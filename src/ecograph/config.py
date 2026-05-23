# src/ecograph/config.py — one place that knows all paths

from pathlib import Path

ROOT = Path(__file__).parent.parent.parent   # project root

class DataPaths:
    # Raw
    SATELLITE_RAW   = ROOT / "data/raw/satellite/tropomi_monthly"
    POWER_PLANTS    = ROOT / "data/raw/facility_reference/global_power_plants.csv"
    OSH_FACILITIES  = ROOT / "data/raw/supply_chain/open_supply_hub_facilities.csv"
    ESG_PDFS        = ROOT / "data/raw/esg_reports"
    EPA_FACTORS     = ROOT / "data/raw/emission_factors"
    OWID_CO2        = ROOT / "data/raw/emission_factors/owid_co2_data.csv"

    # Processed
    NO2_GRIDS       = ROOT / "data/processed/satellite/no2_grids"
    HOTSPOTS        = ROOT / "data/processed/satellite/hotspots"
    FLUX_ESTIMATES  = ROOT / "data/processed/satellite/flux_estimates"
    ESG_TRIPLES     = ROOT / "data/processed/esg_parsed"
    ER_OUTPUT       = ROOT / "data/processed/entity_resolution/entities_resolved.parquet"
    GRAPH_NODES     = ROOT / "data/processed/graph_import/nodes.jsonl"
    GRAPH_EDGES     = ROOT / "data/processed/graph_import/edges.jsonl"

    # Synthetic
    SYNTHETIC_ERP   = ROOT / "data/synthetic/synthetic_invoices.csv"