"""
graph/store.py - Schema setup and triple ingestion into Neo4j.

Responsibilities
----------------
1. apply_schema()       - create constraints + indexes (idempotent)
2. ingest_triples_file() - write one *_triples.json file to Neo4j
3. ingest_all_triples() - batch ingest everything in data/triples/

Triple -> Cypher mapping uses MERGE, so re-running is always safe.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from neo4j import Driver
from neo4j import exceptions as neo4j_exc

from src.config.settings import TRIPLES_DIR
from src.graph.schema import (
    SCHEMA_CONSTRAINTS,
    SCHEMA_INDEXES,
    NodeLabel,
    RelType,
)

logger = logging.getLogger(__name__)

# Regex: relationship type identifiers in Cypher must be [A-Za-z0-9_]
# Any other character is replaced with _ to prevent Cypher injection / syntax errors.
_SAFE_REL_RE = re.compile(r"[^A-Z0-9_]")

# -----------------------------------------------------------------------------
# Schema Setup
# -----------------------------------------------------------------------------

def apply_schema(driver: Driver) -> None:
    """
    Applies all constraints and indexes from schema.py.
    Uses IF NOT EXISTS so it is completely idempotent - safe on every run.
    """
    logger.info("Applying graph schema (constraints + indexes)...")
    with driver.session() as session:
        for stmt in SCHEMA_CONSTRAINTS:
            try:
                session.run(stmt)
            except Exception as exc:
                logger.debug(f"Constraint skipped (likely already exists): {exc}")
        for stmt in SCHEMA_INDEXES:
            try:
                session.run(stmt)
            except Exception as exc:
                logger.debug(f"Index skipped (likely already exists): {exc}")
    logger.info("Schema setup complete.")


# -----------------------------------------------------------------------------
# Triple -> Cypher Mapping
# -----------------------------------------------------------------------------

# Which Node label to assign to the *object* based on the predicate
_OBJ_LABEL: Dict[str, str] = {
    RelType.REPORTS_EMISSION:    NodeLabel.EMISSION_METRIC,
    RelType.FALLS_UNDER_SCOPE:   NodeLabel.SCOPE,
    RelType.MEASURED_IN_YEAR:    NodeLabel.YEAR,
    RelType.BELONGS_TO_CATEGORY: NodeLabel.CATEGORY,
    RelType.COMMITS_TO_NET_ZERO: NodeLabel.YEAR,
    RelType.SETS_TARGET:         NodeLabel.TARGET,
    RelType.TARGETS_REDUCTION:   NodeLabel.EMISSION_METRIC,
    RelType.HAS_SUPPLIER:        NodeLabel.COMPANY,
    RelType.SUPPLIES_TO:         NodeLabel.COMPANY,
    RelType.OPERATES_IN:         NodeLabel.REGION,
    RelType.REPORTS_UNDER:       NodeLabel.STANDARD,
    RelType.LOCATED_AT:          NodeLabel.FACILITY,
}

# Override for the *subject* label (default is Company)
_SUBJ_LABEL: Dict[str, str] = {
    RelType.FALLS_UNDER_SCOPE:   NodeLabel.EMISSION_METRIC,
    RelType.MEASURED_IN_YEAR:    NodeLabel.EMISSION_METRIC,
    RelType.BELONGS_TO_CATEGORY: NodeLabel.EMISSION_METRIC,
    RelType.LOCATED_AT:          NodeLabel.FACILITY,
}

# Labels where the identity property is 'value' instead of 'name'
_VALUE_LABELS = {NodeLabel.EMISSION_METRIC, NodeLabel.YEAR}

def _build_merge_cypher(triple: Dict[str, Any]) -> Tuple[str, dict]:
    """
    Converts a triple dict into a parameterised Cypher MERGE statement.

    Returns ("", {}) for triples that are missing subject or object,
    so callers can skip them cleanly.

    Predicate sanitisation:
    1. Upper-case + spaces -> underscores (e.g. "reports emission" -> "REPORTS_EMISSION")
    2. Strip any character that is not [A-Z0-9_] to prevent Cypher injection.
    3. Collapse consecutive underscores and trim leading/trailing underscores.
    """
    raw_predicate = triple.get("predicate", "RELATED_TO")
    # Step 1: normalise case and spaces
    predicate = raw_predicate.upper().replace(" ", "_").replace("-", "_")
    # Step 2: strip unsafe characters
    predicate = _SAFE_REL_RE.sub("_", predicate)
    # Step 3: collapse runs of underscores, strip edges
    predicate = re.sub(r"_+", "_", predicate).strip("_") or "RELATED_TO"

    subject_name = (triple.get("subject") or "").strip()
    object_name  = (triple.get("object_value") or "").strip()
    metadata     = triple.get("metadata") or {}

    if not subject_name or not object_name:
        return "", {}

    subj_label = _SUBJ_LABEL.get(predicate, NodeLabel.COMPANY)
    obj_label  = _OBJ_LABEL.get(predicate, "Entity")

    subj_prop = "value" if subj_label in _VALUE_LABELS else "name"
    obj_prop  = "value" if obj_label in _VALUE_LABELS else "name"

    cypher = (
        f"MERGE (s:{subj_label} {{{subj_prop}: $subj_name}}) "
        f"MERGE (o:{obj_label} {{{obj_prop}: $obj_name}}) "
        f"MERGE (s)-[r:{predicate}]->(o) "
        f"SET r += $metadata"
    )

    params = {
        "subj_name": subject_name,
        "obj_name":  object_name,
        "metadata":  {k: str(v) for k, v in metadata.items()} if metadata else {},
    }
    return cypher, params

# -----------------------------------------------------------------------------
# Ingestion
# -----------------------------------------------------------------------------

def ingest_triples_file(
    driver: Driver, triples_path: Path
) -> Dict[str, int]:
    """
    Reads one *_triples.json file and writes all triples to Neo4j.

    Returns stats: {"processed": N, "written": N, "skipped": N, "errors": N}
    """
    logger.info(f"Ingesting {triples_path.name}...")

    try:
        with open(triples_path, "r", encoding="utf-8") as fh:
            triples: List[dict] = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error(f"Cannot read {triples_path.name}: {exc}")
        return {"processed": 0, "written": 0, "skipped": 0, "errors": 1}

    stats = {"processed": len(triples), "written": 0, "skipped": 0, "errors": 0}

    def _write_triple(tx, cypher: str, params: dict) -> None:
        tx.run(cypher, **params)

    with driver.session() as session:
        for triple in triples:
            cypher, params = _build_merge_cypher(triple)
            if not cypher:
                stats["skipped"] += 1
                continue
            try:
                session.execute_write(_write_triple, cypher, params)
                stats["written"] += 1
            except neo4j_exc.CypherSyntaxError as exc:
                logger.error(f"Cypher error for {triple}: {exc}")
                stats["errors"] += 1
            except Exception as exc:
                logger.warning(f"Write failed for {triple}: {exc}")
                stats["errors"] += 1

    logger.info(
        f"  {triples_path.name}: "
        f"{stats['written']} written | "
        f"{stats['skipped']} skipped | "
        f"{stats['errors']} errors"
    )
    return stats

def ingest_all_triples(driver: Driver) -> Dict[str, Any]:
    """
    Finds all *_triples.json files in TRIPLES_DIR and ingests them.
    Returns aggregate stats.
    """
    if not TRIPLES_DIR.exists():
        logger.error(
            f"Triples directory not found: {TRIPLES_DIR}. "
            "Run the extraction step first."
        )
        return {}

    triple_files = sorted(TRIPLES_DIR.glob("*_triples.json"))
    if not triple_files:
        logger.warning(f"No triple files found in {TRIPLES_DIR}.")
        return {}

    logger.info(f"Found {len(triple_files)} triple file(s). Starting Neo4j ingestion...")

    totals: Dict[str, int] = {
        "files_ingested": 0, "processed": 0,
        "written": 0, "skipped": 0, "errors": 0,
    }

    for tf in triple_files:
        stats = ingest_triples_file(driver, tf)
        totals["files_ingested"] += 1
        for key in ("processed", "written", "skipped", "errors"):
            totals[key] += stats.get(key, 0)

    logger.info(
        f"Ingestion complete - "
        f"{totals['files_ingested']} files | "
        f"{totals['written']} relationships written | "
        f"{totals['errors']} errors"
    )
    return totals

# -----------------------------------------------------------------------------
# Ad-hoc query helper  (used by Streamlit UI)
# -----------------------------------------------------------------------------

def run_query(
    driver: Driver,
    cypher: str,
    params: Optional[dict] = None,
) -> List[dict]:
    """Runs a read Cypher query and returns results as a list of dicts."""
    with driver.session() as session:
        result = session.run(cypher, **(params or {}))
        return [record.data() for record in result]

# -----------------------------------------------------------------------------
# Standalone entry point
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    from src.graph.connection import get_driver
    try:
        drv = get_driver()
        apply_schema(drv)
        result = ingest_all_triples(drv)
        logger.info(f"Done: {result}")
        drv.close()
    except (EnvironmentError, ConnectionError, PermissionError) as exc:
        logger.critical(str(exc))
    except Exception as exc:
        logger.critical(f"Unexpected failure: {exc}", exc_info=True)