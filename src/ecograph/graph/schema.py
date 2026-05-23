"""
src/graph/schema.py - Neo4j graph schema definition

Defines all node labels, relationship types, properties, constraints, and indexes.
This is the "ontology" of the EcoGraph system.
"""

from enum import Enum
from typing import Set

class NodeLabel(str, Enum):
    """All node types in the graph."""
    Company = "Company"
    Supplier = "Supplier"
    Facility = "Facility"
    Region = "Region"
    EmissionMetric = "EmissionMetric"
    Scope = "Scope"
    GHGCategory = "GHGCategory"
    Year = "Year"
    Target = "Target"
    Observation = "Observation"
    Evidence = "Evidence"
    Policy = "Policy"
    Certification = "Certification"
    
    ALL = {
        "Company", "Supplier", "Facility", "Region", "EmissionMetric",
        "Scope", "GHGCategory", "Year", "Target", "Observation",
        "Evidence", "Policy", "Certification"
    }

class RelationshipType(str, Enum):
    """All relationship types in the graph."""
    # Supply chain topology
    HAS_SUPPLIER = "HAS_SUPPLIER"
    SUPPLIES_TO = "SUPPLIES_TO"
    OPERATES = "OPERATES"
    LOCATED_IN = "LOCATED_IN"
    IN_REGION = "IN_REGION"
    
    # Emissions
    REPORTS_EMISSION = "REPORTS_EMISSION"
    FALLS_UNDER_SCOPE = "FALLS_UNDER_SCOPE"
    MEASURED_IN_YEAR = "MEASURED_IN_YEAR"
    BELONGS_TO_CATEGORY = "BELONGS_TO_CATEGORY"
    
    # Observations
    HAS_OBSERVATION = "HAS_OBSERVATION"
    SUPPORTED_BY = "SUPPORTED_BY"
    
    # Policy & targets
    COMMITS_TO_NET_ZERO = "COMMITS_TO_NET_ZERO"
    SETS_TARGET = "SETS_TARGET"
    GOVERNED_BY = "GOVERNED_BY"
    CERTIFIED_BY = "CERTIFIED_BY"

# Graph schema as Cypher DDL
SCHEMA_DDL = """
// --- Constraints (uniqueness) ---

CREATE CONSTRAINT unique_company_id IF NOT EXISTS
  FOR (c:Company) REQUIRE c.entity_id IS UNIQUE;

CREATE CONSTRAINT unique_supplier_id IF NOT EXISTS
  FOR (s:Supplier) REQUIRE s.entity_id IS UNIQUE;

CREATE CONSTRAINT unique_facility_id IF NOT EXISTS
  FOR (f:Facility) REQUIRE f.entity_id IS UNIQUE;

CREATE CONSTRAINT unique_region_name IF NOT EXISTS
  FOR (r:Region) REQUIRE r.name IS UNIQUE;

CREATE CONSTRAINT unique_scope_name IF NOT EXISTS
  FOR (s:Scope) REQUIRE s.name IS UNIQUE;

CREATE CONSTRAINT unique_ghg_category_name IF NOT EXISTS
  FOR (c:GHGCategory) REQUIRE c.name IS UNIQUE;

CREATE CONSTRAINT unique_observation_id IF NOT EXISTS
  FOR (o:Observation) REQUIRE o.observation_id IS UNIQUE;

// --- Indexes (performance) ---

CREATE INDEX idx_company_name IF NOT EXISTS
  FOR (c:Company) ON (c.name);

CREATE INDEX idx_supplier_name IF NOT EXISTS
  FOR (s:Supplier) ON (s.name);

CREATE INDEX idx_supplier_country IF NOT EXISTS
  FOR (s:Supplier) ON (s.country);

CREATE INDEX idx_facility_name IF NOT EXISTS
  FOR (f:Facility) ON (f.name);

CREATE INDEX idx_emission_metric_value IF NOT EXISTS
  FOR (e:EmissionMetric) ON (e.value);

CREATE INDEX idx_observation_timestamp IF NOT EXISTS
  FOR (o:Observation) ON (o.timestamp);

// --- Full-text index for Company search ---

CREATE FULLTEXT INDEX company_fulltext IF NOT EXISTS
  FOR (c:Company) ON EACH [c.name, c.country, c.sector];
"""

# Node property schemas
NODE_PROPERTIES = {
    "Company": {
        "entity_id": str,      # UUID from ER
        "name": str,           # "Apple Inc"
        "country": str,        # "USA"
        "sector": str,         # "Technology"
        "tax_id": str,         # Optional
        "website": str,        # Optional
        "_is_new": bool,       # Transient flag for ingestion
    },
    "Supplier": {
        "entity_id": str,
        "name": str,
        "country": str,
        "sector": str,
        "supply_chain_tier": int,  # 1 = direct, 2 = Tier-2, etc.
        "latitude": float,     # Optional
        "longitude": float,    # Optional
        "verified": bool,      # Self-reported or verified?
    },
    "Facility": {
        "entity_id": str,
        "name": str,
        "type": str,           # "factory", "warehouse", "power_plant"
        "capacity": float,     # Optional
        "capacity_unit": str,  # "MW", "tonnes/year"
        "latitude": float,
        "longitude": float,
        "country": str,
    },
    "Region": {
        "name": str,           # "South China", "Eastern Europe"
        "country": str,        # Optional
        "carbon_tax": bool,    # Regulatory status
        "carbon_price_usd_per_tonne": float,  # Optional
    },
    "EmissionMetric": {
        "value": float,        # Tonnes CO2e
        "unit": str,           # "tCO2e", "kg CO2e"
        "scope": int,          # 1, 2, or 3
        "category": str,       # For Scope 3: Category 1, 2, ..., 15
    },
    "Observation": {
        "observation_id": str,  # UUID
        "timestamp": str,       # ISO 8601
        "metric": str,          # "co2_flux_tonnes_per_year"
        "value": float,         # Measured value
        "unit": str,            # "tCO2e"
        "method": str,          # "self_reported", "tropomi_cnn", "spend_based"
        "confidence": float,    # 0.0 to 1.0
    },
}

# Relationship property schemas
RELATIONSHIP_PROPERTIES = {
    "HAS_SUPPLIER": {
        "since": str,           # ISO date
        "annual_spend_usd": float,
        "tier": int,
    },
    "REPORTS_EMISSION": {
        "year": int,
        "scope": int,
    },
    "HAS_OBSERVATION": {
        "method": str,
        "timestamp": str,
    },
    "SUPPORTED_BY": {
        "source_type": str,     # "esg_pdf", "erp_invoice", "satellite"
        "confidence": float,
    },
}

def apply_schema(driver) -> dict:
    """
    Apply the complete schema to Neo4j.
    
    Returns:
        dict with counts of created constraints/indexes
    """
    import logging
    logger = logging.getLogger(__name__)
    
    stats = {
        "constraints_created": 0,
        "indexes_created": 0,
        "errors": [],
    }
    
    with driver.session() as session:
        for line in SCHEMA_DDL.split(";"):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                session.run(line)
                if "CONSTRAINT" in line:
                    stats["constraints_created"] += 1
                elif "INDEX" in line:
                    stats["indexes_created"] += 1
            except Exception as exc:
                # May fail if already exists - that's OK
                logger.debug(f"Schema line failed (may be expected): {line[:50]}... — {exc}")
    
    logger.info(f"Schema applied: {stats['constraints_created']} constraints, "
                f"{stats['indexes_created']} indexes")
    return stats