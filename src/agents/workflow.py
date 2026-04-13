"""
agents/workflow.py - LangGraph graph builder for the Ecograph pipeline.

This file only builds and compiles the graph.
Node logic  -> src/agents/nodes.py
Routing -> src/agents/supervision.py
State shape  -> src/agents/state.py

Graph topology:
    [START]
       |
    extract  -> load_graph  -> resolve  -> [END]
       |            |
      [END]     [END]
"""

import logging 

from langgraph.graph import END, StateGraph


from src.agents.nodes import node_extract, node_load_graph, node_resolve
from src.agents.state import EcoGraphState, initial_state
from src.agents.supervision import(
    route_after_extraction,
    route_after_graph_load,
    route_after_resolution,
)

logger = logging.getLogger(__name__)



def build_graph() -> StateGraph:
    """Constructs and compiles the LangGraph state machine."""
    wf = StateGraph(EcoGraphState)

    #nodes
    wf.add_node("extract", node_extract)
    wf.add_node("load_graph", node_load_graph)
    wf.add_node("resolve", node_resolve)

    #entry point
    wf.set_entry_point("extract")

    #conditional edges - keys match the strings returned by supervision.py
    wf.add_conditional_edges(
        "extract",
        route_after_extraction,
        {"load_graph" : "load_graph", "__end__": END }

    )
    wf.add_conditional_edges(
        "load_graph",
        route_after_graph_load,
        {"resolve": "resolve", "__end__": END}
    
    )
    wf.add_conditional_edges(
        "resolve",
        route_after_resolution,
        {"__end__": END}
    )

    return wf.compile()

def run_pipeline()  -> EcoGraphState:
    """
    Builds the graph and runs it from a clean initial state."""
    graph = build_graph()

    logger.info("=" * 55)
    logger.info(" Ecograph LangGraph Pipeline - starting")
    logger.info("=" * 55)

    final_state = graph.invoke(initial_state())

    status = final_state.get("status", "unknown")
    errors = final_state.get("errors", [])

    logger.info("=" * 55)
    logger.info(f" Pipeline finished - status: {status}")

    if errors:
        for err in errors:
            logger.error(err)

    return final_state


if __name__ == "__main__":
    run_pipeline()
    