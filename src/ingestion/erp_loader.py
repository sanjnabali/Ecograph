"""
erp_loader.py - Mock ERP (Enterprise Resource Planning) Data Ingestion.

Purpose
-------
Real-world Scope 3 emissions tracking requires matching extracted supplier names
against a company's own procurement / ERP system records. This module simulates
that by generating a realistic mock ERP dataset and loading supplier records
into Neo4j so they can be connected to entities extracted from ESG PDFs.

In production: replace `generate_mock_erp_data()` with a real database query
or CSV export from systems like SAP, Oracle ERP, or Dynamics 365.
"""

import logging
import random
from typing import List, Dict

from dotenv import load_dotenv
from neo4j import Driver

load_dotenv()

logger = logging.getLogger(__name__)
# NOTE: do NOT call basicConfig here - logging is configured centrally in main.py

# -----------------------------------------------------------------------------
# Mock Data Generator
# -----------------------------------------------------------------------------

_SAMPLE_SUPPLIERS = [
    "Steel Dynamics Inc.", "Flex Ltd.", "Jabil Inc.", "Foxconn Technology",
    "BASF SE", "LG Chem", "Panasonic Corporation", "Murata Manufacturing",
    "Corning Inc.", "3M Company", "Honeywell International", "TE Connectivity",
    "Amphenol Corporation", "Broadcom Inc.", "Qualcomm Inc.", "Taiwan Semiconductor",
    "Samsung Electronics", "SK Hynix", "Micron Technology", "Western Digital",
]

_SPEND_CATEGORIES = [
    "Raw Materials", "Packaging", "Logistics", "Energy", "IT Services",
    "Manufacturing Components", "Professional Services", "Facilities",
]

_REGIONS = ["North America", "Europe", "Asia Pacific", "Latin America", "Middle East"]

def generate_mock_erp_data(num_suppliers: int = 20) -> List[Dict]:
    """
    Generates a list of mock ERP supplier records.

    Each record contains:
    - supplier_name: name of the vendor
    - annual_spend_usd: annual procurement spend
    - spend_category: what they supply
    - region: operational region
    - tier: supply chain tier (Tier 1 = direct, Tier 2 = indirect)
    - contract_active: whether the contract is currently live
    """
    random.seed(42)  # Reproducible mock data
    suppliers = random.sample(_SAMPLE_SUPPLIERS, min(num_suppliers, len(_SAMPLE_SUPPLIERS)))

    records = []
    for supplier in suppliers:
        records.append({
            "supplier_name":    supplier,
            "annual_spend_usd": round(random.uniform(500_000, 50_000_000), 2),
            "spend_category":   random.choice(_SPEND_CATEGORIES),
            "region":           random.choice(_REGIONS),
            "tier":             random.choice([1, 1, 1, 2, 2]),  # weighted toward Tier 1
            "contract_active":  random.choice([True, True, True, False]),
        })

    logger.info(f"Generated {len(records)} mock ERP supplier records.")
    return records

# -----------------------------------------------------------------------------
# Neo4j Loader
# -----------------------------------------------------------------------------

def load_erp_suppliers(driver: Driver, records: List[Dict] = None) -> Dict[str, int]:
    """
    Loads ERP supplier records into Neo4j as Company nodes with ERP properties.
    Uses MERGE so records are idempotent - safe to run multiple times.

    Returns stats dict: {"created": N, "updated": N, "errors": N}
    """
    if records is None:
        records = generate_mock_erp_data()

    stats = {"created": 0, "updated": 0, "errors": 0}

    cypher = """
    MERGE (s:Company {name: $supplier_name})
    ON CREATE SET
        s._is_new           = true,
        s.erp_loaded        = true,
        s.annual_spend_usd  = $annual_spend_usd,
        s.spend_category    = $spend_category,
        s.region            = $region,
        s.supply_chain_tier = $tier,
        s.contract_active   = $contract_active,
        s.source            = 'ERP'
    ON MATCH SET
        s._is_new           = false,
        s.annual_spend_usd  = $annual_spend_usd,
        s.supply_chain_tier = $tier,
        s.contract_active   = $contract_active
    RETURN s._is_new AS was_new
    """

    with driver.session() as session:
        for record in records:
            try:
                result = session.run(cypher, **record).single()
                if result and result["was_new"]:
                    stats["created"] += 1
                else:
                    stats["updated"] += 1
            except Exception as e:
                logger.warning(f"Failed to load ERP record for '{record.get('supplier_name')}': {e}")
                stats["errors"] += 1

    logger.info(
        f"ERP load complete - "
        f"{stats['created']} new nodes | {stats['updated']} updated | {stats['errors']} errors"
    )
    return stats

# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    from src.graph.connection import get_driver
    try:
        driver = get_driver()
        records = generate_mock_erp_data(num_suppliers=20)
        stats = load_erp_suppliers(driver, records)
        logger.info(f"ERP ingestion stats: {stats}")
        driver.close()
    except Exception as e:
        logger.critical(f"ERP loader failed: {e}", exc_info=True)