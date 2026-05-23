"""
src/entity_resolution/splink_model.py - Probabilistic entity resolution

Uses Splink (Fellegi-Sunter model) to merge supplier records from different sources.
High-accuracy merging with explainability.
"""

import logging
import pandas as pd
from typing import Dict, List
import splink.comparison_library as cl
from splink import DuckDBAPI, Linker, SettingsCreator

logger = logging.getLogger(__name__)

class SplinERModel:
    """Wrapper around Splink for our domain."""
    
    def __init__(self, threshold: float = 0.85):
        self.threshold = threshold
        self.linker: Linker = None
        self.merged_df = None
    
    def build_linker(self, df: pd.DataFrame) -> Linker:
        """
        Build Fellegi-Sunter comparison model.
        
        Comparisons:
          1. JaroWinkler on name — highest discriminating power
          2. Distance on coordinates — satellite vs reported address
          3. ExactMatch on tax_id — if available
        """
        # Normalize names
        df = df.copy()
        df["canonical_name"] = (
            df["name"]
            .str.lower()
            .str.strip()
            .str.replace(r"[^a-z0-9]", "", regex=True)  # remove special chars
        )
        
        settings = SettingsCreator(
            link_type="dedupe_only",
            comparisons=[
                # Name similarity — primary signal
                cl.JaroWinklerAtThresholds(
                    "canonical_name",
                    [0.95, 0.88, 0.75],
                    name="name_jw"
                ),
                
                # Geographic proximity (if coordinates available)
                cl.DistanceFunctionAtThresholds(
                    col_name_1="latitude",
                    col_name_2="longitude",
                    thresholds=[5.0, 20.0],  # km
                    higher_is_more_similar=False,
                    name="geo_distance"
                ),
                
                # Tax ID exact match (strong signal)
                cl.ExactMatch("tax_id", term_frequency_adjustments=True),
                
                # Country must match (blocking rule)
                cl.ExactMatch("country"),
            ],
            blocking_rules_to_generate_predictions=[
                # Only compare records with same first 3 chars
                "l.canonical_name[:3] = r.canonical_name[:3]",
                # Country code match
                "l.country = r.country",
            ],
            em_convergence=0.0001,
            max_iterations=20,
        )
        
        linker = Linker(df, settings, db_api=DuckDBAPI())
        return linker
    
    def resolve(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Run entity resolution on a dataframe.
        
        Args:
            df: DataFrame with columns: name, country, latitude, longitude, tax_id, etc.
               (latitude, longitude, tax_id can be NULL)
        
        Returns:
            DataFrame with added column: canonical_id (UUID for merged entities)
        """
        logger.info(f"Running entity resolution on {len(df)} records")
        
        self.linker = self.build_linker(df)
        
        # Get predictions above threshold
        preds = self.linker.predict(threshold_match_probability=self.threshold)
        predictions_df = preds.as_pandas()
        
        logger.info(f"Found {len(predictions_df)} matches above threshold {self.threshold}")
        
        # Assign canonical IDs: clusters of matched records get same ID
        canonical_mapping = self._build_canonical_mapping(predictions_df, df)
        
        df["canonical_id"] = df.index.map(lambda i: canonical_mapping.get(i, f"ENT_{i:06d}"))
        
        # Deduplicate: keep first occurrence of each canonical_id
        self.merged_df = df.drop_duplicates(subset=["canonical_id"], keep="first")
        
        logger.info(f"✅ Entity resolution complete: {len(self.merged_df)} canonical entities")
        return self.merged_df
    
    def _build_canonical_mapping(self, predictions_df: pd.DataFrame, original_df: pd.DataFrame) -> Dict:
        """Build mapping from record_id → canonical_id using cluster detection."""
        import uuid
        from collections import defaultdict
        
        # Union-find to group matched records
        parent = {}
        
        def find(x):
            if x not in parent:
                parent[x] = x
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]
        
        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py
        
        # For each matched pair, union them
        for _, row in predictions_df.iterrows():
            idx_l = row.get("index_l")
            idx_r = row.get("index_r")
            if idx_l is not None and idx_r is not None:
                union(idx_l, idx_r)
        
        # Assign canonical ID to each cluster
        cluster_to_canonical = {}
        result = {}
        for i in range(len(original_df)):
            root = find(i)
            if root not in cluster_to_canonical:
                cluster_to_canonical[root] = str(uuid.uuid4())[:8]
            result[i] = cluster_to_canonical[root]
        
        return result