"""
src/entity_resolution/__init__.py

Entity resolution module for deduplicating and merging similar supplier/company records.

Classes:
    SplinERModel: Probabilistic entity resolution using Splink
    ResolvedEntitiesProcessor: Post-processing and canonical ID assignment
    EntityCluster: Represents a group of merged entities
    UnionFind: Union-Find data structure for clustering
"""

from .splink_model import SplinERModel
from .resolved_entities import (
    ResolvedEntitiesProcessor,
    EntityCluster,
    UnionFind,
)

__all__ = [
    "SplinERModel",
    "ResolvedEntitiesProcessor",
    "EntityCluster",
    "UnionFind",
]