"""
src/ecograph/agents/supervisor.py

Supervisor agent: the central orchestrator of the EcoGraph multi-agent pipeline.

Responsibilities:
- Parse the user query to determine which agents to invoke and in what order.
- Route between agents based on what has been completed and what is outstanding.
- Guard against infinite loops via iteration_count.
- Attach initial metadata (timestamps, model versions) to state.

Design decisions:
- The supervisor uses Groq (Llama-3.3-70b) to perform intent classification
  rather than hard-coded routing rules. This allows the pipeline to handle
  novel query types gracefully.
- Routing is deterministic once intent is classified: the supervisor does
  NOT re-query the LLM on subsequent hops. It uses the pipeline_plan list
  stored in state on the first call and advances a pointer on each call.
- MAX_AGENT_ITERATIONS acts as a hard circuit-breaker regardless of LLM output.
- All supervisor decisions are logged with the full state snapshot for
  complete audit traceability.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from ecograph.agents.state import EcoState
from ecograph.config import settings
from ecograph.llm import ILLMClient, LLMQuotaExhaustedError, get_groq_client

logger = logging.getLogger(__name__)

# ----------------------------------------------------
# Constants
# ----------------------------------------------------

MAX_AGENT_ITERATIONS = 20

_INTENT_SYSTEM_PROMPT = """
You are the orchestration supervisor for EcoGraph, a multi-agent carbon \
accounting system. Given a user query about supply chain emissions, output \
a JSON object describing the execution plan.

Output ONLY valid JSON. No markdown, no explanation.

Schema:
{
"intent": "hotspot_analysis | mitigation_planning | compliance_check | satellite_verify | full_pipeline | report_only",
"requires_satellite": true | false,
"requires_mitigation": true | false,
"requires_validation": true | false,
"reasoning": "one sentence explaining the classification"
}

Intent definitions:
- hotspot_analysis: identify top emission sources in the supply chain
- mitigation_planning: suggest actions to reduce emissions
- compliance_check: verify regulatory compliance only
- satellite_verify: cross-validate emissions with satellite data
- full_pipeline: complete end-to-end analysis (default for complex queries)
- report_only: generate a report from existing state
"""

# ----------------------------------------------------
# Agent pipeline plans per intent
# ----------------------------------------------------
_PIPELINE_PLANS: dict[str, list[str]] = {
    "hotspot_analysis": ["data_analyst", "reporter"],
    "mitigation_planning": ["data_analyst", "supply_commander", "validator", "reporter"],
    "compliance_check": ["data_analyst", "validator", "reporter"],
    "satellite_verify": ["data_analyst", "satellite_intel", "reporter"],
    "full_pipeline": ["data_analyst", "satellite_intel", "supply_commander", "validator", "reporter"],
    "report_only": ["reporter"],
}

_DEFAULT_PLAN = _PIPELINE_PLANS["full_pipeline"]


# ----------------------------------------------------
# Intent classification
# ----------------------------------------------------
def _classify_intent(query: str, llm: ILLMClient) -> dict:
    """
    Use Groq to classify the user query into a pipeline plan.

    Returns a dict with intent, flags, and reasoning.
    Falls back to full_pipeline if classification fails.
    """
    try:
        response = llm.complete(
            query,
            temperature=0.0,
            max_tokens=256,
            system_prompt=_INTENT_SYSTEM_PROMPT,
        )
        data = json.loads(response.strip())
        if "intent" not in data:
            raise ValueError("Missing 'intent' field in classification response.")
        return data
    except LLMQuotaExhaustedError:
        raise
    except Exception as exc:
        logger.warning(
            "Intent classification failed; defaulting to full_pipeline.",
            extra={"error": str(exc), "query_preview": query[:100]},
        )
        return {
            "intent": "full_pipeline",
            "requires_satellite": True,
            "requires_mitigation": True,
            "requires_validation": True,
            "reasoning": "Classification failed; using safe default.",
        }


# ----------------------------------------------------
# Supervisor node function
# ----------------------------------------------------
def run(state: EcoState) -> EcoState:
    """
    LangGraph node function for the supervisor agent.

    First call:
    - Classifies query intent.
    - Builds pipeline_plan in metadata.
    - Routes to first agent in the plan.

    Subsequent calls:
    - Advances to next agent in the saved plan.
    - Handles validator rejection by re-inserting supply_commander.
    - Terminates when plan is exhausted or MAX_AGENT_ITERATIONS reached.

    Parameters
    ----------
    state: Current pipeline state.

    Returns
    -------
    Updated EcoState with next_agent and iteration_count set.

    Raises
    ------
    RuntimeError: Circuit-breaker triggered (iteration_count > MAX_AGENT_ITERATIONS).
    """
    iteration = state.get("iteration_count", 0)

    if iteration >= MAX_AGENT_ITERATIONS:
        logger.error(
            "Supervisor circuit-breaker: max iterations reached.",
            extra={"iteration": iteration, "query": state.get("query", "")[:100]},
        )
        raise RuntimeError(
            f"Supervisor circuit-breaker: reached {MAX_AGENT_ITERATIONS} iterations "
            "without completing the pipeline. Possible infinite loop."
        )

    llm = get_groq_client()
    query = state.get("query", "")
    metadata: dict = state.get("metadata", {})

    # ----------------------------------------------------
    # First call: classify intent and build pipeline plan
    # ----------------------------------------------------
    if iteration == 0:
        logger.info("Supervisor: classifying intent.", extra={"query_preview": query[:100]})
        intent_result = _classify_intent(query, llm)
        intent = intent_result.get("intent", "full_pipeline")
        plan = _PIPELINE_PLANS.get(intent, _DEFAULT_PLAN)

        metadata.update({
            "intent": intent,
            "intent_reasoning": intent_result.get("reasoning", ""),
            "pipeline_plan": plan,
            "plan_cursor": 0,
            "start_ts": datetime.now(timezone.utc).isoformat(),
            "groq_model": settings.GROQ_MODEL,
        })
        logger.info(
            "Supervisor: intent classified.",
            extra={"intent": intent, "plan": plan},
        )
        next_agent = plan[0] if plan else "END"

    # ----------------------------------------------------
    # Subsequent calls: advance the plan cursor
    # ----------------------------------------------------
    else:
        plan = metadata.get("pipeline_plan", _DEFAULT_PLAN)
        cursor = metadata.get("plan_cursor", 0)

        # Handle validator rejection: re-run supply_commander
        compliance_status = state.get("compliance_status")
        if (
            compliance_status is False
            and metadata.get("validator_rejected_once") is not True
        ):
            logger.info(
                "Supervisor: validator rejected plan; re-routing to supply_commander.",
                extra={"violations": state.get("compliance_violations", [])},
            )
            metadata["validator_rejected_once"] = True
            next_agent = "supply_commander"
        else:
            cursor += 1
            metadata["plan_cursor"] = cursor
            next_agent = plan[cursor] if cursor < len(plan) else "END"

    state_update: EcoState = {
        **state,
        "next_agent": next_agent,
        "iteration_count": iteration + 1,
        "metadata": metadata,
        "messages": state.get("messages", []) + [
            {
                "agent": "supervisor",
                "iteration": iteration + 1,
                "next_agent": next_agent,
            }
        ],
    }

    logger.info(
        "Supervisor: routing decision.",
        extra={
            "iteration": iteration + 1,
            "next_agent": next_agent,
            "plan": metadata.get("pipeline_plan", []),
        },
    )
    return state_update