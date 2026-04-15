"""
agents/schema.py - Pydantic models that define the LLM output context.

These are the only classes the LLM is allowed to return.
Keeping them separate from the extractor lets other modules
(neo4j_store, tests) import the data shapes without pulling in the LLM dependencies.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field

# --- PASS 1 SCHEMAS (Entity Recognition) ---
class Entity(BaseModel):
    name: str = Field(description="The exact text of the entity found in the document (e.g., 'Boston Pizza', 'Scope 3 Emissions', '2050').")
    type: str = Field(description="Must be one of: COMPANY, METRIC, INITIATIVE, TARGET, REPORT, STANDARD, YEAR")

class EntityExtractionResult(BaseModel):
    entities: List[Entity] = Field(default_factory=list)

# --- PASS 2 SCHEMAS (Relational Mapping) ---
class Triple(BaseModel):
    """A single Knowledge graph relationship extracted from ESG text"""
    subject: str = Field(
        description=("The source entity - MUST be pulled exactly from the Pass 1 entity list. "
                     "(e.g. 'Apple Inc.', 'Distribution centre A', 'Scope 3').")
    )
    predicate: str = Field(
        description=("The relationship type in UPPER_SNAKE_CASE. "
                     "(e.g REPORTS_EMISSION, HAS_SUPPLIER, COMMITS_TO_NET_ZERO, SETS_TARGET).")
    )
    object_value: str = Field(
        description=("The target entity, metric, or value - MUST be pulled exactly from the Pass 1 entity list. "
                     "(e.g. 'Supplier X', '5000', '2050').")
    )
    metadata: Optional[Dict[str, str]] = Field(
        default=None,
        description=("Optional supporting context as string key-value pairs, "
                     "e.g. {'unit': 'tCO2e', 'year': '2023', 'standard': 'GRI' }. " 
                     "Omit entirely if no additional context is available.")
    )

class ExtractionResult(BaseModel):
    triples: List[Triple] = Field(default_factory=list)