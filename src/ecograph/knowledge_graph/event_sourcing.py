"""
src/ecograph/knowledge_graph/event_sourcing.py

Immutable event-sourced observation pattern for the EcoGraph knowledge graph.
Every emission measurement, satellite reading, or ESG disclosure is written
as an Observation node linked to both the Supplier and the Evidence source.
Observations are NEVER updated or deleted - new readings append new nodes.

This satisfies the CSRD / SB 253 audit trail requirement: at any point in time
the graph can be queried to reconstruct exactly what the supply chain looked
like on a specific date, and every assertion traces back to its evidence source.

Design decisions:
- randomUUID() is called inside Cypher (not Python) so the UUID is generated
  in the database transaction, ensuring uniqueness even under concurrent writes.
- MERGE on Evidence nodes deduplicates evidence sources by (source, file)
  so the same PDF or CSV file does not create duplicate Evidence nodes.
- The function returns the observation_id so callers can reference it in
  subsequent relationship creation within the same pipeline run.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from ecograph.knowledge_graph.neo4j_client import Neo4jClient, get_neo4j_client

logger = logging.getLogger(__name__)

#
# Cypher templates
#

_CREATE_OBSERVATION = """
MATCH (s {entity_id: $entity_id})
CREATE (obs:Observation {
    observation_id: randomUUID(),
    timestamp: datetime($timestamp),
    metric: $metric,
    value: $value,
    unit: $unit,
    method: $method,
    confidence: $confidence
})
CREATE (s)-[:HAS_OBSERVATION]->(obs)
RETURN obs.observation_id AS observation_id
"""

_MERGE_EVIDENCE = """
MERGE (ev:Evidence {source: $source, file: $file})
ON CREATE SET ev.evidence_id = randomUUID(),
              ev.ingested_at = datetime($ingested_at)
RETURN ev.evidence_id AS evidence_id
"""

_LINK_OBSERVATION_EVIDENCE = """
MATCH (obs:Observation {observation_id: $observation_id})
MATCH (ev:Evidence {source: $source, file: $file})
MERGE (obs)-[:SUPPORTED_BY]->(ev)
"""

_GET_OBSERVATION_HISTORY = """
MATCH (s {entity_id: $entity_id})-[:HAS_OBSERVATION]->(obs:Observation)
WHERE obs.metric = $metric
RETURN obs.observation_id AS id,
       obs.value        AS value,
       obs.unit         AS unit,
       obs.method       AS method,
       obs.confidence   AS confidence,
       obs.timestamp    AS timestamp
ORDER BY obs.timestamp DESC
LIMIT $limit
"""

#
# Public API
#

def record_observation(
    entity_id: str,
    metric: str,
    value: float,
    unit: str,
    method: str,
    source: str,
    file: str,
    confidence: float = 1.0,
    client: Optional[Neo4jClient] = None,
) -> Optional[str]:
    """
    Append an immutable Observation node to a graph entity and link it to
    its Evidence source.

    Parameters
    ----------
    entity_id:
        The entity_id property of the Supplier / Facility / Company node
        to attach the observation to.
    metric:
        Metric name, e.g. "co2_flux_tonnes_per_year", "scope3_tco2e".
    value:
        Numeric measurement value.
    unit:
        Unit string, e.g. "tCO2e/yr", "mol/m2".
    method:
        Measurement provenance: "self_reported" | "tropomi_cnn" |
        "spend_based" | "heuristic_capacity_factor".
    source:
        Evidence source type: "ERP" | "ESG_PDF" | "SATELLITE" | "SYNTHETIC".
    file:
        Filename or URL the observation came from.
    confidence:
        Extraction or measurement confidence [0, 1].
    client:
        Neo4j client to use. Defaults to process singleton.

    Returns
    -------
    str: The created observation_id, or None if the write failed.
    """
    db = client or get_neo4j_client()
    now = datetime.now(timezone.utc).isoformat()

    try:
        # 1. Create the Observation node
        obs_result = db.execute_write(
            _CREATE_OBSERVATION,
            {
                "entity_id": entity_id,
                "timestamp": now,
                "metric": metric,
                "value": float(value),
                "unit": unit,
                "method": method,
                "confidence": float(confidence),
            }
        )

        if not obs_result:
            logger.warning(
                "Observation creation returned no results - entity_id may not exist.",
                extra={"entity_id": entity_id},
            )
            return None

        observation_id = obs_result[0].get("observation_id")

        # 2. Ensure Evidence node exists
        db.execute_write(
            _MERGE_EVIDENCE,
            {"source": source, "file": file, "ingested_at": now},
        )

        # 3. Link observation to evidence
        db.execute_write(
            _LINK_OBSERVATION_EVIDENCE,
            {"observation_id": observation_id, "source": source, "file": file},
        )

        logger.debug(
            "Observation recorded.",
            extra={
                "entity_id": entity_id,
                "metric": metric,
                "value": value,
                "method": method,
                "observation_id": observation_id,
            },
        )
        return observation_id

    except Exception as exc:
        logger.error(
            "Failed to record observation.",
            extra={"entity_id": entity_id, "metric": metric, "error": str(exc)},
        )
        return None


def get_observation_history(
    entity_id: str,
    metric: str,
    limit: int = 50,
    client: Optional[Neo4jClient] = None,
) -> list[dict]:
    """
    Retrieve the full chronological observation history for an entity metric.

    Returns records in descending timestamp order (most recent first).
    Used by the Data Analyst agent for time-series baseline computation
    and by the Reporter for the audit trail section.

    Parameters
    ----------
    entity_id: Graph entity identifier.
    metric: Metric name to filter by.
    limit: Maximum number of records to return.
    client: Neo4j client (defaults to singleton).

    Returns
    -------
    list[dict]: Each dict contains id, value, unit, method, confidence, timestamp.
    """
    db = client or get_neo4j_client()
    try:
        return db.execute_read(
            _GET_OBSERVATION_HISTORY,
            {"entity_id": entity_id, "metric": metric, "limit": limit},
        )
    except Exception as exc:
        logger.error(
            "Failed to retrieve observation history.",
            extra={"entity_id": entity_id, "metric": metric, "error": str(exc)},
        )
        return []


def record_observations_batch(
    observations: list[dict],
    client: Optional[Neo4jClient] = None,
) -> dict[str, int]:
    """
    Write multiple observations in sequence.

    Each dict in observations must contain the same keys as the
    record_observation function parameters.

    Returns dict with keys: written, errors.
    """
    written = 0
    errors = 0
    db = client or get_neo4j_client()

    for obs in observations:
        result = record_observation(
            entity_id=obs["entity_id"],
            metric=obs["metric"],
            value=obs["value"],
            unit=obs.get("unit", "tCO2e/yr"),
            method=obs.get("method", "unknown"),
            source=obs.get("source", "SYNTHETIC"),
            file=obs.get("file", ""),
            confidence=obs.get("confidence", 1.0),
            client=db,
        )
        if result:
            written += 1
        else:
            errors += 1

    logger.info(
        "Batch observation write complete.",
        extra={"total": len(observations), "written": written, "errors": errors},
    )
    return {"written": written, "errors": errors}