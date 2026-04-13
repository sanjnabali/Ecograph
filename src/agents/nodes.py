"""
agents/nodes.py - LangGraph node functions for the Ecograph pipeline

Each function is one node in the graph:
  node_extract -> runs Scope3Extractor
  node_load_graph -> ingests triples into Neo4j
  node_resolve -> deduplicates entity names
  
Keeping nodes seperate from the graph builder (workflow.py) means
each node can be unit-tested independently without building the full graph.
"""

import logging
from pathlib import Path
from typing import Any, Dict

from src.agents.extractor import Scope3Extractor
from src.agents.state import EcographState
from src.config.settings import TRIPLES_DIR
from src.graph.connection import get_driver
from src.graph.store import apply_schema, ingest_all_triples
from src.graph.resolver import resolve_entities

logger = logging.getLogger(__name__)



#LLM triple extraction


def node_extract(state: EcographState) -> Dict[str, Any]:
    """
    Runs Scope3Extractor on all parsed JSON files and saves triples to data/triples/.
    on success: populates triple_files and advance status.
    on hard failure (missing API key): set status = 'failed' .
    """
    logger.info("Node extract - LLM triple extraction starting")
    errors = list(state.get("errors", []))

    try:
        extractor = Scope3Extractor()
        extractor.process_all_documents
    except ValueError as exc:
        errors.append(str(exc))
        logger.error(f"Extraction failed: {exc}")
        return {"status": "failed", "errors" : errors}
    except Exception as exc:
        errors.append(f"Extraction error: {exc}")
        logger.error(f"Extraction failed unexpectedly: {exc}", exc_info=True)
        return {"status": "failed", "errors" : errors}
    
    triple_files = [str(p) for p in TRIPLES_DIR.glob("*_triples.json")]
    logger.info(f"Extraction completed successfully. {len(triple_files)} triple files created.")

    return {
        "triple_files": triple_files,
        "status": "extracted",
        "errors": errors
    }

#noe4j graph loading
def node_load_graph(state: EcographState) -> Dict[str, Any]:
    """
    Connects to Neo4j, applies schema, and ingests triples from triple_files.
    Connection / auth errors mark the pipeline as failed.
    Individual triple write errors are counted but don't stop the run.
    """
    logger.info("Node load_graph - Neo4j ingestion starting")
    errors = list(state.get("errors", []))

    try:
        driver = get_driver()
        apply_schema(driver)
        stats = ingest_all_triples(driver)
        driver.close()
    except (EnvironmentError, ConnectionError, PermissionError) as exc:
        errors.append(str(exc))
        logger.error(f"Neo4j connection/auth failed: {exc}")
        return {"status": "failed", "errors": errors, "neo4j_stats": None}
    except Exception as exc:
        errors.append(f"Neo4j load error: {exc}")
        logger.error(f"Neo4j ingestion failed unexpectedly: {exc}", exc_info=True)
        return {"status": "failed", "errors": errors, "neo4j_stats": {}}
    
    logger.info(f"Load done - {stats}")
    return{
        "neo4j_stats": stats,
        "status": "graph_loaded",
        "errors": errors
    }

#Entity resolution
def node_resolve(state: EcographState) -> Dict[str, Any]:
    """
    Runs entity resolution on the Neo4j graph to deduplicate entities.
    any failure is logged but does not mark the pipeline as failed, 
    since the graph is still fully functional and resolution can be re-run later.
    Individual resolution errors are counted but don't stop the run.
    """
    logger.info("Node resolve - Entity resolution starting")
    errors = list(state.get("errors", []))

    try:
        driver = get_driver()
        summary = resolve_entities(driver)
        driver.close()
        logger.info(f"Resolution done: {summary}")
    except Exception as exc:
        errors.append(f"Entity resolution error: {exc}")
        logger.error(f"Entity resolution failed unexpectedly: {exc}", exc_info=True)
        return {"resolved": False, "status": "graph_loaded", "errors": errors}
    
    return{
        "resolved": True,
        "status": "resolved",
        "errors": errors
    }