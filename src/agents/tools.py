"""
agents/tools.py - Backward-compatibility shim.

The extraction logic has been split into two focused modules:
  - src/agents/schema.py  -> triples, ExtractionResult (Pydantic models)
  - src/agents/extractor.py -> Scope3Extractor  (the LLM class)
  
This file re-exports everything so any existing code that does
    from src.agents.tools import Scope3Extractor, Triple
continues to work without changes.
"""

from src.agents.schema import Triple, ExtractionResult
from src.agents.extractor import Scope3Extractor


__all__ = ["Triple", "ExtractionResult", "Scope3Extractor"]
