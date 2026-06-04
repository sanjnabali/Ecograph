"""
src/ecograph/agents/supply_commander.py

Supply Commander agent: generates trade-off-optimised mitigation plans.

Responsibilities:
- Receive the emissions baseline, hotspot list, and discrepancy flags.
- Query Neo4j for alternative suppliers in lower-emission regions.
- Use Groq to evaluate trade-offs (cost, lead time, carbon reduction).
- Produce a structured mitigation plan with ranked recommendations.
- Populate state fields: supply_mitigation_plan, supply_trade_offs.

Design decisions:
- The mitigation prompt uses chain-of-thought reasoning with explicit
  constraints (budget, lead time, regulatory compliance) so the LLM
  produces actionable, auditable recommendations rather than vague advice.
- Trade-off scoring uses a simple weighted linear model:
  score = 0.5 * carbon_reduction_pct + 0.3 * feasibility + 0.2 * (1 - cost_delta_pct)
  This can be replaced with a Pareto front analysis in future iterations.
- All recommendations include a Neo4j node citation so auditors can verify
  that alternative suppliers actually exist in the graph.
- The agent degrades gracefully when no alternative suppliers are found:
  it recommends process improvements at the existing facility instead.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from ecograph.agents.state import EcoState
from ecograph.config import settings
from ecograph.llm import LLMClient, LLMQuotaExhaustedError, get_groq_client

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Trade-off scoring weights
# -----------------------------------------------------------------------------

_W_CARBON = 0.50
_W_FEASIBILITY = 0.30
_W_COST = 0.20


# -----------------------------------------------------------------------------
# Mitigation planning prompt
# -----------------------------------------------------------------------------

_MITIGATION_SYSTEM_PROMPT = """
You are a Scope 3 carbon mitigation strategist with expertise in global supply
chain decarbonisation, carbon accounting (GHG Protocol), and EU CSRD compliance.

Generate a structured, audit-ready mitigation plan in JSON format only.
No markdown, no explanation outside the JSON.

Output schema:
{
"executive_summary": "2-3 sentence overview",
"recommendations": [
 {
  "rank": 1,
  "action_type": "supplier_switch | process_improvement | logistics_reroute | renewable_energy",
  "target_supplier_id": "string or null",
  "alternative_supplier_id": "string or null",
  "projected_co2_reduction_tco2yr": <number>,
  "projected_cost_delta_usd": <number (negative=savings, positive=cost)>,
  "implementation_timeline_months": <integer>,
  "feasibility_score": <0.0-1.0>,
  "regulatory_alignment": ["CSRD | SB253 | GHG_Protocol"],
  "rationale": "one sentence",
  "cited_node_ids": ["List of Neo4j entity_ids cited"]
 }
],
"total_projected_reduction_tco2yr": <number>,
"implementation_roadmap_months": <integer>
}
"""


# -----------------------------------------------------------------------------
# Trade-off scorer
# -----------------------------------------------------------------------------

def _score_recommendation(rec: dict) -> float:
    """
    Compute a composite score for a mitigation recommendation.
    """
    baseline_reduction = rec.get("projected_co2_reduction_tco2yr", 0.0)
    baseline_max_est = 1_000_000.0  # 1 MtCO2/yr as normalisation ceiling

    carbon_norm = min(max(baseline_reduction / baseline_max_est, 0.0), 1.0)
    feasibility = min(max(float(rec.get("feasibility_score", 0.5)), 0.0), 1.0)

    cost_delta = float(rec.get("projected_cost_delta_usd", 0.0))
    cost_ceiling = 10_000_000.0  # $10M as normalisation ceiling
    cost_penalty = min(max(cost_delta / cost_ceiling, 0.0), 1.0)

    return round(
        _W_CARBON * carbon_norm
        + _W_FEASIBILITY * feasibility
        + _W_COST * (1.0 - cost_penalty),
        4,
    )


# -----------------------------------------------------------------------------
# Alternative supplier lookup
# -----------------------------------------------------------------------------

def _find_alternative_suppliers(hotspot_ids: list[str]) -> list[dict]:
    """
    Query Neo4j for suppliers in lower-emission regions that can supply
    the same commodity categories as the flagged hotspot suppliers.

    Returns a list of candidate alternative supplier dicts.
    Fails silently and returns [] if Neo4j is unavailable.
    """
    if not hotspot_ids:
        return []

    cypher = """
    MATCH (h:Supplier)-[:PURCHASES|SUPPLIES*1..2]->(alt:Supplier)
    WHERE h.entity_id IN $hotspot_ids
    AND alt.entity_id NOT IN $hotspot_ids
    AND alt.carbon_intensity_kgco2_usd IS NOT NULL
    RETURN alt.entity_id AS entity_id,
           alt.name AS name,
           alt.country AS country,
           alt.carbon_intensity_kgco2_usd AS carbon_intensity
    ORDER BY alt.carbon_intensity_kgco2_usd ASC
    LIMIT 20
    """
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
            connection_timeout=settings.NEO4J_TIMEOUT,
        )
        results = []
        with driver.session(database=settings.NEO4J_DATABASE) as session:
            result = session.run(cypher, hotspot_ids=hotspot_ids)
            for record in result:
                results.append(dict(record))
        driver.close()
        return results

    except Exception as exc:
        logger.warning(
            "Alternative supplier lookup failed.",
            extra={"error": str(exc)},
        )
        return []


# -----------------------------------------------------------------------------
# Supply Commander node function
# -----------------------------------------------------------------------------

def run(state: EcoState) -> EcoState:
    """
    LangGraph node function for the Supply Commander agent.

    Steps:
    1. Gather context: baseline, hotspots, discrepancies, alternatives.
    2. Build a rich mitigation context string for the LLM.
    3. Call Groq to generate a structured JSON mitigation plan.
    4. Score and rank each recommendation.
    5. Update state with plan and trade-offs.

    Parameters
    ----------
    state: Current pipeline state.

    Returns
    -------
    Updated EcoState.
    """
    logger.info("SupplyCommander: starting.")

    llm = get_groq_client()
    errors: list[str] = list(state.get("errors", []))

    hotspot_ids = state.get("top_hotspot_ids", [])
    discrepancy_flags = state.get("discrepancy_flags", [])
    baseline = state.get("emissions_baseline", 0.0)
    satellite_data = state.get("satellite_verification", {})
    query = state.get("query", "")

    # -------------------------------------------------------------------------
    # Step 1: Find alternative suppliers
    # -------------------------------------------------------------------------
    alternatives = _find_alternative_suppliers(hotspot_ids)

    # -------------------------------------------------------------------------
    # Step 2: Build mitigation context
    # -------------------------------------------------------------------------
    sat_summary = []
    for sid, data in list(satellite_data.items())[:5]:
        sat_summary.append(
            f" - Supplier {sid}: satellite={data.get('flux_tco2yr', 0):.0f} tCO2/yr, "
            f"reported={data.get('reported_tco2yr') or 'unknown'}, "
            f"discrepancy={'YES' if data.get('is_discrepancy') else 'NO'}"
        )

    alt_summary = [
        f" - {a['name']} ({a['country']}), carbon_intensity={a.get('carbon_intensity', 'N/A')} kgCO2/$"
        for a in alternatives[:5]
    ]

    context = (
        f"User query: {query}\n\n"
        f"Scope 3 emissions baseline: {baseline:.0f} tCO2e/year\n"
        f"Top hotspot supplier IDs: {hotspot_ids[:10]}\n"
        f"Discrepancy-flagged suppliers: {discrepancy_flags}\n\n"
        f"Satellite verification results:\n" + ("\n".join(sat_summary) or " None available") + "\n\n"
        f"Available lower-emission alternative suppliers:\n" + ("\n".join(alt_summary) or " None identified in graph") + "\n\n"
        f"Generate a comprehensive mitigation plan prioritising: "
        f"(1) supplier switching for discrepancy-flagged entities, "
        f"(2) renewable energy procurement for remaining hotspots, "
        f"(3) logistics decarbonisation. "
        f"Ensure all recommendations are compliant with EU CSRD and GHG Protocol."
    )

    # -------------------------------------------------------------------------
    # Step 3: Call Groq
    # -------------------------------------------------------------------------
    try:
        response_text = llm.complete(
            context,
            temperature=0.2,
            max_tokens=1500,
            system_prompt=_MITIGATION_SYSTEM_PROMPT,
        )
    except LLMQuotaExhaustedError as exc:
        msg = f"SupplyCommander: Groq quota exhausted: {exc}"
        errors.append(msg)
        logger.error(msg)
        return {
            **state,
            "supply_mitigation_plan": "Mitigation planning incomplete: LLM quota exhausted.",
            "supply_trade_offs": [],
            "errors": errors,
        }
    except Exception as exc:
        msg = f"SupplyCommander: LLM call failed: {exc}"
        errors.append(msg)
        logger.error(msg)
        response_text = "{}"

    # -------------------------------------------------------------------------
    # Step 4: Parse and score recommendations
    # -------------------------------------------------------------------------
    trade_offs: list[dict] = []
    plan_text: str = ""
    total_reduction: float = 0.0

    try:
        # Strip markdown fences if present
        import re
        clean = re.sub(r"^```(?:json)?\s*", "", response_text.strip(), flags=re.MULTILINE)
        clean = re.sub(r"\s*```\s*$", "", clean, flags=re.MULTILINE).strip()
        plan_data = json.loads(clean)

        plan_text = plan_data.get("executive_summary", "")
        recs = plan_data.get("recommendations", [])
        total_reduction = float(plan_data.get("total_projected_reduction_tco2yr", 0.0))

        for rec in recs:
            score = _score_recommendation(rec)
            trade_offs.append({**rec, "composite_score": score})

        trade_offs.sort(key=lambda x: x.get("composite_score",0.0), reverse=True)

        for i, rec in enumerate(trade_offs, start=1):
            rec["rank"] = i  # Update rank based on scoring
    
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        errors.append(f"SupplyCommander: Failed to parse mitigation plan JSON: {exc}")
        plan_text = response_text[:1000]
        logger.warning(
            "SupplyCommander: could not parse structured plan using raw text.",
            extra={"error": str(exc)},
        )

    if trade_offs:
        rec_lines = []
        for rec in trade_offs[:5]:
            rec_lines.append(
                f"{rec['rank']}. [{rec.get('action_type', 'N/A')}]"
                f"Reduce {rec.get('projected_co2_reduction_tco2yr', 0):.0f} tCO2/yr |"
                f"Score: {rec.get('composite_score', 0):.2f} | "
                f"{rec.get('rationale', '')}"
            )
        plan_text += "\n\nTop recommendations:\n" + "\n".join(rec_lines)
        plan_text += f"\n\nTotal projected reduction: {total_reduction:.0f} tCO2e/year"

    logger.info("SupplyCommander: completed with %d recommendations.", len(trade_offs))

    return {
        **state,
        "supply_mitigation_plan": plan_text,
        "supply_trade_offs": trade_offs,
        "errors": errors,
        "messages": list(state.get("messages", [])) + [
            {
                "agent": "supply_commander",
                "recommendations": len(trade_offs),
                "total_reduction": total_reduction,
                "top_action": trade_offs[0].get("action_type") if trade_offs else None,
            }
        ],
    }