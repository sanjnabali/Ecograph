"""
scripts/bootstrap_graph.py

Full pipeline bootstrap: ingest all raw data sources, resolve entities,
and populate the Neo4j knowledge graph.

Steps
-----
1. Validate Neo4j + Groq credentials.
2. Ingest ERP invoices (CSV -> Supplier + Transaction nodes).
3. Parse ESG PDF reports (text extraction + LLM structuring).
4. Fetch / load TROPOMI satellite data (if available).
5. Run Splink entity resolution and write canonical_ids to graph.
6. Build graph schema constraints and indexes.
7. Build community summaries and upsert to Qdrant vector store.

Usage
-----
    python scripts/bootstrap_graph.py [--skip-esg] [--skip-satellite]
                                      [--skip-er] [--skip-communities]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path so `ecograph` is importable
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("bootstrap")

# ==============================================================================
# Helpers
# ==============================================================================

def _validate_credentials() -> None:
    from ecograph.config.settings import settings
    try:
        settings.validate()
    except Exception as exc:
        logger.error("Credential validation failed: %s", exc)
        sys.exit(1)
    logger.info("Credentials validated.")

def _ingest_erp(data_dir: Path) -> int:
    from ecograph.ingestion.erp_connector import ERPConnector
    from ecograph.knowledge_graph.neo4j_client import get_neo4j_client
    
    csv_path = data_dir / "erp_invoices" / "synthetic_invoices.csv"
    if not csv_path.exists():
        logger.warning("ERP CSV not found at %s - skipping.", csv_path)
        return 0
        
    logger.info("Ingesting ERP invoices from %s", csv_path)
    connector = ERPConnector(str(csv_path))
    records = connector.load()
    db = get_neo4j_client()
    
    from ecograph.knowledge_graph.graph_builder import GraphBuilder
    builder = GraphBuilder(db)
    n = builder.upsert_erp_records(records)
    logger.info("ERP ingestion: %d records written.", n)
    return n

def _ingest_esg(esg_dir: Path) -> int:
    from ecograph.ingestion.esg_pdf_parser import ESGPDFParser
    from ecograph.knowledge_graph.graph_builder import GraphBuilder
    from ecograph.knowledge_graph.neo4j_client import get_neo4j_client
    
    pdfs = list(esg_dir.glob("*.pdf"))
    if not pdfs:
        logger.warning("No ESG PDFs found in %s - skipping.", esg_dir)
        return 0
        
    parser = ESGPDFParser()
    builder = GraphBuilder(get_neo4j_client())
    total = 0
    
    for pdf in pdfs:
        logger.info("Parsing ESG PDF: %s", pdf.name)
        try:
            result = parser.parse(str(pdf))
            n = builder.upsert_esg_disclosure(result, source_file=pdf.name)
            total += n
            logger.info(" -> %d emission records written.", n)
        except Exception as exc:
            logger.error("Failed to parse %s: %s", pdf.name, exc)
            
    return total

def _run_entity_resolution() -> None:
    from ecograph.entity_resolution.splink_model import SplinkModel
    from ecograph.entity_resolution.resolved_entities import (
        build_clusters, write_canonical_ids_to_neo4j,
    )
    from ecograph.knowledge_graph.neo4j_client import get_neo4j_client
    
    logger.info("Running entity resolution (Splink)...")
    db = get_neo4j_client()
    model = SplinkModel()
    preds = model.run_full_pipeline(db)
    result = build_clusters(preds, threshold=0.85)
    n = write_canonical_ids_to_neo4j(result, client=db)
    logger.info(
        "Entity resolution: %d clusters, %d nodes updated.",
        result.n_clusters, n,
    )

def _build_communities() -> None:
    from ecograph.graphrag.community_summarizer import build_community_summaries
    
    logger.info("Building community summaries...")
    records = build_community_summaries()
    logger.info("Built %d community summaries.", len(records))

# ==============================================================================
# Main
# ==============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="EcoGraph full pipeline bootstrap")
    parser.add_argument("--data-dir",       type=Path, default=Path("data/raw"))
    parser.add_argument("--skip-esg",       action="store_true")
    parser.add_argument("--skip-erp",       action="store_true")
    parser.add_argument("--skip-er",        action="store_true", help="Skip entity resolution")
    parser.add_argument("--skip-communities", action="store_true")
    args = parser.parse_args()
    
    logger.info("=== EcoGraph Bootstrap ===")
    _validate_credentials()
    
    if not args.skip_erp:
        _ingest_erp(args.data_dir)
        
    if not args.skip_esg:
        _ingest_esg(args.data_dir / "esg_reports")
        
    if not args.skip_er:
        try:
            _run_entity_resolution()
        except Exception as exc:
            logger.error("Entity resolution failed: %s", exc)
            
    if not args.skip_communities:
        try:
            _build_communities()
        except Exception as exc:
            logger.error("Community summarisation failed: %s", exc)
            
    logger.info("=== Bootstrap complete ===")

if __name__ == "__main__":
    main()