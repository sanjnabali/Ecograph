from pathlib import Path
from ecograph.ingestion.satellite_fetcher import SatelliteFetcher, Facility

repo_root = Path(__file__).resolve().parents[4]
sat_dir = repo_root / "data" / "raw" / "satellite" / "tropomi_monthly"

facility = Facility(
    name="Example Facility",
    latitude=12.34,
    longitude=56.78,
    entity_id="example-facility",
)

fetcher = SatelliteFetcher(sat_dir)
measurement = fetcher.fetch_facility_data(facility)
print(measurement)