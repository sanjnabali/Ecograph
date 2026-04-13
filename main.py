"""
main.py - EcoGraph Pipeline Entry Point

Stages:
1-3. LangGraph : Extract -> Load -> Resolve  (src/agents/workflow.py)
4.   ERP Load  : mock supplier data          (src/ingestion/erp_loader.py)
5.   Geo Enrich: geocode Region/Facility nodes (src/ingestion/geo_loader.py)

Pre-requisites:
- data/parsed_content/ contains your 5 parsed JSON files
- .env exists with GOOGLE_API_KEY, NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD

Run:
  python main.py                  # full pipeline
  python main.py --skip-geo       # skip geocoding (faster)
  python main.py --skip-erp       # skip ERP mock data
  python main.py --skip-neo4j     # LLM extraction only, skip Neo4j load & resolve
"""

import argparse
import logging
import sys
from pathlib import Path

# -- Central logging MUST be set up before any other src import --
from src.config.logger_config import setup_logging
from src.config.settings import LOG_FILE, PARSED_CONTENT_DIR

setup_logging(log_file=LOG_FILE)
logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------

def _check_prerequisites() -> bool:
    """
    Validates required data directories and .env exist before
    spending any Gemini API quota on a run that would fail.
    """
    project_root = Path(__file__).resolve().parent
    env_file     = project_root / ".env"
    ok = True

    if not env_file.exists():
        logger.error(".env file not found. Copy .env.example -> .env and fill in your keys.")
        ok = False

    if not PARSED_CONTENT_DIR.exists():
        logger.error(
            f"data/parsed_content/ not found at {PARSED_CONTENT_DIR}.\n"
            "Copy your 5 parsed JSON files from your other laptop."
        )
        ok = False
    else:
        json_files = list(PARSED_CONTENT_DIR.glob("*.json"))
        if not json_files:
            logger.error("data/parsed_content/ exists but contains no .json files.")
            ok = False
        else:
            logger.info(f"Found {len(json_files)} parsed JSON file(s) in data/parsed_content/ ✓")

    return ok


def run_extraction_and_graph() -> dict:
    """
    Stage 1 + 2 + 3: LLM extraction -> Neo4j load -> entity resolution.
    Orchestrated via LangGraph (workflow.py).
    """
    logger.info("=" * 60)
    logger.info("STAGE 1-3: LangGraph Pipeline (Extract -> Load -> Resolve)")
    logger.info("=" * 60)

    try:
        from src.agents.workflow import run_pipeline
        final_state = run_pipeline()
        return final_state
    except ImportError as e:
        logger.critical(f"Import error - check your src/ __init__.py files: {e}")
        return {"status": "failed", "errors": [str(e)]}
    except Exception as e:
        logger.critical(f"LangGraph pipeline failed: {e}", exc_info=True)
        return {"status": "failed", "errors": [str(e)]}


def run_erp_load() -> dict:
    """Stage 4: Load mock ERP supplier data into Neo4j."""
    logger.info("=" * 60)
    logger.info("STAGE 4: ERP Supplier Data Load")
    logger.info("=" * 60)

    try:
        from src.graph.connection      import get_driver
        from src.ingestion.erp_loader import load_erp_suppliers
        driver = get_driver()
        stats  = load_erp_suppliers(driver)
        driver.close()
        logger.info(f"ERP load complete: {stats}")
        return stats
    except Exception as exc:
        logger.error(f"ERP load failed (non-fatal): {exc}", exc_info=True)
        return {"error": str(exc)}


def run_geo_enrichment() -> dict:
    """Stage 5: Geocode Region and Facility nodes."""
    logger.info("=" * 60)
    logger.info("STAGE 5: Geospatial Enrichment")
    logger.info("=" * 60)

    try:
        from src.graph.connection      import get_driver
        from src.ingestion.geo_loader import enrich_regions, enrich_facilities
        driver         = get_driver()
        region_stats   = enrich_regions(driver)
        facility_stats = enrich_facilities(driver)
        driver.close()
        logger.info(f"Geo enrichment - Regions: {region_stats} | Facilities: {facility_stats}")
        return {"regions": region_stats, "facilities": facility_stats}
    except Exception as exc:
        logger.error(f"Geo enrichment failed (non-fatal): {exc}", exc_info=True)
        return {"error": str(exc)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="EcoGraph - ESG Knowledge Graph Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                  # Run full pipeline
  python main.py --skip-geo       # Skip geocoding (faster, no internet needed)
  python main.py --skip-neo4j     # Only run LLM extraction (no Neo4j)
  python main.py --skip-erp       # Skip ERP mock data load
        """
    )
    parser.add_argument("--skip-geo",   action="store_true", help="Skip geospatial enrichment")
    parser.add_argument("--skip-erp",   action="store_true", help="Skip ERP data load")
    parser.add_argument("--skip-neo4j", action="store_true",
                        help="Run LLM extraction only - skip Neo4j load, resolve, ERP, and geo")
    # Keep old flag as a hidden alias for backward compatibility
    parser.add_argument("--only-extract", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():
    args = parse_args()

    logger.info("╔════════════════════════════════════════════════════════════╗")
    logger.info("║        EcoGraph - Scope 3 Knowledge Graph Pipeline         ║")
    logger.info("╚════════════════════════════════════════════════════════════╝")

    # Pre-flight checks
    if not _check_prerequisites():
        logger.critical("Pre-flight checks failed. Fix the above errors and re-run.")
        sys.exit(1)

    # Stage 1-3: LangGraph pipeline
    pipeline_state = run_extraction_and_graph()

    # --skip-neo4j (or legacy --only-extract): stop after extraction
    if args.skip_neo4j or args.only_extract:
        logger.info("--skip-neo4j flag set. Stopping after LLM extraction (no Neo4j).")
        _print_summary(pipeline_state, {}, {})
        return

    if pipeline_state.get("status") == "failed":
        logger.error("Pipeline failed. Check logs above. Skipping ERP and Geo stages.")
        _print_summary(pipeline_state, {}, {})
        sys.exit(1)

    # Stage 4: ERP Load
    erp_stats = {}
    if not args.skip_erp:
        erp_stats = run_erp_load()
    else:
        logger.info("STAGE 4: ERP load skipped (--skip-erp).")

    # Stage 5: Geo Enrichment
    geo_stats = {}
    if not args.skip_geo:
        geo_stats = run_geo_enrichment()
    else:
        logger.info("STAGE 5: Geo enrichment skipped (--skip-geo).")

    _print_summary(pipeline_state, erp_stats, geo_stats)


def _print_summary(pipeline_state: dict, erp_stats: dict, geo_stats: dict):
    """Prints a clean final summary of the entire run."""
    neo4j = pipeline_state.get("neo4j_stats", {})
    errors = pipeline_state.get("errors", [])

    logger.info("")
    logger.info("╔════════════════════════════════════════════════════════════╗")
    logger.info("║                      PIPELINE SUMMARY                      ║")
    logger.info("╠════════════════════════════════════════════════════════════╣")
    logger.info(f"║ Status        : {pipeline_state.get('status', 'unknown'):<35}║")
    logger.info(f"║ Triple files  : {len(pipeline_state.get('triple_files', [])):<35}║")
    logger.info(f"║ Neo4j written : {neo4j.get('written', 'N/A'):<35}║")
    logger.info(f"║ Neo4j errors  : {neo4j.get('errors', 'N/A'):<35}║")
    logger.info(f"║ Resolved      : {str(pipeline_state.get('resolved', False)):<35}║")
    if erp_stats:
        logger.info(f"║ ERP nodes     : {erp_stats.get('created', 'N/A'):<35}║")
    if geo_stats and not geo_stats.get("error"):
        r = geo_stats.get("regions", {})
        logger.info(f"║ Regions geocoded: {r.get('geocoded', 'N/A'):<35}║")
    if errors:
        logger.info("║  Warnings/Errors :                                         ║")
        for err in errors[:5]:    # show max 5 inline
            logger.info(f"║   • {str(err)[:48]:<49}║")
    logger.info("╠════════════════════════════════════════════════════════════╣")
    logger.info("║ Full log saved  : ecograph_run.log                         ║")
    logger.info("╚════════════════════════════════════════════════════════════╝")

if __name__ == "__main__":
    main()