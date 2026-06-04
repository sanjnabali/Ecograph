"""
src/ecograph/knowledge_graph/schema.py

Centralized Neo4j knowledge graph schema definition.

Purpose:
- Define node labels, properties, and relationships
- Provide constraints and indexes for graph integrity
- Enable schema validation and query generation
- Document the knowledge graph structure

Usage:
from ecograph.knowledge_graph.schema import KG_SCHEMA, NodeType, RelationType

# Get all node labels
labels = KG_SCHEMA.get_all_node_labels()

# Validate a triple
is_valid = KG_SCHEMA.validate_triple(subject_type, rel_type, object_type)

# Get Cypher constraints
constraints = KG_SCHEMA.get_constraints()
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Any
from enum import Enum

class NodeType(str, Enum):
    """Enumeration of all node types in the knowledge graph."""
    
    # Core entities
    COMPANY = "Company"
    SUPPLIER = "Supplier"
    FACILITY = "Facility"
    
    # Geographic
    REGION = "Region"
    COUNTRY = "Country"
    
    # Emissions & metrics
    EMISSION_METRIC = "EmissionMetric"
    SCOPE = "Scope"
    
    # Satellite & verification
    OBSERVATION = "Observation"
    SATELLITE_DATA = "SatelliteData"
    
    # ESG & compliance
    ESG_REPORT = "ESGReport"
    CERTIFICATION = "Certification"
    
    # Product & materials
    PRODUCT = "Product"
    MATERIAL = "Material"
    
    # Temporal
    FISCAL_YEAR = "FiscalYear"

class RelationType(str, Enum):
    """Enumeration of all relationship types in the knowledge graph."""
    
    # Supply chain
    SUPPLIES = "SUPPLIES"
    SOURCES_FROM = "SOURCES_FROM"
    MANUFACTURES = "MANUFACTURES"
    OPERATES = "OPERATES"
    
    # Geographic
    LOCATED_IN = "LOCATED_IN"
    HEADQUARTERED_IN = "HEADQUARTERED_IN"
    
    # Emissions
    HAS_EMISSION = "HAS_EMISSION"
    BELONGS_TO_SCOPE = "BELONGS_TO_SCOPE"
    REPORTED_BY = "REPORTED_BY"
    
    # Verification
    VERIFIED_BY = "VERIFIED_BY"
    HAS_OBSERVATION = "HAS_OBSERVATION"
    DISCREPANCY_DETECTED = "DISCREPANCY_DETECTED"
    
    # ESG & compliance
    PUBLISHED = "PUBLISHED"
    HAS_CERTIFICATION = "HAS_CERTIFICATION"
    CERTIFIED_BY = "CERTIFIED_BY"
    
    # Product & materials
    CONTAINS = "CONTAINS"
    USES_MATERIAL = "USES_MATERIAL"
    
    # Temporal
    IN_FISCAL_YEAR = "IN_FISCAL_YEAR"

@dataclass
class NodeSchema:
    """Schema definition for a node type."""
    
    label: str
    required_properties: List[str]
    optional_properties: List[str] = field(default_factory=list)
    unique_property: Optional[str] = None
    indexed_properties: List[str] = field(default_factory=list)
    description: str = ""

@dataclass
class RelationshipSchema:
    """Schema definition for a relationship type."""
    
    type: str
    source_labels: List[str]
    target_labels: List[str]
    properties: List[str] = field(default_factory=list)
    description: str = ""

class KnowledgeGraphSchema:
    """
    Complete knowledge graph schema definition.
    
    Provides:
    - Node schemas with properties
    - Relationship schemas with valid source/target pairs
    - Neo4j constraints and indexes
    - Schema validation methods
    """
    
    def __init__(self):
        self.nodes: Dict[str, NodeSchema] = self._define_nodes()
        self.relationships: Dict[str, RelationshipSchema] = self._define_relationships()
        
    def _define_nodes(self) -> Dict[str, NodeSchema]:
        """Define all node schemas."""
        return {
            NodeType.COMPANY: NodeSchema(
                label="Company",
                required_properties=["entity_id", "name"],
                optional_properties=["country", "sector", "headquarters", "revenue", "employees"],
                unique_property="entity_id",
                indexed_properties=["name", "country", "sector"],
                description="A company entity (customer or tier-0 supplier)"
            ),
            
            NodeType.SUPPLIER: NodeSchema(
                label="Supplier",
                required_properties=["entity_id", "name"],
                optional_properties=["country", "tier", "sector", "annual_volume_usd", "co2_intensity"],
                unique_property="entity_id",
                indexed_properties=["name", "country", "tier"],
                description="A supplier in the supply chain (tier 1-N)"
            ),
            
            NodeType.FACILITY: NodeSchema(
                label="Facility",
                required_properties=["entity_id", "name"],
                optional_properties=["country", "latitude", "longitude", "capacity", "facility_type"],
                unique_property="entity_id",
                indexed_properties=["name", "country"],
                description="A physical facility (factory, warehouse, power plant)"
            ),
            
            NodeType.REGION: NodeSchema(
                label="Region",
                required_properties=["name"],
                optional_properties=["region_type", "parent_region"],
                unique_property="name",
                indexed_properties=["name"],
                description="A geographic region (continent, country, state)"
            ),
            
            NodeType.EMISSION_METRIC: NodeSchema(
                label="EmissionMetric",
                required_properties=["entity_id", "value", "unit"],
                optional_properties=["scope", "source", "methodology", "timestamp", "fiscal_year"],
                unique_property="entity_id",
                indexed_properties=["value", "scope", "fiscal_year"],
                description="An emission measurement (tCO2e, kgCO2e, etc.)"
            ),
            
            NodeType.SCOPE: NodeSchema(
                label="Scope",
                required_properties=["name"],
                optional_properties=["description", "ghg_protocol_version"],
                unique_property="name",
                indexed_properties=["name"],
                description="GHG Protocol scope (Scope 1, 2, 3)"
            ),
            
            NodeType.OBSERVATION: NodeSchema(
                label="Observation",
                required_properties=["observation_id", "timestamp"],
                optional_properties=["satellite", "instrument", "latitude", "longitude", "ch4_ppb", "co2_ppm", "no2_mol_cm2", "qa_value", "cloud_fraction"],
                unique_property="observation_id",
                indexed_properties=["timestamp", "satellite"],
                description="A satellite observation (TROPOMI, Sentinel, etc.)"
            ),
            
            NodeType.ESG_REPORT: NodeSchema(
                label="ESGReport",
                required_properties=["entity_id", "title", "publication_date"],
                optional_properties=["publisher", "scope_1", "scope_2", "scope_3", "url", "file_path"],
                unique_property="entity_id",
                indexed_properties=["title", "publication_date"],
                description="An ESG/sustainability report document"
            ),
            
            NodeType.PRODUCT: NodeSchema(
                label="Product",
                required_properties=["entity_id", "name"],
                optional_properties=["category", "hs_code", "carbon_footprint"],
                unique_property="entity_id",
                indexed_properties=["name", "category"],
                description="A product or SKU"
            ),
            
            NodeType.FISCAL_YEAR: NodeSchema(
                label="FiscalYear",
                required_properties=["year"],
                optional_properties=["start_date", "end_date"],
                unique_property="year",
                indexed_properties=["year"],
                description="A fiscal year period"
            ),
        }
        
    def _define_relationships(self) -> Dict[str, RelationshipSchema]:
        """Define all relationship schemas."""
        return {
            RelationType.SUPPLIES: RelationshipSchema(
                type="SUPPLIES",
                source_labels=["Supplier"],
                target_labels=["Company", "Supplier"],
                properties=["volume_usd", "start_date", "tier"],
                description="Supplier provides goods/services to customer"
            ),
            
            RelationType.SOURCES_FROM: RelationshipSchema(
                type="SOURCES_FROM",
                source_labels=["Company", "Supplier"],
                target_labels=["Supplier"],
                properties=["volume_usd", "start_date"],
                description="Entity sources materials from supplier"
            ),
            
            RelationType.OPERATES: RelationshipSchema(
                type="OPERATES",
                source_labels=["Company", "Supplier"],
                target_labels=["Facility"],
                properties=["ownership_percentage", "start_date"],
                description="Entity operates a facility"
            ),
            
            RelationType.LOCATED_IN: RelationshipSchema(
                type="LOCATED_IN",
                source_labels=["Facility", "Company", "Supplier"],
                target_labels=["Region"],
                properties=[],
                description="Entity is located in a region"
            ),
            
            RelationType.HAS_EMISSION: RelationshipSchema(
                type="HAS_EMISSION",
                source_labels=["Company", "Supplier", "Facility"],
                target_labels=["EmissionMetric"],
                properties=["source", "verified"],
                description="Entity has emission measurement"
            ),
            
            RelationType.BELONGS_TO_SCOPE: RelationshipSchema(
                type="BELONGS_TO_SCOPE",
                source_labels=["EmissionMetric"],
                target_labels=["Scope"],
                properties=[],
                description="Emission belongs to GHG scope"
            ),
            
            RelationType.VERIFIED_BY: RelationshipSchema(
                type="VERIFIED_BY",
                source_labels=["EmissionMetric"],
                target_labels=["Observation"],
                properties=["match_quality", "discrepancy_percent"],
                description="Emission verified by satellite observation"
            ),
            
            RelationType.HAS_OBSERVATION: RelationshipSchema(
                type="HAS_OBSERVATION",
                source_labels=["Facility"],
                target_labels=["Observation"],
                properties=["distance_km"],
                description="Facility has nearby satellite observation"
            ),
            
            RelationType.DISCREPANCY_DETECTED: RelationshipSchema(
                type="DISCREPANCY_DETECTED",
                source_labels=["Observation"],
                target_labels=["Facility", "Supplier"],
                properties=["reported_value", "satellite_value", "discrepancy_percent", "flagged_date"],
                description="Satellite data shows emission discrepancy"
            ),
            
            RelationType.PUBLISHED: RelationshipSchema(
                type="PUBLISHED",
                source_labels=["Company", "Supplier"],
                target_labels=["ESGReport"],
                properties=["publication_date"],
                description="Entity published ESG report"
            ),
            
            RelationType.IN_FISCAL_YEAR: RelationshipSchema(
                type="IN_FISCAL_YEAR",
                source_labels=["EmissionMetric", "ESGReport"],
                target_labels=["FiscalYear"],
                properties=[],
                description="Data belongs to fiscal year"
            ),
        }
        
    def get_all_node_labels(self) -> List[str]:
        """Get all node labels."""
        return [schema.label for schema in self.nodes.values()]
        
    def get_all_relationship_types(self) -> List[str]:
        """Get all relationship types."""
        return [schema.type for schema in self.relationships.values()]
        
    def get_constraints(self) -> List[str]:
        """Generate Neo4j constraint creation queries."""
        constraints = []
        for node_type, schema in self.nodes.items():
            if schema.unique_property:
                label = schema.label
                prop = schema.unique_property
                constraints.append(
                    f"CREATE CONSTRAINT unique_{label.lower()}_{prop} IF NOT EXISTS "
                    f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
                )
        return constraints
        
    def get_indexes(self) -> List[str]:
        """Generate Neo4j index creation queries."""
        indexes = []
        for node_type, schema in self.nodes.items():
            label = schema.label
            for prop in schema.indexed_properties:
                if prop != schema.unique_property: # Skip unique props (already indexed by constraint)
                    indexes.append(
                        f"CREATE INDEX idx_{label.lower()}_{prop} IF NOT EXISTS "
                        f"FOR (n:{label}) ON (n.{prop})"
                    )
        return indexes
        
    def get_fulltext_indexes(self) -> List[str]:
        """Generate full-text search indexes."""
        return [
            "CREATE FULLTEXT INDEX company_fulltext IF NOT EXISTS "
            "FOR (n:Company) ON EACH [n.name, n.country, n.sector]",
            
            "CREATE FULLTEXT INDEX supplier_fulltext IF NOT EXISTS "
            "FOR (n:Supplier) ON EACH [n.name, n.country, n.sector]",
            
            "CREATE FULLTEXT INDEX facility_fulltext IF NOT EXISTS "
            "FOR (n:Facility) ON EACH [n.name, n.country, n.facility_type]"
        ]
        
    def validate_triple(self, subject_type: str, relation_type: str, object_type: str) -> bool:
        """
        Validate if a triple (subject, relation, object) is valid according to schema.
        
        Args:
            subject_type: Source node label
            relation_type: Relationship type
            object_type: Target node label
            
        Returns:
            True if valid, False otherwise
        """
        if relation_type not in self.relationships:
            return False
            
        rel_schema = self.relationships[relation_type]
        return (subject_type in rel_schema.source_labels and
                object_type in rel_schema.target_labels)
                
    def get_node_properties(self, node_label: str) -> List[str]:
        """Get all properties (required + optional) for a node type."""
        for node_type, schema in self.nodes.items():
            if schema.label == node_label:
                return schema.required_properties + schema.optional_properties
        return []
        
    def get_relationship_properties(self, rel_type: str) -> List[str]:
        """Get all properties for a relationship type."""
        if rel_type in self.relationships:
            return self.relationships[rel_type].properties
        return []
        
    def print_schema(self) -> str:
        """Generate human-readable schema documentation."""
        lines = ["# EcoGraph Knowledge Graph Schema\n"]
        
        lines.append("## Node Types\n")
        for node_type, schema in self.nodes.items():
            lines.append(f"### {schema.label}")
            lines.append(f"{schema.description}\n")
            lines.append(f"**Required:** {', '.join(schema.required_properties)}")
            if schema.optional_properties:
                lines.append(f"**Optional:** {', '.join(schema.optional_properties)}")
            lines.append("")
            
        lines.append("\n## Relationship Types\n")
        for rel_type, schema in self.relationships.items():
            lines.append(f"### {schema.type}")
            lines.append(f"{schema.description}")
            lines.append(f"**From:** {', '.join(schema.source_labels)}")
            lines.append(f"**To:** {', '.join(schema.target_labels)}")
            if schema.properties:
                lines.append(f"**Properties:** {', '.join(schema.properties)}")
            lines.append("")
            
        return "\n".join(lines)

# Global schema instance
KG_SCHEMA = KnowledgeGraphSchema()

if __name__ == "__main__":
    # Print schema documentation
    print(KG_SCHEMA.print_schema())
    
    # Print Cypher DDL
    print("\n## Neo4j Constraints\n")
    for constraint in KG_SCHEMA.get_constraints():
        print(constraint)
        
    print("\n## Neo4j Indexes\n")
    for index in KG_SCHEMA.get_indexes():
        print(index)
        
    print("\n## Full-text Indexes\n")
    for index in KG_SCHEMA.get_fulltext_indexes():
        print(index)