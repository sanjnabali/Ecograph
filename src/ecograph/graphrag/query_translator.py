"""
src/ecograph/graphrag/query_translator.py

Translates natural-language queries into Cypher statements for Neo4j retrieval.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from ecograph.llm import ILLMClient, LLMQuotaExhaustedError, get_groq_client

logger = logging.getLogger(__name__)

# Constants
DEFAULT_LIMIT = 200
MAX_LIMIT = 500
_WRITE_KEYWORDS = re.compile(
    r"\b(CREATE|MERGE|DELETE|SET|REMOVE|DROP|CALL)\b",
    flags=re.IGNORECASE,
)
_FALLBACK_QUERY = (
    "MATCH (s:Supplier)-[:HAS_OBSERVATION]->(o:Observation) "
    "RETURN s, o ORDER BY o.value DESC LIMIT 100"
)

_SYSTEM_PROMPT = """
You are a Cypher query generator for a Neo4j supply chain carbon accounting \
knowledge graph. Your output must be a single valid Cypher MATCH query followed \
by a RETURN clause. No explanation, no markdown, no multiple queries.

Node labels:
Company, Supplier, Facility, Region, Observation, Evidence,
EmissionTarget, GHGCategory, Regulation, Certification, Scope

Relationship types:
PURCHASES, SUPPLIES, OPERATES, LOCATED_IN, IN_REGION, HAS_OBSERVATION,
SUPPORTED_BY, SETS_TARGET, REPORTS_EMISSION, GOVERNED_BY, CERTIFIED_BY

Key Observation properties:
metric: "co2_flux_tonnes_per_year" | "scope3_tco2e" | "annual_emissions_tco2e"
value: float (tCO2e/year)
method: "self_reported" | "tropomi_cnn" | "spend_based" | "heuristic_capacity_factor"
timestamp: datetime

Rules:
1. Never use CREATE, MERGE, DELETE, SET, REMOVE, or DROP.
2. Always include LIMIT (max 500).
3. Use parameterless queries only (no $params).
4. Use path patterns up to depth 5 for Tier-N traversal.

Examples:
User: Which Tier-2 suppliers have emissions above 50000 tCO2/year?
Cypher: MATCH (c:Company)-[:PURCHASES*2]->(s:Supplier)-[:HAS_OBSERVATION]->(o:Observation) WHERE o.metric = 'co2_flux_tonnes_per_year' AND o.value > 50000 RETURN s.name, s.country, o.value, o.timestamp ORDER BY o.value DESC LIMIT 200

User: Find suppliers in carbon tax regions.
Cypher: MATCH (s:Supplier)-[:LOCATED_IN]->(r:Region) WHERE r.has_carbon_tax = true RETURN s.name, s.entity_id, r.name, r.carbon_tax_rate_usd_tonne LIMIT 200

User: Cross-validate self-reported versus satellite emissions with >20% discrepancy.
Cypher: MATCH (s:Supplier)-[:HAS_OBSERVATION]->(rep:Observation {method: 'self_reported'}) MATCH (s)-[:HAS_OBSERVATION]->(sat:Observation {method: 'tropomi_cnn'}) WHERE abs(rep.value - sat.value) / rep.value > 0.20 RETURN s.name, s.entity_id, rep.value, sat.value LIMIT 200

User: Identify top 10 carbon hotspots across all tiers.
Cypher: MATCH (c:Company)-[:PURCHASES*1..5]->(s:Supplier)-[:HAS_OBSERVATION]->(o:Observation) WHERE o.metric IN ['co2_flux_tonnes_per_year', 'scope3_tco2e'] RETURN s.name, s.entity_id, s.country, sum(o.value) AS total_emissions ORDER BY total_emissions DESC LIMIT 10
"""


def _is_read_only(cypher: str) -> bool:
    """Return False if the Cypher contains any write operations."""
    return not bool(_WRITE_KEYWORDS.search(cypher))


def _ensure_limit(cypher: str, limit: int = DEFAULT_LIMIT) -> str:
    """Append a LIMIT clause if one is not already present."""
    if re.search(r"\bLIMIT\b", cypher, flags=re.IGNORECASE):
        return cypher
    return cypher.rstrip().rstrip(";") + f" LIMIT {limit}"


def _extract_cypher(text: str) -> str:
    """
    Extract clean Cypher from an LLM response.
    """
    # Strip markdown code fences
    text = re.sub(r"^```(?:cypher|sql)?\s*", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"\s*```\s*$", "", text, flags=re.MULTILINE).strip()

    # Take only the first MATCH statement if multiple are returned
    lines = text.split("\n")
    cypher_lines = []
    in_query = False
    for line in lines:
        stripped = line.strip()
        if re.match(r"^MATCH\b", stripped, flags=re.IGNORECASE):
            in_query = True
        if in_query:
            cypher_lines.append(line)
            # Stop at LIMIT clause (end of query)
            if re.search(r"\bLIMIT\s+\d+", stripped, flags=re.IGNORECASE):
                break

    if cypher_lines:
        return " ".join(cypher_lines).strip()

    return text.strip()


def translate_to_cypher(
    query: str,
    llm: Optional[ILLMClient] = None,
    limit: int = DEFAULT_LIMIT,
) -> str:
    """
    Translate a natural-language query to a safe, read-only Cypher statement.
    """
    resolved_llm = llm or get_groq_client()
    effective_limit = min(max(limit, 1), MAX_LIMIT)

    try:
        raw_response = resolved_llm.complete(
            query,
            temperature=0.0,
            max_tokens=512,
            system_prompt=_SYSTEM_PROMPT,
        )
    except LLMQuotaExhaustedError:
        raise
    except Exception as exc:
        logger.warning(
            "Cypher translation LLM call failed; using fallback.",
            extra={"error": str(exc), "query_preview": query[:100]},
        )
        return _ensure_limit(_FALLBACK_QUERY, effective_limit)

    cypher = _extract_cypher(raw_response)

    if not cypher:
        logger.warning("Empty Cypher response; using fallback.")
        return _ensure_limit(_FALLBACK_QUERY, effective_limit)

    if "MATCH" not in cypher.upper() or "RETURN" not in cypher.upper():
        logger.warning(
            "Cypher response missing MATCH or RETURN; using fallback.",
            extra={"raw_preview": cypher[:200]},
        )
        return _ensure_limit(_FALLBACK_QUERY, effective_limit)

    if not _is_read_only(cypher):
        logger.error(
            "Cypher translation produced a write query; rejected for safety.",
            extra={"cypher_preview": cypher[:200]},
        )
        return _ensure_limit(_FALLBACK_QUERY, effective_limit)

    cypher = _ensure_limit(cypher, effective_limit)

    logger.debug(
        "Cypher translation successful.",
        extra={"cypher_preview": cypher[:200]},
    )
    return cypher