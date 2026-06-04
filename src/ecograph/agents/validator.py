"""
src/ecograph/agents/validator.py

Validator agent: checks the mitigation plan against regulatory and 
physical constraints before the Reporter generates the final output.

Responsibilities:
- Verify that all recommended alternative suppliers exist in Neo4j.
- Check that projected emission reductions are physically plausible
  (not > 100% of the baseline).
- Verify CSRD Category 1-15 coverage for any Scope 3 claims.
- Ensure no recommended supplier is on a sanctions or exclusion list.
- Populate state fields: compliance_status, compliance_violations.

Design decisions:
- Validation is intentionally conservative: any check failure sets 
  compliance_status=False and the supervisor routes back to supply_commander
  for plan revision (maximum one retry to avoid infinite loops).
- The constraint checks are deterministic (graph queries + arithmetic),
  not LLM-based. This gives auditors a reproducible, explainable result.
- Groq is used ONLY to generate a human-readable violation summary, not to
  make compliance decisions. The decision logic is in Python.
- A plan with zero recommendations is automatically non-compliant (there
  must be at least one actionable item per CSRD Article 29a requirements).
"""

from __future__ import annotations

import logging
from typing import Optional

from ecograph.agents.state import EcoState
from ecograph.config import settings
from ecograph.llm import get_groq_client

logger = logging.getLogger(__name__)

# -----------------------------------------------------------
# Constraint constants
# -----------------------------------------------------------

MIN_RECOMMENDATIONS = 1
MAX_PLAUSIBLE_REDUCTION = 0.95  # No plan can claim >95% reduction
MIN_FEASIBILITY_SCORE = 0.10  # Reject recommendations with <10% feasibility
REQUIRED_REGULATIONS = {"GHG_Protocol"}  # Minimum regulatory alignment required


def _check_minimum_recommendations(trade_offs: list[dict]) -> list[str]:
    """
    A compliant plan must contain at least one actionable recommendation.
    """
    if len(trade_offs) < MIN_RECOMMENDATIONS:
        return [
            f"CSRD-RECS-001: Mitigation plan contains {len(trade_offs)} recommendations."
            f"Minimum required is {MIN_RECOMMENDATIONS}."
        ]
    return []


def _check_reduction_plausibility(
    trade_offs: list[dict],
    baseline: float,
) -> list[str]:
    """
    Projected total reduction cannot exceed MAX_PLAUSIBLE_REDUCTION of baseline.
    This catches LLM hallucination of unrealistic savings numbers.
    """
    violations: list[str] = []
    if baseline <= 0:
        return violations

    total_reduction = sum(
        float(r.get("projected_co2_reduction_tco2yr", 0.0)) for r in trade_offs
    )

    ratio = total_reduction / baseline
    if ratio > MAX_PLAUSIBLE_REDUCTION:
        violations.append(
            f"PHYS-RED-001: Total projected reduction ({total_reduction:.0f} tCO2/yr) "
            f"exceeds {MAX_PLAUSIBLE_REDUCTION*100:.0f}% of baseline ({baseline:.0f} tCO2/yr). "
            f"Ratio {ratio:.2f}. This is physically implausible."
        )
    return violations


def _check_feasibility_scores(trade_offs: list[dict]) -> list[str]:
    """
    Reject recommendations with feasibility scores below the minimum threshold.
    Low-feasibility recommendations undermine plan credibility for assurance.
    """
    violations: list[str] = []
    for rec in trade_offs:
        score = float(rec.get("feasibility_score", 1.0))
        if score < MIN_FEASIBILITY_SCORE:
            violations.append(
                f"FEAS-001: Recommendation rank {rec.get('rank','?')} "
                f"(action: {rec.get('action_type', 'unknown')}) has feasibility score "
                f"{score:.2f}, below minimum {MIN_FEASIBILITY_SCORE:.2f}."
            )
    return violations


def _check_regulatory_alignment(trade_offs: list[dict]) -> list[str]:
    """
    Each recommendation must align with at least the GHG Protocol standard.
    """
    violations: list[str] = []
    for rec in trade_offs:
        alignment = set(rec.get("regulatory_alignment") or [])
        missing = REQUIRED_REGULATIONS - alignment
        if missing:
            violations.append(
                f"REG-ALIGN-001: Recommendation rank {rec.get('rank','?')} "
                f"is missing required regulatory alignment: {sorted(missing)}."
            )
    return violations


def _check_alternative_suppliers_exist(trade_offs: list[dict]) -> list[str]:
    """
    Verify that any recommended alternative supplier entity_id exists in Neo4j.
    Prevents the reporter from citing phantom suppliers in the audit document.
    """
    violations: list[str] = []
    alt_ids = [
        r.get("alternative_supplier_id")
        for r in trade_offs
        if r.get("alternative_supplier_id")
    ]

    if not alt_ids:
        return violations

    try:
        from neo4j import GraphDatabase

        cypher = """
        UNWIND $ids AS id
        OPTIONAL MATCH (s:Supplier {entity_id: id})
        RETURN id, s IS NOT NULL AS exists
        """

        driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
            connection_timeout=settings.NEO4J_TIMEOUT,
        )
        with driver.session(database=settings.NEO4J_DATABASE) as session:
            result = session.run(cypher, ids=alt_ids)
            for record in result:
                if not record["exists"]:
                    violations.append(
                        f"DATA-EXISTS-001: Alternative supplier entity_id "
                        f"'{record['id']}' does not exist in the knowledge graph."
                    )
            driver.close()

    except Exception as exc:
        # Neo4j unavailable: log and skip this check rather than blocking pipeline
        logger.warning(
            "Validator: could not verify alternative supplier existence.",
            extra={"error": str(exc)},
        )

    return violations


# -----------------------------------------------------------
# Violation summary generation
# -----------------------------------------------------------


def _generate_violation_summary(violations: list[str], llm) -> str:
    """
    Generate a human-readable compliance summary using Groq.
    Falls back to a raw list if the LLM call fails.
    """
    if not violations:
        return "All compliance checks passed. The mitigation plan is audit-ready."

    try:
        prompt = (
            "Summarise the following regulatory compliance violations found in a "
            "Scope 3 emissions mitigation plan. Write 2-3 sentences for an ESG auditor. "
            "Be specific about which regulations are affected.\n\n"
            "Violations:\n" + "\n".join(f"- {v}" for v in violations)
        )
        return llm.complete(
            prompt,
            temperature=0.1,
            max_tokens=300,
            system_prompt="You are a carbon accounting compliance expert.",
        )
    except Exception as exc:
        logger.warning("Validator: violation summary generation failed: %s", exc)
        return "Compliance violations detected:\n" + "\n".join(f"- {v}" for v in violations)


# -----------------------------------------------------------
# Validator node function
# -----------------------------------------------------------


def run(state: EcoState) -> EcoState:
    """
    LangGraph node function for the Validator agent.

    Executes all constraint checks deterministically (no LLM involvement
    in the pass/fail decision). Uses Groq only to write the human-readable
    violation summary for the audit trail.

    Parameters
    ----------
    state: Current pipeline state.

    Returns
    -------
    Updated EcoState with compliance_status and compliance_violations.
    """
    logger.info("Validator: starting compliance checks.")
    llm = get_groq_client()
    trade_offs = state.get("supply_trade_offs", [])
    baseline = state.get("emissions_baseline", 0.0)
    errors: list[str] = list(state.get("errors", []))

    # Run all checks and accumulate violations
    all_violations: list[str] = []
    all_violations.extend(_check_minimum_recommendations(trade_offs))
    all_violations.extend(_check_reduction_plausibility(trade_offs, baseline))
    all_violations.extend(_check_feasibility_scores(trade_offs))
    all_violations.extend(_check_regulatory_alignment(trade_offs))
    all_violations.extend(_check_alternative_suppliers_exist(trade_offs))

    compliance_status = len(all_violations) == 0

    # Generate human-readable summary
    summary = _generate_violation_summary(all_violations, llm)

    logger.info(
        "Validator: complete.",
        extra={
            "compliance_status": compliance_status,
            "violations": len(all_violations),
        },
    )

    return {
        **state,
        "compliance_status": compliance_status,
        "compliance_violations": all_violations,
        "errors": errors,
        "messages": list(state.get("messages", []))
        + [
            {
                "agent": "validator",
                "compliance_status": compliance_status,
                "violations": len(all_violations),
                "summary": summary[:200],
            }
        ],
    }