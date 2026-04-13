"""
agents/supervision.py - LangGraph conditional edge (routing) functions.

Each function receives the current EcoGraphState and returns a plain string
that matches a key in the workflow's add_conditional_edges mapping.

Why we return strings instead of the END sentinel:
    LangGraph's add_conditional_edges maps string keys -> node names.
    The END sentinel is the string "__end__" internally, so returning
    the literal string is equivalent AND makes the Literal type annotation
    accurate - avoiding a type-checker mismatch. 
"""

import logging
from typing import Literal

from src.agents.state import EcoGraphState

logger = logging.getLogger(__name__)


_END = "__end__"


#after extraction

def route_after_extraction(
        state: EcoGraphState,
) -> Literal["load_graph", "__end__"]:
    """
    triple_files produced AND status != failed -> load_graph
    else -> __end__ (halt workflow)
    """
    if state.get("status") == "failed":
        logger.warning("Extraction failed. Halting workflow.")
        return _END
    
    if state.get("triple_files"):
        return "load_graph"
    
    logger.warning("No triples extracted. Halting workflow.")
    return _END


#after graph loading, before neo4j store


def route_after_graph_load(
        state: EcoGraphState,
) -> Literal["resolve", "__end__"]:
    """
    relationship written > 0 -> resolve
    failed / nothing written -> __end__ (halt workflow)
    """
    if state.get("status") == "failed":
        logger.warning("Graph loading failed. Halting workflow.")
        return _END
    
    written = state.get("neo4j_stats", {}).get("written", 0)
    if written > 0:
        return "resolve"
    
    logger.warning("No relationships written to Neo4j - skipping resolution")
    return _END


#after entity resolution


def route_after_resolution(
        state: EcoGraphState,
) -> Literal["__end__"]:
    """
    Resolution is always the last step"""
    return _END



