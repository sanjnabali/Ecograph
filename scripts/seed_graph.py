"""
scripts/seed_graph.py  —  Run this once after setting up Neo4j to populate
the dashboard with supplier data, relationships and observations.

Usage:
    python scripts/seed_graph.py
"""
import hashlib
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parents[1] / ".env", override=False)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SUPPLIERS = [
    ("Global Steel Corp",     "CN", 8_500_000),
    ("Samsung Electronics",   "KR", 3_200_000),
    ("TSMC",                  "TW", 2_100_000),
    ("Vale SA",               "BR", 12_000_000),
    ("BHP Group",             "AU", 9_700_000),
    ("Foxconn",               "TW", 4_300_000),
    ("Glencore",              "CH", 15_000_000),
    ("POSCO",                 "KR", 7_800_000),
    ("ArcelorMittal",         "LU", 11_000_000),
    ("Sinopec",               "CN", 22_000_000),
    ("Apple Inc",             "US", 22_600_000),
    ("Microsoft",             "US", 14_500_000),
    ("NVIDIA",                "US", 1_200_000),
    ("H&M Group",             "SE", 4_600_000),
    ("Rio Tinto",             "AU", 18_200_000),
]

RELATIONSHIPS = [
    ("Apple Inc",             "TSMC"),
    ("Apple Inc",             "Foxconn"),
    ("Apple Inc",             "Samsung Electronics"),
    ("Microsoft",             "NVIDIA"),
    ("H&M Group",             "Global Steel Corp"),
    ("Samsung Electronics",   "POSCO"),
    ("Foxconn",               "Sinopec"),
    ("Vale SA",               "ArcelorMittal"),
    ("BHP Group",             "Global Steel Corp"),
    ("Glencore",              "Vale SA"),
    ("ArcelorMittal",         "Global Steel Corp"),
    ("TSMC",                  "Samsung Electronics"),
]

OBSERVATIONS = [
    ("Sinopec",           "co2_scope3", 22_000_000, "tCO2e", "satellite",    "TROPOMI/SSP",                  0.82),
    ("Apple Inc",         "co2_scope3", 22_600_000, "tCO2e", "self_reported","ESG Report 2023",              0.95),
    ("Apple Inc",         "co2_scope3", 20_000_000, "tCO2e", "satellite",    "TROPOMI/SSP",                  0.78),
    ("Rio Tinto",         "co2_scope3", 18_200_000, "tCO2e", "self_reported","ESG Report 2025",              0.95),
    ("Glencore",          "co2_scope3", 15_000_000, "tCO2e", "self_reported","ESG Report 2024",              0.98),
    ("Microsoft",         "co2_scope3", 14_500_000, "tCO2e", "self_reported","Sustainability Report 2025",   0.97),
    ("Microsoft",         "co2_scope1",    100_000, "tCO2e", "self_reported","Sustainability Report 2025",   0.99),
    ("Microsoft",         "co2_scope2",  1_800_000, "tCO2e", "self_reported","Sustainability Report 2025",   0.99),
    ("BHP Group",         "co2_scope3",  9_700_000, "tCO2e", "satellite",    "TROPOMI/SSP",                  0.74),
    ("Global Steel Corp", "co2_scope3",  8_500_000, "tCO2e", "self_reported","ESG Report 2024",              0.88),
    ("POSCO",             "co2_scope3",  7_800_000, "tCO2e", "self_reported","Sustainability Report 2025",   0.83),
    ("H&M Group",         "co2_scope3",  4_600_000, "tCO2e", "satellite",    "TROPOMI/SSP",                  0.71),
    ("Foxconn",           "co2_scope3",  4_300_000, "tCO2e", "self_reported","Sustainability Report 2025",   0.94),
    ("Samsung Electronics","co2_scope3", 3_200_000, "tCO2e", "self_reported","ESG Report 2024",              0.96),
    ("TSMC",              "co2_scope3",  2_100_000, "tCO2e", "self_reported","Sustainability Report FY2025", 0.97),
    ("NVIDIA",            "co2_scope3",  1_200_000, "tCO2e", "self_reported","Sustainability Report FY2025", 0.97),
]


def _eid(name: str) -> str:
    return hashlib.md5(f"supplier:{name.lower()}".encode()).hexdigest()[:16]


def main():
    from ecograph.knowledge_graph.neo4j_client import get_neo4j_client

    db = get_neo4j_client()
    logger.info("Connected to Neo4j.")

    # 1. Schema
    for stmt in [
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Supplier)    REQUIRE n.entity_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Observation) REQUIRE n.entity_id IS UNIQUE",
        "CREATE INDEX IF NOT EXISTS FOR (n:Supplier) ON (n.co2_scope3)",
        "CREATE INDEX IF NOT EXISTS FOR (n:Supplier) ON (n.country_code)",
    ]:
        try:
            db.execute_write(stmt)
        except Exception:
            pass
    logger.info("Schema ready.")

    # 2. Supplier nodes
    ok = 0
    for name, country, co2 in SUPPLIERS:
        try:
            db.execute_write(
                "MERGE (s:Supplier {entity_id: $eid}) "
                "SET s.name = $name, s.country_code = $country, s.co2_scope3 = $co2",
                {"eid": _eid(name), "name": name, "country": country, "co2": co2},
            )
            ok += 1
        except Exception as exc:
            logger.warning("Supplier seed failed (%s): %s", name, exc)
    logger.info("Seeded %d/%d supplier nodes.", ok, len(SUPPLIERS))

    # 3. Supply-chain relationships
    ok = 0
    for buyer, supplier in RELATIONSHIPS:
        try:
            db.execute_write(
                "MATCH (a:Supplier {entity_id: $b_eid}) "
                "MATCH (b:Supplier {entity_id: $s_eid}) "
                "MERGE (a)-[:HAS_SUPPLIER {weight: 1.0}]->(b)",
                {"b_eid": _eid(buyer), "s_eid": _eid(supplier)},
            )
            ok += 1
        except Exception as exc:
            logger.warning("Relationship failed (%s->%s): %s", buyer, supplier, exc)
    logger.info("Created %d/%d supply-chain relationships.", ok, len(RELATIONSHIPS))

    # 4. Observation nodes
    base = datetime.now(timezone.utc) - timedelta(days=30)
    ok = 0
    for i, (name, metric, value, unit, method, source, conf) in enumerate(OBSERVATIONS):
        obs_id = hashlib.md5(f"obs:{name}:{metric}:{i}".encode()).hexdigest()[:16]
        ts = (base + timedelta(days=i)).isoformat()
        try:
            db.execute_write(
                "MATCH (s:Supplier {entity_id: $sup_eid}) "
                "MERGE (o:Observation {entity_id: $obs_id}) "
                "SET o.metric=$metric, o.value=$value, o.unit=$unit, o.method=$method, "
                "    o.source=$source, o.confidence=$conf, o.timestamp=$ts, "
                "    o.supplier_name=$name "
                "MERGE (s)-[:HAS_OBSERVATION]->(o)",
                {
                    "sup_eid": _eid(name), "obs_id": obs_id,
                    "metric": metric, "value": value, "unit": unit,
                    "method": method, "source": source, "conf": conf,
                    "ts": ts, "name": name,
                },
            )
            ok += 1
        except Exception as exc:
            logger.warning("Observation failed (%s/%s): %s", name, metric, exc)
    logger.info("Seeded %d/%d observations.", ok, len(OBSERVATIONS))

    # 5. Verify
    try:
        r = db.execute_read("MATCH (s:Supplier) RETURN count(s) AS n", {})
        supplier_count = r[0]["n"] if r else 0
        r2 = db.execute_read("MATCH (o:Observation) RETURN count(o) AS n", {})
        obs_count = r2[0]["n"] if r2 else 0
        r3 = db.execute_read("MATCH ()-[r:HAS_SUPPLIER]->() RETURN count(r) AS n", {})
        rel_count = r3[0]["n"] if r3 else 0
        logger.info(
            "Graph now has: %d suppliers, %d observations, %d supply relationships.",
            supplier_count, obs_count, rel_count,
        )
    except Exception as exc:
        logger.warning("Verification query failed: %s", exc)

    logger.info("Done. Refresh your Streamlit dashboard.")


if __name__ == "__main__":
    main()