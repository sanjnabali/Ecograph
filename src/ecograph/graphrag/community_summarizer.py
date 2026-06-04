"""
src/ecograph/graphrag/community_summarizer.py

Leiden community detection + LLM-based thematic summarisation.

Workflow:
1. Export the supply-chain graph from Neo4j as a NetworkX graph.
2. Run the Leiden algorithm (via the `leidenalg` library, which wraps the
   C++ implementation) to detect supply-chain communities.
3. For each community, extract the top-N nodes by betweenness centrality.
4. Call the Groq LLM to generate a 2-3 sentence thematic summary of
   what the community represents (e.g. "East-Asian electronics manufacturing
   cluster dominated by TSMC and Samsung with high Scope-3 intensity").
5. Store summaries in the Qdrant vector store for GraphRAG retrieval.

The community summaries are the primary retrieval units in the GraphRAG
pipeline: dense retrieval returns the most relevant community summaries,
which are then stitched into the prompt alongside the subgraph context.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# Data model
# --------------------------------------------------------------------------

@dataclass
class CommunityRecord:
    community_id: str
    node_count: int
    top_nodes: list[str]
    summary: str  # LLM-generated thematic description
    avg_co2_scope3: Optional[float]  # mean CO2 intensity of community members


# Graph export from Neo4j
# --------------------------------------------------------------------------

_EXPORT_CYPHER = """
MATCH (a:Supplier)-[r:SUPPLIES|MANUFACTURES|SOURCES_FROM]->(b:Supplier)
RETURN a.entity_id AS src, b.entity_id AS tgt,
coalesce(r.weight, 1.0) AS weight
LIMIT 50000
"""

_NODE_CYPHER = """
MATCH (s:Supplier)
RETURN s.entity_id AS entity_id,
coalesce(s.name, s.entity_id) AS name,
coalesce(s.co2_scope3, 0.0) AS co2_scope3
"""

def _build_networkx_graph(client) -> tuple:
    """Return (G, node_meta) where G is a networkx.DiGraph."""
    try:
        import networkx as nx  # type: ignore[import]
    except ImportError as exc:
        raise ImportError("networkx is required for community detection.") from exc

    G = nx.DiGraph()

    node_rows = client.execute_read(_NODE_CYPHER, {})
    node_meta: dict[str, dict] = {}
    for row in node_rows:
        eid = row["entity_id"]
        G.add_node(eid)
        node_meta[eid] = {"name": row["name"], "co2_scope3": row.get("co2_scope3", 0.0)}

    edge_rows = client.execute_read(_EXPORT_CYPHER, {})
    for row in edge_rows:
        G.add_edge(row["src"], row["tgt"], weight=row["weight"])
    return G, node_meta


# Community detection
# --------------------------------------------------------------------------

def _detect_communities(G) -> list[set]:
    """
    Run Leiden on the undirected version of G.
    Falls back to connected components if leidenalg is not installed.
    """
    try:
        import igraph as ig  # type: ignore[import]
        import leidenalg  # type: ignore[import]

        undirected = G.to_undirected()
        edges = list(undirected.edges())
        ig_graph = ig.Graph(
            n=len(G),
            edges=[(list(G.nodes()).index(u), list(G.nodes()).index(v)) for u, v in edges],
            directed=False,
        )
        partition = leidenalg.find_partition(
            ig_graph, leidenalg.ModularityVertexPartition
        )
        nodes_list = list(G.nodes())
        return [set(nodes_list[i] for i in part) for part in partition]
    except ImportError:
        logger.warning(
            "leidenalg / igraph not installed - using weakly connected components."
        )
        import networkx as nx  # type: ignore[import]
        return [c for c in nx.weakly_connected_components(G)]


def _top_nodes_by_centrality(G, community: set, top_n: int = 5) -> list[str]:
    """Return the top-N nodes by degree centrality within the community subgraph."""
    try:
        import networkx as nx  # type: ignore[import]
        sub = G.subgraph(community)
        centrality = nx.degree_centrality(sub)
        ranked = sorted(centrality.items(), key=lambda x: x[1], reverse=True)
        return [k for k, _ in ranked[:top_n]]
    except Exception:
        return list(community)[:top_n]


# LLM summarisation
# --------------------------------------------------------------------------

_SUMMARY_PROMPT = """\
You are an ESG supply-chain analyst. Below is a list of supplier entities
that form a detected supply-chain community (cluster).

Top entities by centrality: {top_names}
Number of entities in cluster: {n}
Average Scope-3 CO2 intensity: {avg_co2:.0f} tC02e/yr

Write exactly 2-3 sentences describing:
1. What this cluster likely represents (region, industry, product type).
2. The carbon risk profile.
Do NOT use bullet points. Do NOT use markdown. Output plain text only."""


def _summarise_community(
    top_names: list[str],
    n: int,
    avg_co2: float,
    llm_client,
) -> str:
    prompt = _SUMMARY_PROMPT.format(
        top_names=", ".join(top_names),
        n=n,
        avg_co2=avg_co2,
    )
    try:
        return llm_client.complete(prompt).strip()
    except Exception as exc:
        logger.warning("Community summary LLM call failed: %s", exc)
        return f"Supply-chain cluster with {n} entities. Top members: {', '.join(top_names)}."


# Main entry point
# --------------------------------------------------------------------------

def build_community_summaries(
    neo4j_client=None,
    llm_client=None,
    vector_store=None,
    min_community_size: int = 3,
) -> list[CommunityRecord]:
    """
    Run the full community summarisation pipeline.

    1. Export graph from Neo4j.
    2. Detect communities with Leiden.
    3. Summarise each community with Groq.
    4. Upsert summaries to the Qdrant vector store.

    Parameters
    ----------
    neo4j_client: Neo4j client (defaults to singleton).
    llm_client: Groq LLM client (defaults to singleton).
    vector_store: Qdrant vector store (defaults to singleton).
    min_community_size:
        Skip communities smaller than this.

    Returns
    -------
    list[CommunityRecord]
    """
    from ecograph.knowledge_graph.neo4j_client import get_neo4j_client
    from ecograph.llm import get_groq_client
    from ecograph.graphrag.vector_store import get_vector_store

    db = neo4j_client or get_neo4j_client()
    llm = llm_client or get_groq_client()
    vs = vector_store or get_vector_store()

    try:
        G, node_meta = _build_networkx_graph(db)
    except Exception as exc:
        logger.error("Failed to export graph from Neo4j: %s", exc)
        return []

    if len(G) == 0:
        logger.warning("Graph is empty - no communities to detect.")
        return []

    communities = _detect_communities(G)
    logger.info("Detected %d communities.", len(communities))

    records: list[CommunityRecord] = []

    for idx, community in enumerate(communities):
        if len(community) < min_community_size:
            continue

        top_ids = _top_nodes_by_centrality(G, community)
        top_names = [node_meta.get(nid, {}).get("name", nid) for nid in top_ids]
        co2_vals = [node_meta.get(nid, {}).get("co2_scope3", 0.0) for nid in community]
        avg_co2 = sum(co2_vals) / len(co2_vals) if co2_vals else 0.0

        summary = _summarise_community(top_names, len(community), avg_co2, llm)

        community_id = f"community_{idx:04d}"
        record = CommunityRecord(
            community_id=community_id,
            node_count=len(community),
            top_nodes=top_names,
            summary=summary,
            avg_co2_scope3=avg_co2,
        )
        records.append(record)

        # Upsert to vector store
        try:
            vs.upsert(
                doc_id=community_id,
                text=summary,
                metadata={
                    "type": "community",
                    "node_count": len(community),
                    "avg_co2": avg_co2,
                    "top_nodes": ", ".join(top_names),
                },
            )
        except Exception as exc:
            logger.warning("Failed to upsert community %s to vector store: %s", community_id, exc)

    logger.info("Built %d community summaries.", len(records))
    return records