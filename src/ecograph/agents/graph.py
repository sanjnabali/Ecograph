"""
src/ecograph/agents/graph.py

LangGraph multi-agent workflow for EcoGraph.

Defines the directed (optionally cyclic) state graph that orchestrates:
Supervisor -> DataAnalyst -> SatelliteIntel -> SupplyCommander
           -> Validator -> Reporter -> END

The supervisor makes all routing decisions. Other agents are pure
transformers: they receive state, produce updated state, and return.
The validator can trigger a single re-run of supply_commander if the
initial plan fails compliance checks.

Design decisions:
- StateGraph is used (not MessageGraph) because agents communicate via
  structured TypedDict fields, not unstructured message lists.
- Conditional edges on the supervisor node use the 'next_agent' field,
  not lambda closures over external state, keeping routing logic visible.
- The MAX_AGENT_ITERATIONS circuit-breaker in supervisor.py prevents
  unbounded loops. LangGraph's own recursion limit provides a second guard.
- compile() is called once at module import via get_agent() singleton,
  ensuring the graph is only built once per process.
"""

from __future__ import annotations

import threading
from typing import Optional

from langgraph.graph import END, StateGraph

from ecograph.agents.state import EcoState
from ecograph.agents import (
    data_analyst,
    reporter,
    satellite_intel,
    supervisor,
    supply_commander,
    validator,
)


def _route_from_supervisor(state: EcoState) -> str:
    """
    Routing function for the supervisor conditional edge.
    Returns the value of state["next_agent"], which the supervisor sets
    on every iteration.
    """
    return state.get("next_agent", "END")


def build_ecograph_agent():
    """
    Construct and compile the EcoGraph LangGraph state graph.

    Returns a compiled CompiledGraph ready for .invoke() or .stream().
    """
    workflow = StateGraph(EcoState)

    # --------------------------------------------------------------------------
    # Register all agent nodes
    # --------------------------------------------------------------------------
    workflow.add_node("supervisor",       supervisor.run)
    workflow.add_node("data_analyst",     data_analyst.run)
    workflow.add_node("satellite_intel",  satellite_intel.run)
    workflow.add_node("supply_commander", supply_commander.run)
    workflow.add_node("validator",        validator.run)
    workflow.add_node("reporter",         reporter.run)

    # --------------------------------------------------------------------------
    # Entry point
    # --------------------------------------------------------------------------
    workflow.set_entry_point("supervisor")

    # --------------------------------------------------------------------------
    # Supervisor routes to any node or END
    # --------------------------------------------------------------------------
    workflow.add_conditional_edges(
        "supervisor",
        _route_from_supervisor,
        {
            "data_analyst":     "data_analyst",
            "satellite_intel":  "satellite_intel",
            "supply_commander": "supply_commander",
            "validator":        "validator",
            "reporter":         "reporter",
            "END":              END,
        },
    )

    # --------------------------------------------------------------------------
    # All worker agents return to supervisor after completion
    # --------------------------------------------------------------------------
    for agent_name in ("data_analyst", "satellite_intel", "supply_commander", "validator"):
        workflow.add_edge(agent_name, "supervisor")

    # --------------------------------------------------------------------------
    # Reporter terminates the pipeline
    # --------------------------------------------------------------------------
    workflow.add_edge("reporter", END)

    return workflow.compile()


# --------------------------------------------------------------------------
# Process-singleton compiled graph
# --------------------------------------------------------------------------
_compiled_graph = None
_graph_lock = threading.Lock()


def get_agent():
    """
    Return the process-singleton compiled EcoGraph agent.

    Thread-safe: uses double-checked locking so only one graph is compiled
    even if multiple threads call get_agent() concurrently on startup.
    """
    global _compiled_graph
    if _compiled_graph is None:
        with _graph_lock:
            if _compiled_graph is None:
                _compiled_graph = build_ecograph_agent()
    return _compiled_graph