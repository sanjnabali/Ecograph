"""
geo_loader.py - Geospatial Enrichment for EcoGraph.

Purpose
-------
Enriches Company and Facility nodes in Neo4j with geographic coordinates
(latitude / longitude) by geocoding their region/country names.

This enables:
- Visualising the supply chain on a map (Streamlit + pydeck/folium).
- Spatial queries: "find all suppliers within 500km of this facility".
- Carbon-intensity weighting by grid region (e.g., high-coal vs renewable grids).

Data source: Uses the free Nominatim API (OpenStreetMap) - no API key needed.
Rate limit:  1 request/second (enforced internally to respect Nominatim ToS).

In production: swap Nominatim for Google Maps Geocoding API or HERE API
for higher accuracy and rate limits.
"""

import time
import logging
from typing import Optional, Tuple, List, Dict

import requests
from dotenv import load_dotenv
from neo4j import Driver

from src.config.settings import NOMINATIM_URL, NOMINATIM_DELAY, GEO_REQUEST_TIMEOUT

load_dotenv()

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Geocoding
# -----------------------------------------------------------------------------

def geocode_location(location_name: str) -> Optional[Tuple[float, float]]:
    """
    Geocodes a location name string to (latitude, longitude) using Nominatim.
    Returns None if geocoding fails or the location is not found.
    """
    params = {
        "q":       location_name,
        "format":  "json",
        "limit":   1,
    }
    headers = {
        # Nominatim requires a valid User-Agent identifying your application
        "User-Agent": "EcoGraph-ESG-KnowledgeGraph/1.0 (research project)"
    }

    try:
        response = requests.get(
            NOMINATIM_URL, params=params, headers=headers, timeout=GEO_REQUEST_TIMEOUT
        )
        response.raise_for_status()
        results = response.json()

        if results:
            lat = float(results[0]["lat"])
            lon = float(results[0]["lon"])
            logger.debug(f" Geocoded '{location_name}' -> ({{lat:.4f}}, {{lon:.4f}})")
            return lat, lon
        else:
            logger.debug(f" No geocoding result for '{location_name}'")
            return None

    except requests.exceptions.Timeout:
        logger.warning(f"Geocoding timeout for '{location_name}'")
        return None
    except requests.exceptions.RequestException as e:
        logger.warning(f"Geocoding request failed for '{location_name}': {e}")
        return None
    except (KeyError, ValueError, IndexError) as e:
        logger.warning(f"Unexpected geocoding response format for '{location_name}': {e}")
        return None

# -----------------------------------------------------------------------------
# Neo4j: Load coordinates onto Region and Facility nodes
# -----------------------------------------------------------------------------

def _get_ungeocoded_nodes(driver: Driver, label: str, name_prop: str = "name") -> List[str]:
    """
    Returns all node names of a given label that don't yet have lat/lon set
    AND have not been marked as permanently failed (geocode_failed=true).

    Nodes that failed on a previous run are skipped by default.  To retry them,
    clear the flag first:
        MATCH (n:Region) WHERE n.geocode_failed = true REMOVE n.geocode_failed
    """
    cypher = f"""
        MATCH (n:{label})
        WHERE n.latitude IS NULL
          AND n.{name_prop} IS NOT NULL
          AND (n.geocode_failed IS NULL OR n.geocode_failed = false)
        RETURN n.{name_prop} AS name
    """
    with driver.session() as session:
        result = session.run(cypher)
        return [r["name"] for r in result]

def _mark_geocode_failed(driver: Driver, label: str, name: str,
                         name_prop: str = "name") -> None:
    """Sets geocode_failed=true on a node so it is not retried on next run."""
    cypher = f"""
        MATCH (n:{label} {{{name_prop}: $name}})
        SET n.geocode_failed = true
    """
    with driver.session() as session:
        session.run(cypher, name=name)

def _set_coordinates(driver: Driver, label: str, name: str,
                     lat: float, lon: float, name_prop: str = "name") -> None:
    """Writes latitude and longitude onto a Neo4j node."""
    cypher = f"""
        MATCH (n:{label} {{{name_prop}: $name}})
        SET n.latitude = $lat, n.longitude = $lon
    """
    with driver.session() as session:
        session.run(cypher, name=name, lat=lat, lon=lon)

def enrich_regions(driver: Driver) -> Dict[str, int]:
    """
    Geocodes all Region nodes that are missing coordinates.
    Returns stats: {"attempted": N, "geocoded": N, "failed": N}
    """
    logger.info("Geocoding Region nodes...")
    regions = _get_ungeocoded_nodes(driver, "Region")
    return _geocode_and_store(driver, "Region", regions)

def enrich_facilities(driver: Driver) -> Dict[str, int]:
    """
    Geocodes all Facility nodes that are missing coordinates.
    Returns stats: {"attempted": N, "geocoded": N, "failed": N}
    """
    logger.info("Geocoding Facility nodes...")
    facilities = _get_ungeocoded_nodes(driver, "Facility")
    return _geocode_and_store(driver, "Facility", facilities)

def _geocode_and_store(driver: Driver, label: str, names: List[str]) -> Dict[str, int]:
    """Helper: geocodes a list of names and writes coordinates to Neo4j."""
    if not names:
        logger.info(f"  No {label} nodes need geocoding.")
        return {"attempted": 0, "geocoded": 0, "failed": 0}

    logger.info(f"  {len(names)} {label} node(s) to geocode...")
    stats = {"attempted": len(names), "geocoded": 0, "failed": 0}

    for name in names:
        coords = geocode_location(name)
        if coords:
            lat, lon = coords
            _set_coordinates(driver, label, name, lat, lon)
            stats["geocoded"] += 1
        else:
            _mark_geocode_failed(driver, label, name)
            stats["failed"] += 1

        # Respect Nominatim rate limit - 1 request per second
        time.sleep(NOMINATIM_DELAY)

    logger.info(
        f"  {label} geocoding: {stats['geocoded']} succeeded | {stats['failed']} failed"
    )
    return stats

# -----------------------------------------------------------------------------
# Summary query: export enriched nodes for Streamlit map
# -----------------------------------------------------------------------------

def get_geocoded_nodes(driver: Driver) -> List[Dict]:
    """
    Returns all nodes with coordinates - ready for map visualisation.
    Each dict has: {label, name, latitude, longitude}
    """
    cypher = """
        MATCH (n)
        WHERE n.latitude IS NOT NULL AND n.longitude IS NOT NULL
        RETURN labels(n)[0] AS label,
               COALESCE(n.name, n.value) AS name,
               n.latitude AS latitude,
               n.longitude AS longitude
        ORDER BY label, name
    """
    with driver.session() as session:
        result = session.run(cypher)
        return [r.data() for r in result]

# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    from src.graph.connection import get_driver
    try:
        driver = get_driver()
        region_stats    = enrich_regions(driver)
        facility_stats  = enrich_facilities(driver)
        logger.info(f"Geo enrichment complete - Regions: {region_stats} | Facilities: {facility_stats}")
        driver.close()
    except Exception as e:
        logger.critical(f"Geo loader failed: {e}", exc_info=True)