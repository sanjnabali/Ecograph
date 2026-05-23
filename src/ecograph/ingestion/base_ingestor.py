"""
src/ingestion/base_ingestor.py - Abstract base class for all ingestors

All data connectors (ERP, ESG, Satellite) inherit from this and implement
the same interface: ingest() → list of typed triples.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

@dataclass
class GraphTriple:
    """
    Atomic unit of graph data: one edge + metadata.
    
    Example:
        subject={"label": "Company", "name": "Apple"},
        relationship="PURCHASES",
        object={"label": "Supplier", "name": "Global Steel"},
        properties={"volume_usd": 500000, "date": "2024-01-15"},
        provenance={"source": "ERP", "file": "invoices.csv", "row": 42}
    """
    subject: Dict[str, Any]          # {"label": str, "id": str, "name": str}
    relationship: str                 # "PURCHASES", "REPORTS_EMISSION"
    object: Dict[str, Any]            # {"label": str, "id": str, "name": str}
    properties: Dict[str, Any]        # Relationship properties
    provenance: Dict[str, Any]        # Source tracking
    confidence: float = 1.0           # For LLM-extracted data
    
    def to_dict(self) -> dict:
        return asdict(self)

class BaseIngestor(ABC):
    """
    Abstract base for all data ingestors.
    
    Subclasses must implement ingest() to return List[GraphTriple].
    """
    
    def __init__(self):
        self.triples: List[GraphTriple] = []
        self.errors: List[str] = []
        self.warnings: List[str] = []
    
    @abstractmethod
    def ingest(self, **kwargs) -> List[GraphTriple]:
        """
        Main ingestion method. Must return list of GraphTriple objects.
        
        Args vary by ingestor type.
        
        Returns:
            List of GraphTriple with all data, provenance, confidence
        """
        pass
    
    def _create_node_id(self, label: str, name: str) -> str:
        """Generate a unique node ID."""
        import hashlib
        s = f"{label}:{name}".lower().encode()
        return hashlib.md5(s).hexdigest()[:12]
    
    def _create_triple(
        self,
        subject_label: str,
        subject_name: str,
        relationship: str,
        object_label: str,
        object_name: str,
        properties: Dict[str, Any],
        source: str,
        source_file: str = "",
        confidence: float = 1.0,
    ) -> GraphTriple:
        """Factory method to create a triple with consistent structure."""
        return GraphTriple(
            subject={
                "label": subject_label,
                "id": self._create_node_id(subject_label, subject_name),
                "name": subject_name,
            },
            relationship=relationship,
            object={
                "label": object_label,
                "id": self._create_node_id(object_label, object_name),
                "name": object_name,
            },
            properties=properties,
            provenance={
                "source": source,
                "file": source_file,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            confidence=confidence,
        )
    
    def get_summary(self) -> dict:
        """Return summary of ingestion."""
        return {
            "triples_created": len(self.triples),
            "errors": self.errors,
            "warnings": self.warnings,
        }