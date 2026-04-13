"""
api/routers/stats.py - Dashboard statistics endpoints.

GET /api/stats/summary      - node/rel counts + emission totals
GET /api/stats/emissions    - emissions grouped by company
GET /api/stats/categories   - Scope 3 category breakdown
GET /api/stats/targets      - net-zero targets per company
GET /api/stats/health       - DB connectivity probe (used by frontend heartbeat)
"""

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from neo4j import Driver
from pydantic import BaseModel, Field

from api.deps import get_driver

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/stats", tags=["Statistics"])

class GraphSummary(BaseModel):
    total_nodes:         int
    total_relationships: int
    companies:           int
    emission_metrics:    int
    regions:             int
    facilities:          int
    suppliers:           int   # Company nodes with supply_chain_tier set

class EmissionRow(BaseModel):
    company: str
    value:   float
    unit:    str = "tCO2e"
    year:    str = Field(default="unknown")
    scope:   str = Field(default="unknown")

class CategoryRow(BaseModel):
    category: str
    count:    int

class TargetRow(BaseModel):
    company:     str
    target_year: str
    description: str = ""

class HealthStatus(BaseModel):
    status:  str  # "ok" | "degraded"
    neo4j:   bool
    message: str  = ""

@router.get(
    "/health",
    response_model=HealthStatus,
    summary="Database health check",
    description="Returns 200 if Neo4j is reachable. Used by the frontend heartbeat.",
)
def health_check(driver: Driver = Depends(get_driver)) -> HealthStatus:
    # Deps.get_driver already verified connectivity - if we reach here it's healthy
    return HealthStatus(status="ok", neo4j=True)

@router.get(
    "/summary",
    response_model=GraphSummary,
    summary="Graph node and relationship totals",
)
def get_summary(driver: Driver = Depends(get_driver)) -> GraphSummary:
    """
    Returns counts of all node types and total relationships.
    All counts default to 0 if no data exists yet.
    """
    cypher = """
        MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt
    """
    rel_cypher = "MATCH ()-[r]->() RETURN count(r) AS total"
    
    supplier_cypher = """
        MATCH (c:Company) WHERE c.supply_chain_tier IS NOT NULL RETURN count(c) AS cnt
    """

    counts: Dict[str, int] = {}
    with driver.session() as session:
        for record in session.run(cypher):
            if record["label"]:
                counts[record["label"]] = record["cnt"]
        rel_result = session.run(rel_cypher).single()
        total_rels = rel_result["total"] if rel_result else 0
        sup_result = session.run(supplier_cypher).single()
        supplier_count = sup_result["cnt"] if sup_result else 0

    return GraphSummary(
        total_nodes         = sum(counts.values()),
        total_relationships = total_rels,
        companies           = counts.get("Company", 0),
        emission_metrics    = counts.get("EmissionMetric", 0),
        regions             = counts.get("Region", 0),
        facilities          = counts.get("Facility", 0),
        suppliers           = supplier_count,
    )

@router.get(
    "/emissions",
    response_model=List[EmissionRow],
    summary="Emissions by company",
    description=(
        "Returns all Company->EmissionMetric relationships with optional "
        "year and scope context. Sorted by value descending."
    ),
)
def get_emissions(
    limit: int = 50,
    driver: Driver = Depends(get_driver),
) -> List[EmissionRow]:
    """
    Query param:
      limit (int, default 50, max 500) - cap on returned rows
    """
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500.")

    cypher = """
        MATCH (c:Company)-[:REPORTS_EMISSION]->(e:EmissionMetric)
        OPTIONAL MATCH (e)-[:MEASURED_IN_YEAR]->(y:Year)
        OPTIONAL MATCH (e)-[:FALLS_UNDER_SCOPE]->(s:Scope)
        RETURN
            c.name      AS company,
            e.value     AS value,
            COALESCE(e.unit, 'tCO2e') AS unit,
            COALESCE(y.value, 'unknown') AS year,
            COALESCE(s.name, 'unknown')  AS scope
        ORDER BY
            CASE WHEN e.value IS NOT NULL THEN toFloat(e.value) ELSE 0 END DESC
        LIMIT $limit
    """
    
    rows: List[EmissionRow] = []
    with driver.session() as session:
        for r in session.run(cypher, limit=limit):
            try:
                rows.append(EmissionRow(
                    company = r["company"] or "Unknown",
                    value   = float(r["value"] or 0),
                    unit    = r["unit"],
                    year    = str(r["year"]),
                    scope   = str(r["scope"]),
                ))
            except (TypeError, ValueError) as exc:
                logger.warning(f"Skipping malformed emission record: {r.data()} - {exc}")

    return rows

@router.get(
    "/categories",
    response_model=List[CategoryRow],
    summary="Scope 3 category breakdown",
)
def get_categories(driver: Driver = Depends(get_driver)) -> List[CategoryRow]:
    cypher = """
        MATCH (e:EmissionMetric)-[:BELONGS_TO_CATEGORY]->(cat:Category)
        RETURN cat.name AS category, count(e) AS count
        ORDER BY count DESC
    """
    rows: List[CategoryRow] = []
    with driver.session() as session:
        for r in session.run(cypher):
            if r["category"]:
                rows.append(CategoryRow(category=r["category"], count=r["count"]))
    return rows

@router.get(
    "/targets",
    response_model=List[TargetRow],
    summary="Net-zero targets per company",
)
def get_targets(driver: Driver = Depends(get_driver)) -> List[TargetRow]:
    cypher = """
        MATCH (c:Company)-[:COMMITS_TO_NET_ZERO]->(y:Year)
        RETURN c.name AS company, y.value AS target_year, '' AS description
        UNION
        MATCH (c:Company)-[:SETS_TARGET]->(t:Target)
        RETURN c.name AS company, COALESCE(t.year, 'unknown') AS target_year,
               COALESCE(t.description, '') AS description
        ORDER BY target_year ASC
    """
    
    rows: List[TargetRow] = []
    with driver.session() as session:
        for r in session.run(cypher):
            if r["company"]:
                rows.append(TargetRow(
                    company     = r["company"],
                    target_year = str(r["target_year"] or "unknown"),
                    description = r["description"] or "",
                ))
    return rows