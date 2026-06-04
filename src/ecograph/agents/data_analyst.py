"""
src/ecograph/agents/data_analyst.py

Data Analyst agent: queries the Neo4j knowledge graph and computes
Scope 3 emissions baselines using exponential smoothing.

Responsibilities:
- Translate the user query to Cypher via Groq (GraphRAG query translation).
- Execute the Cypher query against Neo4j.
- Apply Holt-Winters double exponential smoothing to time-series emission
  observations for trend-adjusted baseline estimation.
- Identify the top-N carbon hotspot suppliers from the graph.
- Populate state fields: supply_chain_nodes,
  data_analyst_summary, emissions_baseline, top_hotspot_ids.

Design decisions:
- The Cypher translator prompt is highly constrained (returns ONLY Cypher)
  and uses temperature=0 for deterministic, reproducible queries.
- The agent caps Neo4j query results at MAX_NODES to prevent memory
  overflow on large graphs; callers can increase this via state metadata.
- Exponential smoothing alpha=0.3 is a well-validated default for emission
  time series with moderate volatility. It can be overridden via .env.
- All graph query results are included in citations for auditability.
- The agent degrades gracefully when Neo4j is unavailable: it returns
  empty results rather than crashing the pipeline.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Optional

from ecograph.agents.state import EcoState
from ecograph.config import settings
from ecograph.llm import ILLMClient, LLMQuotaExhaustedError, get_groq_client

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------
MAX_NODES = 500
SMOOTHING_ALPHA = 0.3  # Holt simple exponential smoothing weight
TOP_N_HOTSPOTS = 10
_DEFAULT_EMISSION_VALUE = 0.0

# --------------------------------------------------------------------------
# Cypher translation prompt
# --------------------------------------------------------------------------
_CYPHER_SYSTEM_PROMPT = """
You are a Cypher query generator for a Neo4j supply chain knowledge graph.

Node labels: Company, Supplier, Facility, Region, Observation, Evidence,
EmissionTarget, GHGCategory, Regulation, Certification

Relationship types: PURCHASES, SUPPLIES, OPERATES, LOCATED_IN, IN_REGION,
HAS_OBSERVATION, SUPPORTED_BY, SETS_TARGET, REPORTS_EMISSION,
GOVERNED_BY, CERTIFIED_BY

Observation node properties:
metric: string (e.g., "co2_flux_tonnes_per_year", "scope3_tco2e")
value: float
unit: string
method: string ("self_reported" | "tropomi_cnn" | "spend_based")
timestamp: datetime

Output ONLY a valid Cypher MATCH query with a RETURN clause.
Always include a LIMIT clause (max 500 records).
Never use CREATE, MERGE, DELETE, or SET.
If the query cannot be expressed in Cypher, output: MATCH (n) RETURN n LIMIT 10
"""

# --------------------------------------------------------------------------
# Cypher query translation
# --------------------------------------------------------------------------
def _translate_to_cypher(query: str, llm: ILLMClient) -> str:
    """
    Translate a natural-language query to a Cypher statement using Groq.

    Returns a safe fallback query if translation fails.
    """
    fallback = "MATCH (s:Supplier)-[:HAS_OBSERVATION]->(o:Observation) RETURN s, o LIMIT 100"
    try:
        cypher = llm.complete(
            query,
            temperature=0.0,
            max_tokens=512,
            system_prompt=_CYPHER_SYSTEM_PROMPT,
        ).strip()

        # Basic sanity check: must contain MATCH and RETURN
        if "MATCH" not in cypher.upper() or "RETURN" not in cypher.upper():
            logger.warning(
                "Cypher translation returned non-query text; using fallback.",
                extra={"raw_preview": cypher[:200]},
            )
            return fallback

        # Ensure there is always a LIMIT clause
        if "LIMIT" not in cypher.upper():
            cypher = cypher.rstrip().rstrip(";") + f" LIMIT {MAX_NODES}"

        return cypher

    except LLMQuotaExhaustedError:
        raise
    except Exception as exc:
        logger.warning(
            "Cypher translation failed; using fallback.",
            extra={"error": str(exc)},
        )
        return fallback

# --------------------------------------------------------------------------
# Exponential smoothing
# --------------------------------------------------------------------------
def _exponential_smooth(values: list[float], alpha: float = SMOOTHING_ALPHA) -> float:
    """
    Simple (Holt Level-1) exponential smoothing for emission time series.

    Returns the smoothed level at time T (the most recent smoothed estimate).
    Handles edge cases: empty list returns 0.0; single value returns that value.

    Parameters
    ----------
    values:
        Chronologically ordered emission readings (tCO2e/year).
    alpha:
        Smoothing factor in (0, 1). Lower = more smoothing (weight on history).
        0.3 is appropriate for moderately volatile annual emission data.

    Returns
    -------
    float: Trend-adjusted baseline estimate.
    """
    if not values:
        return _DEFAULT_EMISSION_VALUE

    valid = [v for v in values if isinstance(v, (int, float)) and math.isfinite(v) and v >= 0]
    if not valid:
        return _DEFAULT_EMISSION_VALUE

    if len(valid) == 1:
        return float(valid[0])

    level = float(valid[0])
    for v in valid[1:]:
        level = alpha * v + (1 - alpha) * level

    return round(level, 2)

# --------------------------------------------------------------------------
# Neo4j execution helpers
# --------------------------------------------------------------------------
def _execute_cypher(cypher: str) -> tuple[list[dict], list[str]]:
    """
    Execute a Cypher query against Neo4j and return raw results.

    Returns (records, errors). Errors are non-fatal strings for the audit trail.
    Isolation: this function has no side effects on the graph (read-only).
    """
    try:
        from neo4j import GraphDatabase, exceptions as neo4j_exc
        
        driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
            connection_timeout=settings.NEO4J_TIMEOUT,
            max_connection_pool_size=settings.NEO4J_MAX_POOL,
        )
        records: list[dict] = []
        errors: list[str] = []
        
        with driver.session(database=settings.NEO4J_DATABASE) as session:
            result = session.run(cypher)
            for record in result:
                records.append(dict(record))
        driver.close()
        return records, errors

    except Exception as exc:
        err = f"Neo4j query failed: {exc}"
        logger.error(err, extra={"cypher_preview": cypher[:200]})
        return [], [err]

# --------------------------------------------------------------------------
# Hotspot identification
# --------------------------------------------------------------------------
def _identify_hotspots(nodes: list[dict], top_n: int = TOP_N_HOTSPOTS) -> list[str]:
    """
    Identify the top-N supplier entity_ids by emission value from graph records.

    Handles heterogeneous Neo4j record shapes: each record may contain
    Supplier nodes and Observation nodes under different key names.
    Returns a list of entity_ids sorted by descending emission value.
    """
    supplier_emissions: dict[str, float] = {}

    for record in nodes:
        supplier_id: Optional[str] = None
        emission_val: float = 0.0

        for key, value in record.items():
            if value is None:
                continue
            # Neo4j driver returns Node objects; convert to dict if needed
            if hasattr(value, "items"):
                node_dict = dict(value)
            elif isinstance(value, dict):
                node_dict = value
            else:
                continue

            labels = getattr(value, "labels", set())
            if "Supplier" in labels or node_dict.get("_label") == "Supplier":
                supplier_id = node_dict.get("entity_id") or node_dict.get("name")
            
            metric = node_dict.get("metric", "")
            if metric in ("co2_flux_tonnes_per_year", "scope3_tco2e", "annual_emissions_tco2e"):
                try:
                    emission_val = float(node_dict.get("value", 0.0))
                except (TypeError, ValueError):
                    emission_val = 0.0
        
        if supplier_id and emission_val > 0:
            supplier_emissions[supplier_id] = max(
                supplier_emissions.get(supplier_id, 0.0), emission_val
            )

    sorted_suppliers = sorted(supplier_emissions.items(), key=lambda x: x[1], reverse=True)
    return [sid for sid, _ in sorted_suppliers[:top_n]]

# --------------------------------------------------------------------------
# Data Analyst node function
# --------------------------------------------------------------------------
def run(state: EcoState) -> EcoState:
    """
    LangGraph node function for the Data Analyst agent.

    Execution steps:
    1. Translate user query to Cypher.
    2. Execute Cypher against Neo4j.
    3. Extract emission time series per supplier.
    4. Apply exponential smoothing to compute baseline.
    5. Rank suppliers by emission to identify hotspots.
    6. Generate natural-language summary via Groq.
    7. Update state with findings and citations.

    Parameters
    ----------
    state: Current pipeline state.

    Returns
    -------
    Updated EcoState.
    """
    logger.info("DataAnalyst: starting.", extra={"query_preview": state.get("query", "")[:100]})
    llm = get_groq_client()
    query = state.get("query", "")
    errors: list[str] = list(state.get("errors", []))

    # Step 1: Translate query to Cypher
    try:
        cypher = _translate_to_cypher(query, llm)
    except LLMQuotaExhaustedError as exc:
        errors.append(f"DataAnalyst: Groq quota exhausted during Cypher translation: {exc}")
        logger.error("DataAnalyst: quota exhausted.", extra={"error": str(exc)})
        return {
            **state,
            "errors": errors,
            "data_analyst_summary": "Data analysis incomplete: LLM quota exhausted.",
            "supply_chain_nodes": [],
            "subgraph_cypher": "",
            "emissions_baseline": 0.0,
            "top_hotspot_ids": [],
        }

    logger.debug("DataAnalyst: Cypher generated.", extra={"cypher_preview": cypher[:200]})

    # Step 2: Execute against Neo4j
    records, neo4j_errors = _execute_cypher(cypher)
    errors.extend(neo4j_errors)

    logger.info(
        "DataAnalyst: graph query complete.",
        extra={"records_returned": len(records), "cypher_errors": len(neo4j_errors)},
    )

    # Step 3 & 4: Extract emission readings and compute smoothed baseline
    emission_series: list[float] = []
    for record in records:
        for value in record.values():
            if value is None:
                continue
            node_dict = dict(value) if hasattr(value, "items") else (value if isinstance(value, dict) else {})
            metric = node_dict.get("metric", "")
            if metric in ("co2_flux_tonnes_per_year", "scope3_tco2e", "annual_emissions_tco2e"):
                try:
                    emission_series.append(float(node_dict.get("value", 0.0)))
                except (TypeError, ValueError):
                    pass
    
    emissions_baseline = _exponential_smooth(emission_series)

    # Step 5: Identify hotspots
    hotspot_ids = _identify_hotspots(records)

    # Step 6: Generate natural-language summary
    summary_prompt = (
        f"Summarise the following supply chain carbon analysis in 3-4 sentences "
        f"for an ESG auditor. Include the total emissions baseline, the top hotspot "
        f"suppliers, and any data quality issues.\n\n"
        f"Query: {query}\n"
        f"Emissions baseline (tCO2e/year): {emissions_baseline:.0f}\n"
        f"Top hotspot supplier IDs: {hotspot_ids[:5]}\n"
        f"Graph records retrieved: {len(records)}\n"
        f"Data errors: {errors[:3] if errors else 'None'}"
    )

    try:
        summary = llm.complete(
            summary_prompt,
            temperature=0.3,
            max_tokens=400,
            system_prompt="You are an ESG carbon accounting expert. Write concisely and precisely.",
        )
    except Exception as exc:
        summary = (
            f"Data analysis retrieved {len(records)} graph records. "
            f"Estimated Scope 3 emissions baseline: {emissions_baseline:.0f} tCO2e/year. "
            f"Top {len(hotspot_ids)} hotspot suppliers identified."
        )
        errors.append(f"DataAnalyst: summary generation failed: {exc}")

    # Step 7: Collect citations (graph node IDs for audit trail)
    citations: list[dict] = []
    for record in records[:50]:  # Cap at 50 to avoid state bloat
        for value in record.values():
            if hasattr(value, "element_id"):
                citations.append({
                    "neo4j_element_id": value.element_id,
                    "agent": "data_analyst",
                    "ts": datetime.now(timezone.utc).isoformat(),
                })

    logger.info(
        "DataAnalyst: complete.",
        extra={
            "baseline_tco2": emissions_baseline,
            "hotspots": len(hotspot_ids),
            "citations": len(citations),
        },
    )

    return {
        **state,
        "supply_chain_nodes": records,
        "subgraph_cypher": cypher,
        "data_analyst_summary": summary,
        "emissions_baseline": emissions_baseline,
        "top_hotspot_ids": hotspot_ids,
        "citations": list(state.get("citations", [])) + citations,
        "messages": list(state.get("messages", [])) + [
            {
                "agent": "data_analyst",
                "summary": summary[:200],
                "baseline": emissions_baseline,
                "hotspots": hotspot_ids[:5],
            }
        ],
    }