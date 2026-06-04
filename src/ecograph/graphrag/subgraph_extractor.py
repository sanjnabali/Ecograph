"""
src/ecograph/graphrag/subgraph_extractor.py

Entity neighbourhood extraction from the Neo4j knowledge graph.

Given a list of entity identifiers (supplier IDs, canonical_ids, etc.),
this module retrieves the local subgraph up to a configurable hop depth
and serialises it as a structured text block that can be injected into
the GraphRAG prompt context.

Design:
- Returns both the raw graph data (nodes + relationships) and a
  pre-formatted text summary for LLM consumption.
- Hops are limited to 2 by default to keep the context window bounded.
- All Cypher queries are read-only (MATCH only).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Cypher
# --------------------------------------------------------------------------

_SUBGRAPH_CYPHER = """
MATCH path = (center)-[*1..{hops}]-(neighbor)
WHERE center.entity_id IN $entity_ids
   OR center.canonical_id IN $entity_ids
WITH nodes(path) AS ns, relationships(path) AS rels
UNWIND ns AS n
WITH DISTINCT n, rels
RETURN
    n.entity_id    AS entity_id,
    n.name         AS name,
    labels(n)      AS labels,
    n.country_code AS country,
    n.co2_scope3   AS co2_scope3,
    rels
LIMIT 200
"""

_RELATIONSHIP_CYPHER = """
MATCH (a)-[r]->(b)
WHERE (a.entity_id IN $entity_ids OR a.canonical_id IN $entity_ids)
   OR (b.entity_id IN $entity_ids OR b.canonical_id IN $entity_ids)
RETURN
    a.entity_id    AS source_id,
    a.name         AS source_name,
    type(r)        AS rel_type,
    r.weight       AS weight,
    b.entity_id    AS target_id,
    b.name         AS target_name
LIMIT 300
"""

# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------

@dataclass
class SubgraphContext:
    """
    Structured representation of a neighbourhood subgraph.

    Attributes
    ----------
    nodes:
        List of dicts with entity_id, name, labels, country, co2_scope3.
    edges:
        List of dicts with source_id, source_name, rel_type, weight,
        target_id, target_name.
    text_summary:
        Human-readable text block injected into the LLM prompt.
    """
    nodes: list[dict]
    edges: list[dict]
    text_summary: str
    query_ids: list[str]


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------

def extract_subgraph(
    entity_ids: list[str],
    hops: int = 2,
    client=None,
) -> SubgraphContext:
    """
    Retrieve the local subgraph for the given entity IDs.

    Parameters
    ----------
    entity_ids:
        List of entity_id or canonical_id values to centre the subgraph on.
    hops:
        Hop depth (default 2). Values > 3 may be slow on large graphs.
    client:
        Neo4j client. Defaults to process singleton.

    Returns
    -------
    SubgraphContext
    """
    from ecograph.knowledge_graph.neo4j_client import get_neo4j_client

    db = client or get_neo4j_client()

    if not entity_ids:
        return SubgraphContext(nodes=[], edges=[], text_summary="No entities provided.", query_ids=[])

    # Clamp hops to avoid extremely expensive traversals
    hops = max(1, min(hops, 3))
    cypher = _SUBGRAPH_CYPHER.format(hops=hops)

    nodes: list[dict] = []
    edges: list[dict] = []

    try:
        raw_nodes = db.execute_read(cypher, {"entity_ids": entity_ids})
        nodes = [
            {
                "entity_id": r.get("entity_id", ""),
                "name": r.get("name", ""),
                "labels": r.get("labels", []),
                "country": r.get("country", ""),
                "co2_scope3": r.get("co2_scope3"),
            }
            for r in raw_nodes
            if r.get("entity_id")
        ]
    except Exception as exc:
        logger.warning("Subgraph node query failed: %s", exc)

    try:
        raw_edges = db.execute_read(_RELATIONSHIP_CYPHER, {"entity_ids": entity_ids})
        edges = [
            {
                "source_id": r.get("source_id", ""),
                "source_name": r.get("source_name", ""),
                "rel_type": r.get("rel_type", ""),
                "weight": r.get("weight"),
                "target_id": r.get("target_id", ""),
                "target_name": r.get("target_name", ""),
            }
            for r in raw_edges
        ]
    except Exception as exc:
        logger.warning("Subgraph edge query failed: %s", exc)

    text_summary = _format_subgraph_text(nodes, edges)
    return SubgraphContext(
        nodes=nodes,
        edges=edges,
        text_summary=text_summary,
        query_ids=entity_ids,
    )


def _format_subgraph_text(nodes: list[dict], edges: list[dict]) -> str:
    """Serialise subgraph to a compact text block for LLM injection."""
    lines: list[str] = ["=== SUPPLY CHAIN SUBGRAPH ==="]

    if nodes:
        lines.append(f"\nEntities ({len(nodes)}):")
        for n in nodes[:50]:  # cap at 50 to protect context window
            co2 = f" [co2_scope3={n['co2_scope3']:.0f} tCO2e]" if n.get("co2_scope3") else ""
            lines.append(
                f" - [{'/'.join(n['labels'])}] {n['name'] or n['entity_id']} "
                f"(country={n['country']}){co2}"
            )

    if edges:
        lines.append(f"\nRelationships ({len(edges)}):")
        for e in edges[:80]:
            w = f" [weight={e['weight']:.2f}]" if e.get("weight") is not None else ""
            lines.append(
                f" - {e['source_name'] or e['source_id']} "
                f"--[{e['rel_type']}]--> "
                f"{e['target_name'] or e['target_id']}{w}"
            )

    if not nodes and not edges:
        lines.append("No graph data available for the requested entities.")

    return "\n".join(lines)