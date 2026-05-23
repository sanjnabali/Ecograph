"""
src/ecograph/graph/schema.py

Neo4j graph schema definition for EcoGraph.

This module is the single authoritative definition of the knowledge graph
ontology. Every node label, relationship type, constraint, index, and
property name used anywhere in the codebase must trace back to a constant
defined here.

Design decisions:
- NodeLabel and RelationshipType are plain string constants (not Enum subclasses)
  so they can be interpolated directly into f-strings for Cypher queries without
  calling .value. Using string-backed Enum would require .value everywhere or
  a custom __str__, both adding ceremony for no benefit.
- SCHEMA_DDL is split into individual statements (list[str]) rather than one
  semicolon-delimited string. This makes it safe to iterate and execute each
  statement independently, catching per-statement errors without aborting the
  entire schema application.
- Property schemas (NODE_PROPERTIES) serve as documentation and as the
  authoritative type contract. They are used by graph_builder.py to validate
  and coerce values before writing to Neo4j.
- apply_schema() is idempotent — re-running it on an existing graph is safe.
  All DDL statements use IF NOT EXISTS.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Node labels
# ---------------------------------------------------------------------------

class NodeLabel:
    # Supply chain entities
    COMPANY    = "Company"
    SUPPLIER   = "Supplier"
    FACILITY   = "Facility"
    REGION     = "Region"

    # Emission accounting
    EMISSION_METRIC = "EmissionMetric"
    GHG_CATEGORY    = "GHGCategory"
    SCOPE           = "Scope"
    YEAR            = "Year"

    # Observations and evidence (audit trail)
    OBSERVATION = "Observation"
    EVIDENCE    = "Evidence"

    # Policy, targets, certifications
    TARGET        = "Target"
    REGULATION    = "Regulation"
    CERTIFICATION = "Certification"

    # All labels as a frozenset — used for label validation in API layer
    ALL: frozenset = frozenset({
        "Company", "Supplier", "Facility", "Region",
        "EmissionMetric", "GHGCategory", "Scope", "Year",
        "Observation", "Evidence",
        "Target", "Regulation", "Certification",
    })


# ---------------------------------------------------------------------------
# Relationship types
# ---------------------------------------------------------------------------

class RelationshipType:
    # Supply chain topology
    HAS_SUPPLIER  = "HAS_SUPPLIER"
    SUPPLIES_TO   = "SUPPLIES_TO"
    OPERATES      = "OPERATES"
    LOCATED_IN    = "LOCATED_IN"
    IN_REGION     = "IN_REGION"
    OWNED_BY      = "OWNED_BY"

    # Emission accounting
    REPORTS_EMISSION     = "REPORTS_EMISSION"
    FALLS_UNDER_SCOPE    = "FALLS_UNDER_SCOPE"
    MEASURED_IN_YEAR     = "MEASURED_IN_YEAR"
    BELONGS_TO_CATEGORY  = "BELONGS_TO_CATEGORY"
    GENERATES_EMISSION   = "GENERATES_EMISSION"

    # Observation layer (event sourcing — append-only audit trail)
    HAS_OBSERVATION = "HAS_OBSERVATION"
    SUPPORTED_BY    = "SUPPORTED_BY"
    VERIFIES        = "VERIFIES"
    CITES           = "CITES"

    # Policy and commitments
    COMMITS_TO_NET_ZERO = "COMMITS_TO_NET_ZERO"
    SETS_TARGET         = "SETS_TARGET"
    GOVERNED_BY         = "GOVERNED_BY"
    CERTIFIED_BY        = "CERTIFIED_BY"
    REQUIRES            = "REQUIRES"


# ---------------------------------------------------------------------------
# Property schemas
# Each entry maps a label to a dict of {property_name: python_type}.
# Used by GraphBuilder to validate and coerce values before writing.
# ---------------------------------------------------------------------------

NODE_PROPERTIES: dict[str, dict[str, type]] = {
    NodeLabel.COMPANY: {
        "entity_id":  str,
        "name":       str,
        "country":    str,
        "sector":     str,
        "tax_id":     str,    # optional
        "website":    str,    # optional
    },
    NodeLabel.SUPPLIER: {
        "entity_id":          str,
        "name":               str,
        "country":            str,
        "sector":             str,
        "supply_chain_tier":  int,   # 1=direct, 2=Tier-2, etc.
        "latitude":           float, # optional
        "longitude":          float, # optional
        "primary_fuel":       str,   # optional — for power plants
        "capacity_mw":        float, # optional — for power plants
        "os_id":              str,   # Open Supply Hub ID, optional
        "gppd_id":            str,   # WRI Power Plant ID, optional
    },
    NodeLabel.FACILITY: {
        "entity_id":     str,
        "name":          str,
        "facility_type": str,    # "factory", "warehouse", "power_plant"
        "latitude":      float,
        "longitude":     float,
        "country":       str,
        "capacity_mw":   float,  # optional
        "primary_fuel":  str,    # optional
    },
    NodeLabel.REGION: {
        "name":                      str,
        "country":                   str,   # optional
        "carbon_tax":                bool,
        "carbon_price_usd_per_tonne": float, # optional
        "latitude":                  float,  # optional — centroid
        "longitude":                 float,  # optional — centroid
    },
    NodeLabel.EMISSION_METRIC: {
        "value":    float,
        "unit":     str,   # "tCO2e", "MtCO2e", "kgCO2e"
        "scope":    int,   # 1, 2, or 3
        "category": str,   # optional — Scope 3 category name
        "year":     int,   # reporting year
        "method":   str,   # "self_reported", "spend_based", "tropomi_cnn"
    },
    NodeLabel.OBSERVATION: {
        "observation_id": str,   # UUID — unique constraint
        "timestamp":      str,   # ISO-8601 UTC
        "metric":         str,   # "co2_flux_tonnes_per_year", etc.
        "value":          float,
        "unit":           str,
        "method":         str,   # "self_reported", "tropomi_cnn", "spend_based"
        "confidence":     float, # 0.0 to 1.0
    },
    NodeLabel.TARGET: {
        "target_id":   str,
        "target_year": int,
        "description": str,
        "scope":       str,   # "1,2,3" or "all"
        "reduction_pct": float, # optional — % reduction target
    },
}

RELATIONSHIP_PROPERTIES: dict[str, dict[str, type]] = {
    RelationshipType.HAS_SUPPLIER: {
        "since":             str,   # ISO date
        "annual_spend_usd":  float,
        "tier":              int,
        "commodity":         str,
        "provenance_source": str,
    },
    RelationshipType.REPORTS_EMISSION: {
        "year":              int,
        "scope":             int,
        "provenance_source": str,
        "provenance_file":   str,
    },
    RelationshipType.HAS_OBSERVATION: {
        "method":    str,
        "timestamp": str,
    },
    RelationshipType.SUPPORTED_BY: {
        "source_type": str,   # "esg_pdf", "erp_invoice", "satellite"
        "confidence":  float,
        "file":        str,
        "chunk_index": int,
    },
}


# ---------------------------------------------------------------------------
# Schema DDL — each string is one executable Cypher statement
# All use IF NOT EXISTS so the function is idempotent.
# ---------------------------------------------------------------------------

_CONSTRAINTS: list[str] = [
    # Uniqueness constraints (also create an index automatically in Neo4j 4+)
    "CREATE CONSTRAINT unique_company_entity_id IF NOT EXISTS "
    "FOR (n:Company) REQUIRE n.entity_id IS UNIQUE",

    "CREATE CONSTRAINT unique_supplier_entity_id IF NOT EXISTS "
    "FOR (n:Supplier) REQUIRE n.entity_id IS UNIQUE",

    "CREATE CONSTRAINT unique_facility_entity_id IF NOT EXISTS "
    "FOR (n:Facility) REQUIRE n.entity_id IS UNIQUE",

    "CREATE CONSTRAINT unique_region_name IF NOT EXISTS "
    "FOR (n:Region) REQUIRE n.name IS UNIQUE",

    "CREATE CONSTRAINT unique_scope_name IF NOT EXISTS "
    "FOR (n:Scope) REQUIRE n.name IS UNIQUE",

    "CREATE CONSTRAINT unique_ghg_category_name IF NOT EXISTS "
    "FOR (n:GHGCategory) REQUIRE n.name IS UNIQUE",

    "CREATE CONSTRAINT unique_observation_id IF NOT EXISTS "
    "FOR (n:Observation) REQUIRE n.observation_id IS UNIQUE",

    "CREATE CONSTRAINT unique_year_value IF NOT EXISTS "
    "FOR (n:Year) REQUIRE n.value IS UNIQUE",
]

_INDEXES: list[str] = [
    "CREATE INDEX idx_company_name IF NOT EXISTS "
    "FOR (n:Company) ON (n.name)",

    "CREATE INDEX idx_supplier_name IF NOT EXISTS "
    "FOR (n:Supplier) ON (n.name)",

    "CREATE INDEX idx_supplier_country IF NOT EXISTS "
    "FOR (n:Supplier) ON (n.country)",

    "CREATE INDEX idx_supplier_tier IF NOT EXISTS "
    "FOR (n:Supplier) ON (n.supply_chain_tier)",

    "CREATE INDEX idx_facility_coords IF NOT EXISTS "
    "FOR (n:Facility) ON (n.latitude, n.longitude)",

    "CREATE INDEX idx_emission_metric_value IF NOT EXISTS "
    "FOR (n:EmissionMetric) ON (n.value)",

    "CREATE INDEX idx_observation_timestamp IF NOT EXISTS "
    "FOR (n:Observation) ON (n.timestamp)",

    "CREATE INDEX idx_observation_method IF NOT EXISTS "
    "FOR (n:Observation) ON (n.method)",
]

_FULLTEXT_INDEXES: list[str] = [
    # Full-text index for Company — used by GraphRAG NL search
    "CREATE FULLTEXT INDEX company_fulltext IF NOT EXISTS "
    "FOR (n:Company) ON EACH [n.name, n.sector, n.country]",

    "CREATE FULLTEXT INDEX supplier_fulltext IF NOT EXISTS "
    "FOR (n:Supplier) ON EACH [n.name, n.sector, n.country]",
]

SCHEMA_DDL: list[str] = _CONSTRAINTS + _INDEXES + _FULLTEXT_INDEXES


# ---------------------------------------------------------------------------
# Schema application
# ---------------------------------------------------------------------------

def apply_schema(driver: Any) -> dict:
    """
    Apply the complete schema DDL to the connected Neo4j instance.

    This function is idempotent — it can be called on a graph that already
    has the schema applied without error. Each statement uses IF NOT EXISTS.

    Parameters
    ----------
    driver :
        An initialised neo4j.Driver (or the connection module's singleton).
        Accepts any object with a .session() context-manager method so
        tests can pass a mock driver.

    Returns
    -------
    dict
        {
          "constraints_applied": int,
          "indexes_applied": int,
          "fulltext_applied": int,
          "errors": list[str],    # non-fatal — statements that were skipped
        }
    """
    from ecograph.graph.connection import Neo4jQueryError

    stats: dict[str, Any] = {
        "constraints_applied": 0,
        "indexes_applied":     0,
        "fulltext_applied":    0,
        "errors":              [],
    }

    with driver.session() as s:
        for statement in _CONSTRAINTS:
            try:
                s.run(statement)
                stats["constraints_applied"] += 1
            except Exception as exc:
                msg = f"Constraint DDL skipped: {exc!s:.120}"
                stats["errors"].append(msg)
                logger.debug(msg)

        for statement in _INDEXES:
            try:
                s.run(statement)
                stats["indexes_applied"] += 1
            except Exception as exc:
                msg = f"Index DDL skipped: {exc!s:.120}"
                stats["errors"].append(msg)
                logger.debug(msg)

        for statement in _FULLTEXT_INDEXES:
            try:
                s.run(statement)
                stats["fulltext_applied"] += 1
            except Exception as exc:
                msg = f"Full-text DDL skipped: {exc!s:.120}"
                stats["errors"].append(msg)
                logger.debug(msg)

    logger.info(
        "Schema application complete.",
        extra={
            "constraints": stats["constraints_applied"],
            "indexes":     stats["indexes_applied"],
            "fulltext":    stats["fulltext_applied"],
            "skipped":     len(stats["errors"]),
        },
    )
    return stats