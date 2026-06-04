"""Seed Observation nodes into Neo4j for the Audit Trail page."""
from __future__ import annotations
import sys
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

from ecograph.knowledge_graph.neo4j_client import get_neo4j_client

OBSERVATIONS = [
    ("Sinopec", "co2_scope3", 22_000_000, "tCO2e", "satellite", "TROPOMI/SSP", 0.82),
    ("Apple Inc", "co2_scope3", 22_000_000, "tCO2e", "self_reported", "ESG Report 2023", 0.95),
    ("Apple Inc", "co2_scope3", 20_800_000, "tCO2e", "satellite", "TROPOMI/SSP", 0.78),
    ("Rio Tinto", "co2_scope3", 18_200_000, "tCO2e", "self_reported", "ESG Report 2025", 0.95),
    ("Glencore", "co2_scope3", 15_000_000, "tCO2e", "self_reported", "ESG Report 2024", 0.90),
    ("Microsoft", "co2_scope3", 14_500_000, "tCO2e", "self_reported", "Sustainability Report 2025", 0.97),
    ("Microsoft", "co2_scope1", 100_000, "tCO2e", "self_reported", "Sustainability Report 2025", 0.99),
    ("Microsoft", "co2_scope2", 1_800_000, "tCO2e", "self_reported", "Sustainability Report 2025", 0.91),
    ("BHP Group", "co2_scope3", 9_700_000, "tCO2e", "satellite", "TROPOMI/SSP", 0.74),
    ("Global Steel Corp", "co2_scope3", 8_500_000, "tCO2e", "self_reported", "ESG Report 2024", 0.88),
    ("POSCO", "co2_scope3", 7_600_000, "tCO2e", "self_reported", "Sustainability Report 2025", 0.83),
    ("H&M Group", "co2_scope3", 4_300_000, "tCO2e", "satellite", "TROPOMI/SSP", 0.71),
    ("Foxconn", "co2_scope3", 4_300_000, "tCO2e", "self_reported", "Sustainability Report 2025", 0.94),
    ("Samsung Electronics", "co2_scope3", 3_200_000, "tCO2e", "self_reported", "ESG Report 2024", 0.96),
    ("TSMC", "co2_scope3", 2_100_000, "tCO2e", "self_reported", "Sustainability Report FY2025", 0.97),
    ("NVIDIA", "co2_scope3", 1_200_000, "tCO2e", "self_reported", "Sustainability Report FY2025", 0.97),
]

def main() -> None:
    db = get_neo4j_client()
    base_time = datetime.now(timezone.utc) - timedelta(days=30)
    seeded = 0

    for i, (name, metric, value, unit, method, source, conf) in enumerate(OBSERVATIONS):
        sup_id = hashlib.md5(f"supplier:{name.lower()}".encode()).hexdigest()[:16]
        obs_id = hashlib.md5(f"obs:{name}:{metric}".encode()).hexdigest()[:16]
        ts = (base_time + timedelta(days=i)).isoformat()

        try:
            db.execute_write(
                """
                MATCH (s:Supplier {entity_id: $sup_id})
                MERGE (o:Observation {entity_id: $obs_id})
                SET o.observation_id = $obs_id,
                    o.metric         = $metric,
                    o.value          = $value,
                    o.unit           = $unit,
                    o.method         = $method,
                    o.source         = $source,
                    o.confidence     = $conf,
                    o.timestamp      = $ts,
                    o.supplier_name  = $name
                MERGE (s)-[:HAS_OBSERVATION]->(o)
                """,
                {
                    "sup_id": sup_id, "obs_id": obs_id, "metric": metric,
                    "value": value, "unit": unit, "method": method,
                    "source": source, "conf": conf, "ts": ts,
                    "name": name,
                }
            )
            seeded += 1
            logger.info("✓ %s / %s", name, metric)
        except Exception as exc:
            logger.warning("X %s / %s: %s", name, metric, exc)

    # Verify
    result = db.execute_read("MATCH (o:Observation) RETURN count(o) AS n", {})
    total = result[0]["n"] if result else "?"
    logger.info("Done - seeded %d, total Observation nodes in DB: %s", seeded, total)

if __name__ == "__main__":
    main()