"""
schema.py - Graph Ontology for the EcoGraph Knowledge Graph.

Defines the allowed Node labels and Relationship types that can be
written to Neo4j. Acts as a single source of truth so that neo4j_store.py,
resolver.py, and tools.py all agree on naming.
"""

from dataclasses import dataclass, field
from typing import FrozenSet

# -----------------------------------------------------------------------------
# Node Labels
# -----------------------------------------------------------------------------

class NodeLabel:
    """Canonical Neo4j node labels used across the graph."""

    COMPANY         = "Company"         # e.g. "Apple Inc.", "Supplier Co."
    EMISSION_METRIC = "EmissionMetric"  # a numeric emission value + unit
    SCOPE           = "Scope"           # Scope 1 / 2 / 3
    TARGET          = "Target"          # Net-zero or reduction commitment
    YEAR            = "Year"            # Reporting or target year
    CATEGORY        = "Category"        # GHG Protocol Scope 3 category
    FACILITY        = "Facility"        # A physical site or location
    REGION          = "Region"          # Geographic region / country
    STANDARD        = "Standard"        # Reporting standard (GRI, CDP, TCFD...)

    # Convenience set for validation
    ALL: FrozenSet[str] = frozenset([
        COMPANY, EMISSION_METRIC, SCOPE, TARGET,
        YEAR, CATEGORY, FACILITY, REGION, STANDARD,
    ])

class RelType:
    """Canonical Neo4j relationship types extracted by the LLM."""

    # Emission reporting
    REPORTS_EMISSION    = "REPORTS_EMISSION"    # Company -[REPORTS_EMISSION]-> EmissionMetric
    FALLS_UNDER_SCOPE   = "FALLS_UNDER_SCOPE"   # EmissionMetric -[FALLS_UNDER_SCOPE]-> Scope
    MEASURED_IN_YEAR    = "MEASURED_IN_YEAR"    # EmissionMetric -[MEASURED_IN_YEAR]-> Year
    BELONGS_TO_CATEGORY = "BELONGS_TO_CATEGORY" # EmissionMetric -[BELONGS_TO_CATEGORY]-> Category

    # Targets & commitments
    COMMITS_TO_NET_ZERO = "COMMITS_TO_NET_ZERO" # Company -[COMMITS_TO_NET_ZERO]-> Year
    SETS_TARGET         = "SETS_TARGET"         # Company -[SETS_TARGET]-> Target
    TARGETS_REDUCTION   = "TARGETS_REDUCTION"   # Company -[TARGETS_REDUCTION]-> EmissionMetric

    # Supply chain
    HAS_SUPPLIER        = "HAS_SUPPLIER"        # Company -[HAS_SUPPLIER]-> Company
    SUPPLIES_TO         = "SUPPLIES_TO"         # Company -[SUPPLIES_TO]-> Company
    OPERATES_IN         = "OPERATES_IN"         # Company/Facility -[OPERATES_IN]-> Region

    # Governance
    REPORTS_UNDER       = "REPORTS_UNDER"       # Company -[REPORTS_UNDER]-> Standard
    LOCATED_AT          = "LOCATED_AT"          # Company -[LOCATED_AT]-> Facility

    ALL: FrozenSet[str] = frozenset([
        REPORTS_EMISSION, FALLS_UNDER_SCOPE, MEASURED_IN_YEAR, BELONGS_TO_CATEGORY,
        COMMITS_TO_NET_ZERO, SETS_TARGET, TARGETS_REDUCTION,
        HAS_SUPPLIER, SUPPLIES_TO, OPERATES_IN,
        REPORTS_UNDER, LOCATED_AT,
    ])

# -----------------------------------------------------------------------------
# Cypher index / constraint definitions
# (Applied once at DB setup via neo4j_store.py)
# -----------------------------------------------------------------------------

SCHEMA_CONSTRAINTS = [
    # Uniqueness constraints ensure MERGE works correctly and prevents duplicates
    "CREATE CONSTRAINT company_name IF NOT EXISTS FOR (c:Company) REQUIRE c.name IS UNIQUE",
    "CREATE CONSTRAINT scope_name IF NOT EXISTS FOR (s:Scope) REQUIRE s.name IS UNIQUE",
    "CREATE CONSTRAINT year_value IF NOT EXISTS FOR (y:Year) REQUIRE y.value IS UNIQUE",
    "CREATE CONSTRAINT target_id IF NOT EXISTS FOR (t:Target) REQUIRE t.id IS UNIQUE",
    "CREATE CONSTRAINT category_name IF NOT EXISTS FOR (cat:Category) REQUIRE cat.name IS UNIQUE",
    "CREATE CONSTRAINT region_name IF NOT EXISTS FOR (r:Region) REQUIRE r.name IS UNIQUE",
    "CREATE CONSTRAINT standard_name IF NOT EXISTS FOR (s:Standard) REQUIRE s.name IS UNIQUE",
]

SCHEMA_INDEXES = [
    # Full-text index for fuzzy company name search (used by resolver.py)
    "CREATE FULLTEXT INDEX company_fulltext IF NOT EXISTS FOR (c:Company) ON EACH [c.name]",
    # Standard range index on EmissionMetric value for numeric queries
    "CREATE INDEX emission_value IF NOT EXISTS FOR (e:EmissionMetric) ON (e.value)",
]

@dataclass
class EcoGraphSchema:
    """
    Convenience container - import this in other modules to access
    all ontology constants in one place.
    """
    node:        NodeLabel = field(default_factory=NodeLabel)
    rel:         RelType   = field(default_factory=RelType)
    constraints: list      = field(default_factory=lambda: SCHEMA_CONSTRAINTS)
    indexes:     list      = field(default_factory=lambda: SCHEMA_INDEXES)