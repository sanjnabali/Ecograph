"""
state.py - LangGraph shared state definition for the Ecograph pipeline.

Every Node in the LangGraph workflow reads from and writes to this TypeDict.
LangGraph passes a copy of this dict between nodes automatically.
"""

from typing import TypedDict, List, Optional


class EcoGraphState(TypedDict):
    """
    Shared state that flows through the entire LangGraph pipeline.
    
    Fields
    ------
    parsed_files : List[str]
        Absolute paths to parsed JSON files in data/parsed_content/.
        populated by the 'parse' node (or pre-loaded when skipping parsing).
        
    triple_files : List[str]
        Absolute paths to extracted triples Json files in data/triples/.
        Populated by the 'extract' node.
        
    neo4j_stats : dict
        summary of what was written to Neo4j.
        e.g. {"nodes_created" : 120, "relationship_created": 95, "files_ingested": 5}
        
    resolved : bool
        whether the entity-resolution (deduplication) step has been run.
        
    errors : List[str]
        Accumulated non-fatal error messages from any stage.
        Allows later nodes to report a partial-success summary.
    
    status : str
        Human-readable pipeline status:
        "running" | "extraction_complete" | "graph_loaded" | "resolved" | "failed"
    """

    parsed_files: List[str]
    triple_files: List[str]
    neo4j_stats: dict
    resolved: bool
    errors: List[str]
    status: str

def initial_state() -> EcoGraphState:
    """Returns a clean, empty starting state for a fresh pipeline run."""
    return EcoGraphState(
        parsed_files=[],
        triple_files=[],
        neo4j_stats={},
        resolved=False,
        errors=[],
        status="running",
    )
    
    