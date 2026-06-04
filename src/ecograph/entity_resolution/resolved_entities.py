"""
src/ecograph/entity_resolution/resolved_entities.py

Post-processing of Splink predictions: assign canonical entity IDs and
persist cluster membership to the graph database.

After Splink scores all candidate pairs, this module:
1. Loads the scored pair predictions from the Splink DuckDB.
2. Applies a configurable match-probability threshold (default 0.85).
3. Builds connected components (clusters) over matched pairs using
   Union-Find, assigning a stable canonical_id to each cluster.
4. Writes the cluster membership back to Neo4j so that
   Supplier nodes from different ERP extracts / ESG PDFs resolve to the
   same canonical entity.

Design decisions:
- canonical_id is a deterministic UUID-v5 derived from the sorted member IDs
  so re-running the pipeline produces the same IDs.
- Union-Find is implemented without external graph library to avoid adding
  a heavy dependency just for this step.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

_CANONICAL_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # UUID v5 namespace


# -----------------------------------------------------------------------------
# Union-Find (disjoint set union)
# -----------------------------------------------------------------------------
class _UnionFind:
    def __init__(self) -> None:
        self._parent: dict[str, str] = {}
        self._rank: dict[str, int] = {}

    def find(self, x: str) -> str:
        self._parent.setdefault(x, x)
        self._rank.setdefault(x, 0)
        if self._parent[x] != x:
            self._parent[x] = self.find(self._parent[x])  # path compression
        return self._parent[x]

    def union(self, x: str, y: str) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return

        # Union by rank
        if self._rank[rx] < self._rank[ry]:
            rx, ry = ry, rx
        self._parent[ry] = rx
        if self._rank[rx] == self._rank[ry]:
            self._rank[rx] += 1

    def clusters(self) -> dict[str, list[str]]:
        """Return {root_id: [member_id, ...]} for all clusters."""
        groups: dict[str, list[str]] = {}
        for node in list(self._parent.keys()):
            root = self.find(node)
            groups.setdefault(root, []).append(node)
        return groups


# -----------------------------------------------------------------------------
# Data classes
# -----------------------------------------------------------------------------
@dataclass
class ResolvedEntity:
    canonical_id: str
    member_ids: list[str]
    confidence: float  # mean match probability within cluster


@dataclass
class ResolutionResult:
    resolved: list[ResolvedEntity]
    n_clusters: int
    n_singletons: int
    n_merged: int


def _derive_canonical_id(member_ids: list[str]) -> str:
    """
    Deterministic UUID-v5 from sorted member IDs.
    Same set of members always produces the same canonical_id.
    """
    key = "|".join(sorted(member_ids))
    return str(uuid.uuid5(_CANONICAL_NAMESPACE, key))


def build_clusters(
    predictions: list[dict],
    threshold: float = 0.85,
) -> ResolutionResult:
    """
    Group entity pairs into clusters based on match probability.

    Parameters
    ----------
    predictions:
        List of dicts with keys: source_id, target_id, match_probability.
    threshold:
        Minimum match probability to consider a pair a match.

    Returns
    -------
    ResolutionResult
    """
    uf = _UnionFind()
    pair_scores: dict[tuple[str, str], list[float]] = {}

    for row in predictions:
        src = str(row.get("source_id", ""))
        tgt = str(row.get("target_id", ""))
        prob = float(row.get("match_probability", 0.0))
        if not src or not tgt:
            continue
        if prob >= threshold:
            uf.union(src, tgt)
            key = (min(src, tgt), max(src, tgt))
            pair_scores.setdefault(key, []).append(prob)

    clusters_raw = uf.clusters()
    resolved: list[ResolvedEntity] = []
    n_singletons = 0
    n_merged = 0

    for root, members in clusters_raw.items():
        # Collect all pair scores involving cluster members
        cluster_probs = []
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                key = (min(members[i], members[j]), max(members[i], members[j]))
                cluster_probs.extend(pair_scores.get(key, []))

        avg_conf = float(sum(cluster_probs)) / len(cluster_probs) if cluster_probs else 1.0
        canonical_id = _derive_canonical_id(members)
        resolved.append(ResolvedEntity(
            canonical_id=canonical_id,
            member_ids=sorted(members),
            confidence=avg_conf,
        ))

        if len(members) == 1:
            n_singletons += 1
        else:
            n_merged += 1

    logger.info(
        "Entity resolution complete: %d clusters (%d merged, %d singletons).",
        len(resolved), n_merged, n_singletons,
    )
    return ResolutionResult(
        resolved=resolved,
        n_clusters=len(resolved),
        n_singletons=n_singletons,
        n_merged=n_merged,
    )


def write_canonical_ids_to_neo4j(
    result: ResolutionResult,
    client=None,
) -> int:
    """
    Persist canonical_id to each Supplier node's member IDs in Neo4j.

    For each resolved entity, MATCH all Supplier nodes whose entity_id
    is in member_ids and SET supplier.canonical_id = canonical_id.

    Returns count of nodes updated.
    """
    from ecograph.knowledge_graph.neo4j_client import get_neo4j_client

    db = client or get_neo4j_client()
    _CYPHER = """
    UNWIND $rows AS row
    MATCH (s {entity_id: row.member_id})
    SET s.canonical_id = row.canonical_id,
        s.resolution_confidence = row.confidence
    """

    rows = []
    for entity in result.resolved:
        for mid in entity.member_ids:
            rows.append({
                "member_id": mid,
                "canonical_id": entity.canonical_id,
                "confidence": entity.confidence,
            })

    if not rows:
        return 0

    try:
        db.execute_write_many(_CYPHER, rows)
        logger.info("Wrote canonical_id to %d supplier nodes.", len(rows))
        return len(rows)
    except Exception as exc:
        logger.error("Failed to write canonical IDs to Neo4j: %s", exc)
        return 0