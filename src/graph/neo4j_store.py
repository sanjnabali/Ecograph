"""
neo4j_store.py - Neo4j connection, schema setup, and triple ingestion.

Responsibilities
----------------
1. Connect to Neo4j using credentials from .env
2. Apply schema constraints and indexes (idempotent - safe to run multiple times)
3. Ingest extracted triples from data/triples/*.json into the graph
4. Provide a query helper for ad-hoc Cypher execution
"""

import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional, Any

from dotenv import load_dotenv
from neo4j import GraphDatabase, Driver, exceptions as neo4j_exc

from src.graph.schema import SCHEMA_CONSTRAINTS, SCHEMA_INDEXES, NodeLabel, RelType

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)



def get_driver() -> Driver:
    """
    Creates and return a Neo4j Driver from environment variables.
    Raises a clear error if any required variable is missing.
    """
    uri = os.getenv("NEO4J_URI")
    username = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    
    missing = [k for k, v in {"NEO4J_URI": uri, "NEO4J_USERNAME": username, "NEO4J_PASSWORD": password}.items() if not v]
    if missing:
        raise EnvironmentError(f"Missing Neo4j env variable(s): {', '.join(missing)}"
                                "add them to your .env file.")
    
    try:
        driver = GraphDatabase.driver(uri, auth=(username, password))
        driver.verify_connectivity()
        logger.info(f"Neo4j connected uri={uri} user={username}")
        return driver
    except neo4j_exc.ServiceUnavailable as e:
        raise ConnectionError(
            f"Cannot reach Neo4j at '{uri}."
            "Is Neo4j Desktop / AuthDB running? \n"
            f"Original error: {e}"
        )
    except neo4j_exc.AuthError as e:
        raise PermissionError(
            "Neo4j authentication failed."
            "check NEO4J_USERNAME and NEO4J_PASSWORD in your .env file."
        ) from e
    

def apply_schema(driver: Driver):
    """
    Applies all uniqueness constraints and indexes defined in schema.py
    Uses IF NOT EXISTS - completely idempotent and safe to call on every run.
    """
    logger.info("Applying schema constraints and indexes")
    with driver.session() as session:
        for stmt in SCHEMA_CONSTRAINTS:
            try: 
                session.run(stmt)
            except Exception as e:
                logger.warning(f"Constraint statement skipped: {e}")
            
        for stmt in SCHEMA_INDEXES:
            try:
                session.run(stmt)
            except Exception as e:
                logger.warning(f"Index statement skipped: {e}")
    logging.info("Schema constraints and indexes applied")



_PREDICATE_OBJECT_LABEL: Dict[str, str] = {
    RelType.REPORTS_EMISSION: NodeLabel.Emission_METRIC,
    RelType.FALLS_UNDER_SCOPE: NodeLabel.SCOPE,
    RelType.MEASURED_IN_YEAR: NodeLabel.YEAR,
    RelType.BELONGS_TO_CATEGORY: NodeLabel.CATEGORY,
    RelType.COMMITS_TO_NET_ZERO: NodeLabel.YEAR,
    RelType.SETS_TARGET: NodeLabel.TARGET,
    RelType.TARGETS_REDUCTION: NodeLabel.EMISSION_METRIC,
    RelType.HAS_SUPPLIER: NodeLabel.COMPANY,
    RelType.SUPPLIES_TO: NodeLabel.COMPANY,
    RelType.OPERATES_IN: NodeLabel.REGION,
    RelType.REPORTS_UNDER: NodeLabel.STANDARD,
    RelType.LOCATED_AT: NodeLabel.FACILITY,
}


_PREDICATE_SUBJECT_LABEL: Dict[str, str] = {
    RelType.LOCATED_AT: NodeLabel.FACILITY,
    RelType.FALLS_UNDER_SCOPE: NodeLabel.EMISSION_METRIC,
    RelType.MEASURED_IN_YEAR: NodeLabel.EMISSION_METRIC,
    RelType.BELONGS_TO_CATEGORY: NodeLabel.EMISSION_METRIC,

}

def _infer_subject_label(predicate: str) -> str:
    return _PREDICATE_SUBJECT_LABEL.get(predicate, NodeLabel.COMPANY)

def _infer_object_label(predicate: str) -> str:
    return _PREDICATE_OBJECT_LABEL.get(predicate, "Entity")

def _build_merge_cypher(triple: Dict[str, Any]) -> tuple[str, dict]:
    """
    converts a triple dict into a parametrised cypher Merge statement.
    
    Strategy: Merge on name/value so duplicate triples from different
    documents are indempotent - they update properties instead of creating
    duplicate nodes.
    """

    predicate = triple.get("predicate", "RELATED_TO").upper().replace(" ", "_")
    subject_name = triple.get("subject", "").strip()
    object_name = triple.get("object_value", "").strip()
    metadata = triple.get("metadata", {})

    if not subject_name or not object_name:
        return "", {}
    
    subj_label = _infer_subject_label(predicate)
    obj_label = _infer_object_label(predicate)

    subj_prop = "value" if subj_label in (NodeLabel.EMISSION_METRIC, NodeLabel.YEAR) else "name"
    obj_prop = "value" if obj_label in (NodeLabel.EMISSION_METRIC, NodeLabel.YEAR) else "name"

    cypher = f"""
       MERGE (s:{subj_label} {{{subj_prop}: $subj_name}})
       MERGE (o:{obj_label} {{{obj_prop}: $obj_name}})
       MERGE (s)-[r:{predicate}]->(o)
       SET r += $metadata
       RETURN count(r) AS rels_created
    """

    params = {
        "subj_name": subject_name,
        "obj_name": object_name,
        "metadata": {k: str(v) for k, v in metadata.items()} if metadata else {},
    }
    return cypher.strip(), params


def ingest_triples_file(driver: Driver, triples_path: Path) -> Dict[str, int]:
    """
    Reads a single *_triples.json file and writes every triple to Neo4j.
    
    Returns a stats dict: {"processed": N, "written": N, "skipped": N, "errors": N }
    """
    logger.info(f"Ingesting triples from {triples_path.name}")

    try:
        with open(triples_path, 'r', encoding='utf-8') as f:
            triples: List[dict] = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Cannot read {triples_path.name}: {e}")
        return {"processed": 0, "written": 0, "skipped": 0, "errors": 0}
    
    stats = {"processed": len(triples), "written": 0, "skipped": 0, "errors": 0}

    with driver.session() as session:
        for triple in  triples:
            cypher, params = _build_merge_cypher(triple)
            if not cypher:
                stats["skipped"] += 1
                continue
            try:
                session.run(cypher, **params)
                stats["written"]+=1
            except neo4j_exc.CypherSyntaxError as e:
                logger.error(f"Cypher syntax error for triple {triple}: {e}")
                stats["errors"] += 1
            except Exception as e:
                logger.warning(f"failed to write triple {triple}: {e}")
                stats["errors"] += 1

    logger.info(
        f" {triples_path.name}: "
        f"{stats['written']} written | {stats['skipped']} skipped | {stats['errors']} errors"
    )
    return stats

def ingest_all_triples(driver: Driver) -> Dict[str, Any]:
    """
    Finds all *triples.json files in data/triples/ and ingest them all
    Returns an aggregate stats summary
    """
    project_root = Path(__file__).resolve().parent.parent.parent
    triples_dir = project_root / "data" / "triples"

    if not triples_dir.exist():
        logger.error(f"Triples directory not found: {triples_dir}. run tools.py first")
        return {}
    

    triple_files = list(triples_dir.glob("*_triples.json"))
    if not triple_files:
        logger.warning(f"No triple files found in {triples_dir}")
        return {}
    
    logger.info(f"found {len(triple_files)} triple file(s). starting neo4j ingestion")

    total = {"file_ingested": 0, "processed": 0, "written": 0, "skipped": 0, "errors": 0}

    for tf in triple_files:
        stats = ingest_triples_file(driver, tf)
        total["file_ingested"] += 1
        for key in ("processed", "written", "skipped", "errors"):
            total[key] += stats.get(key, 0)

    logger.info(
        f"Ingestion complete -"
        f"{total['file_ingested']} files "
        f"{total['written']} relationships written "
        f"{total['errors']} errors"
    )
    return total

def run_query(driver: Driver, cypher:str, params: Optional[dict] = None) -> List[dict]:
    """
    Runs an arbitary read cypher query and returns results as a list of dicts.
    Useful for the UI and debugging
    """

    with driver.session() as session:
        result = session.run(cypher, **(params or {}))
        return [record.data() for record in result]
    

if __name__ == "__main__":
    try:
        driver = get_driver()
        apply_schema(driver)
        stats = ingest_all_triples(driver)
        logger.info("final stats: {stats}")
        driver.close()
    except (EnvironmentError, ConnectionError, PermissionError) as e:
        logger.critical(str(e))
    except Exception as e:
        logger.critical(f"Unexcepted failure during Neo4j ingestion: {e}", exc_info=True)




    



    



            




