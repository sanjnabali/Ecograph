"""
agents/schema.py - Pydantic models that define the LLM output context.

These are the only classes the LLM is allowed to return.
Keeping them seperate from the extractor lets other modules
(neo4j_store, tests) import the data shapes without pulling in the LLM dependencies"""


from  typing import Dict, List, Optional
from pydantic import BaseModel, Field


class Triple(BaseModel):
    """A single Knowledge graph relationship extracted from ESG text"""

    subject: str = Field(
        description=("The source entity - a company name, Facility or scope label"
                     "(e.g. 'Apple Inc.', 'Distribution centre A', 'Scope 3')."
                    )
    )
    predicate: str = Field(
        description= ("The relationship type in UPPER_SNAKE_CASE"
                      "(e.g REPORTS_EMISSION, HAS_SUPPLIER, COMMITS_TO_NET_ZERO, SETS_TARGET).")
    )
    object_value: str = Field(
        description= ("The target entity, metric, or value"
                      "(e.g. 'Supplier X, '5000', '2050', 'Scope 3 Category 11')."
                      )
    )
    metadata: Optional[Dict[str, str]] = Field(
        default = None,
        description= ("Optional supporting context as string key-value pairs,"
                      "e.g. {'unit': 'tCO2e', 'year': '2023', 'standard': 'GRI' }." 
                      "Omit entirely if no additional context is available"),

    )

class ExtractionResult(BaseModel):
    """
    Top-level wrapper the LLM must return - a list of triples."""

    triples: List[Triple] = Field(
        description="All knowledge graph triples extracted from the provided text."
    )