"""
scripts/run_pipeline.py

Step-by-step data extraction pipeline.
Runs each step independently so you can stop/resume at any point.

Steps
*****
    1  ERP invoices          -> data/processed/erp/triples.jsonl
    2  Emission factors      -> data/processed/emission_factors/factors.parquet
    3  Supply chain map      -> data/processed/supply_chain/facilities.parquet
    4  ESG PDF reports       -> data/processed/esg/<company>/triples.jsonl
    5  Bootstrap Neo4j       -> graph constraints + indexes + all triples loaded

Usage
*****
    # Run ALL steps
    python scripts/run_pipeline.py

    # Run only specific steps
    python scripts/run_pipeline.py --steps 1 2 3

    # Skip the slow ESG PDF step (Groq calls)
    python scripts/run_pipeline.py --skip 4
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup - works whether run from project root or scripts/
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env", override=False)

import pandas as pd

from ecograph.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s]-%(name)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")

# Output directories
# ------------------
PROCESSED     = PROJECT_ROOT / "data" / "processed"
ERP_OUT       = PROCESSED / "erp"
EF_OUT        = PROCESSED / "emission_factors"
SC_OUT        = PROCESSED / "supply_chain"
ESG_OUT       = PROCESSED / "esg_parsed"          # matches folder you created
GRAPH_OUT     = PROCESSED / "graph_import"
SUMMARY_FILE  = PROCESSED / "pipeline_summary.json"

for _d in (ERP_OUT, EF_OUT, SC_OUT, ESG_OUT, GRAPH_OUT):
    _d.mkdir(parents=True, exist_ok=True)


# ===========================================================================
# STEP 1 - ERP Invoices
# ===========================================================================

def step1_erp() -> dict:
    """Parse synthetic_invoices.csv -> JSONL triples."""
    logger.info("--- STEP 1: ERP invoices ---")
    
    csv_path = PROJECT_ROOT / "data" / "raw" / "erp_invoices" / "synthetic_invoices.csv"
    if not csv_path.exists():
        logger.warning("synthetic_invoices.csv not found - generating now...")
        _generate_erp_data(csv_path)
        
    from ecograph.ingestion.erp_connector import ERPConnector
    connector = ERPConnector()
    result = connector.ingest(csv_path)
    
    out_file = ERP_OUT / "triples.jsonl"
    with open(out_file, "w", encoding="utf-8") as fh:
        for triple in result.triples:
            fh.write(json.dumps(triple.to_dict()) + "\n")
            
    # Also save a flat CSV summary for easy inspection
    rows = []
    for t in result.triples:
        rows.append({
            "subject_name":  t.subject.name,
            "subject_label": t.subject.label,
            "relationship":  t.relationship,
            "object_name":   t.object.name,
            "object_label":  t.object.label,
            "confidence":    t.confidence,
            "source_file":   t.provenance.file,
        })
    pd.DataFrame(rows).to_csv(ERP_OUT / "triples_flat.csv", index=False)
    
    summary = {
        "step": 1,
        "name": "ERP invoices",
        "triples": result.triple_count,
        "errors": result.error_count,
        "output": str(out_file),
    }
    logger.info(" Step 1 done - %d triples -> %s", result.triple_count, out_file)
    return summary


def _generate_erp_data(out_path: Path) -> None:
    """Generate synthetic ERP invoice CSV if the file is missing."""
    gen_script = PROJECT_ROOT / "data" / "synthetic" / "generate_synthetic_erp.py"
    if gen_script.exists():
        import subprocess
        subprocess.run(
            [sys.executable, str(gen_script)],
            check=True,
        )
    else:
        # Minimal inline generator
        logger.info("Generating minimal synthetic ERP data...")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        suppliers = [
            ("SUP001", "Global Steel Corp",     "China", "CN", 31.23, 121.47),
            ("SUP002", "Samsung Electronics",   "South Korea", "KR", 37.51, 126.97),
            ("SUP003", "TSMC",                  "Taiwan", "TW", 24.15, 120.68),
            ("SUP004", "Vale SA",               "Brazil", "BR", -19.9, -43.9),
            ("SUP005", "BHP Group",             "Australia", "AU", -31.9, 115.8),
            ("SUP006", "Foxconn",               "Taiwan", "TW", 25.03, 121.56),
            ("SUP007", "Glencore",              "Switzerland", "CH", 47.0, 8.3),
            ("SUP008", "POSCO",                 "South Korea", "KR", 36.0, 129.5),
            ("SUP009", "ArcelorMittal",         "Luxembourg", "LU", 49.6, 6.1),
            ("SUP010", "Sinopec",               "China", "CN", 39.9, 116.4),
        ]
        rows = []
        import random, string
        rng = random.Random(42)
        categories = ["Steel", "Semiconductors", "Mining", "Electronics", "Chemicals"]
        for i in range(200):
            sup = rng.choice(suppliers)
            rows.append({
                "invoice_id":          f"INV-{i+1:05d}",
                "invoice_date":        f"2024-{rng.randint(1,12):02d}-{rng.randint(1,28):02d}",
                "buyer_id":            "BUY001",
                "buyer_name":          "EcoGraph Demo Corp",
                "supplier_id":         sup[0],
                "supplier_name":       sup[1],
                "commodity_category":  rng.choice(categories),
                "total_value_usd":     round(rng.uniform(50_000, 2_000_000), 2),
                "invoice_qty":         rng.randint(10, 10_000),
                "unit_of_measure":     "units",
                "delivery_location":   sup[2],
                "supplier_country":    sup[3],
                "supplier_lat":        sup[4],
                "supplier_lon":        sup[5],
            })
        pd.DataFrame(rows).to_csv(out_path, index=False)
        logger.info("Generated %d rows -> %s", len(rows), out_path)


# ===========================================================================
# STEP 2 - Emission Factors
# ===========================================================================

def step2_emission_factors() -> dict:
    """Merge all GHG emission-factor Excel files into one clean Parquet."""
    logger.info("--- STEP 2: Emission factors ---")
    
    ef_dir = PROJECT_ROOT / "data" / "raw" / "emission_factors"
    xlsx_files = sorted(ef_dir.glob("ghg-emission-factors-hub*.xlsx"))
    owid_csv = ef_dir / "owid-co2-data.csv"
    
    frames = []
    
    # --- GHG EPA Excel files ---
    for xlsx in xlsx_files:
        try:
            logger.info("Reading %s ...", xlsx.name)
            # EPA hub files have a sheet called "Emission Factors Hub"
            xf = pd.read_excel(xlsx, sheet_name=0, dtype=str)
            xf.columns = [c.strip().lower().replace(" ", "_") for c in xf.columns]
            xf["source_file"] = xlsx.name
            frames.append(xf)
            logger.info("  -> %d rows", len(xf))
        except Exception as exc:
            logger.warning("  Skipped %s: %s", xlsx.name, exc)
            
    if frames:
        ef_combined = pd.concat(frames, ignore_index=True)
        out_xlsx = EF_OUT / "emission_factors_combined.parquet"
        ef_combined.to_parquet(out_xlsx, index=False)
        logger.info("  Saved %d rows -> %s", len(ef_combined), out_xlsx)
        n_ef = len(ef_combined)
    else:
        logger.warning("  No EPA Excel files found.")
        n_ef = 0
        
    # --- OWID CO2 CSV ---
    n_owid = 0
    if owid_csv.exists():
        try:
            owid = pd.read_csv(owid_csv, dtype=str, low_memory=False)
            owid.columns = [c.strip().lower().replace(" ", "_") for c in owid.columns]
            out_owid = EF_OUT / "owid_co2.parquet"
            owid.to_parquet(out_owid, index=False)
            n_owid = len(owid)
            logger.info("  OWID CO2: %d rows -> %s", n_owid, out_owid)
        except Exception as exc:
            logger.warning("  OWID CO2 failed: %s", exc)
            
    summary = {
        "step": 2,
        "name": "Emission factors",
        "rows_epa": n_ef,
        "rows_owid": n_owid,
        "output_dir": str(EF_OUT),
    }
    logger.info(" Step 2 done")
    return summary


# ===========================================================================
# STEP 3 - Supply Chain Map
# ===========================================================================

def step3_supply_chain() -> dict:
    """Process Open Supply Hub + global power plants CSV."""
    logger.info("--- STEP 3: Supply chain facilities ---")
    
    sc_dir = PROJECT_ROOT / "data" / "raw" / "supply_chain"
    fac_dir = PROJECT_ROOT / "data" / "raw" / "facility_reference"
    
    results = {}
    
    osh_csv = sc_dir / "open_supply_hub_facilities.csv"
    if osh_csv.exists():
        try:
            df = pd.read_csv(osh_csv, dtype=str, low_memory=False)
            df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
            out = SC_OUT / "open_supply_hub.parquet"
            df.to_parquet(out, index=False)
            results["open_supply_hub_rows"] = len(df)
            logger.info("  Open Supply Hub: %d facilities -> %s", len(df), out)
        except Exception as exc:
            logger.warning("  Open Supply Hub failed: %s", exc)
    else:
        logger.warning("  open_supply_hub_facilities.csv not found")
        
    gpp_csv = fac_dir / "global_power_plants.csv"
    if gpp_csv.exists():
        try:
            df = pd.read_csv(gpp_csv, dtype=str, low_memory=False)
            df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
            out = SC_OUT / "global_power_plants.parquet"
            df.to_parquet(out, index=False)
            results["power_plants_rows"] = len(df)
            logger.info("  Global power plants: %d facilities -> %s", len(df), out)
        except Exception as exc:
            logger.warning("  Global power plants failed: %s", exc)
    else:
        logger.warning("  global_power_plants.csv not found")
        
    summary = {"step": 3, "name": "Supply chain facilities", **results, "output_dir": str(SC_OUT)}
    logger.info(" Step 3 done")
    return summary


# ===========================================================================
# STEP 4 - ESG PDF Reports (Groq LLM extraction)
# ===========================================================================

def _validate_groq_key() -> bool:
    """Quick check that the Groq API key works before starting PDF processing."""
    import requests as _req
    key = settings.GROQ_API_KEY
    if not key or key == "your_groq_api_key_here":
        logger.error(
            "❌ GROQ_API_KEY is not set in .env\n"
            "   Get a free key at: https://console.groq.com/keys\n"
            "   Then update GROQ_API_KEY in your .env file."
        )
        return False
    try:
        resp = _req.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info(" Groq API key is valid")
            return True
        elif resp.status_code == 401:
            logger.error(
                "❌ Groq API key is INVALID (401 Unauthorized).\n"
                "   Your key: %s...%s\n"
                "   Steps to fix:\n"
                "     1. Go to https://console.groq.com/keys\n"
                "     2. Delete the old key and create a NEW one\n"
                "     3. Copy the new key into .env as GROQ_API_KEY=gsk_...",
                key[:8], key[-4:],
            )
            return False
        else:
            logger.warning("Groq key check returned HTTP %d - proceeding anyway", resp.status_code)
            return True
    except Exception as exc:
        logger.warning("Could not reach Groq to validate key (%s) - proceeding anyway", exc)
        return True


def step4_esg_pdfs() -> dict:
    """
    Extract structured triples from ESG PDF reports using Groq.
    
    Speed optimizations applied:
    - Uses llama-3.1-8b-instant (30,000 TPM vs 6,000 for 70b) -> faster
    - Smaller chunks (3,500 chars ~875 tokens) -> more calls per minute
    - ThreadPoolExecutor(3 workers) -> 3 PDFs processed in parallel
    - Each worker has its own GroqClient with its own token bucket
    - Resume-safe: .done flag skips already-finished PDFs
    - Estimated time: ~12-18 minutes for all 5 PDFs
    """
    logger.info("--- STEP 4: ESG PDF Reports (Groq extraction) ---")
    
    if not _validate_groq_key():
        return {
            "step": 4,
            "name": "ESG PDFs",
            "error": "Invalid or missing GROQ_API_KEY - see instructions above",
            "pdfs_processed": 0,
        }
        
    pdf_dir = PROJECT_ROOT / "data" / "raw" / "esg_reports"
    pdf_files = sorted(pdf_dir.glob("*.pdf"))
    
    if not pdf_files:
        logger.warning("No PDF files found in %s", pdf_dir)
        return {"step": 4, "name": "ESG PDFs", "pdfs_processed": 0}
        
    # Filter already done PDFs
    pending = []
    for pdf_path in pdf_files:
        slug = pdf_path.stem.replace(" ", "_").lower()[:40]
        done_flag = ESG_OUT / slug / ".done"
        if done_flag.exists():
            logger.info("  %s - already done, skipping", pdf_path.name)
        else:
            pending.append(pdf_path)
            
    already_done = len(pdf_files) - len(pending)
    logger.info(
        "  %d PDFs to process, %d already done",
        len(pending), already_done
    )
    
    if not pending:
        return {"step": 4, "name": "ESG PDFs", "pdfs_processed": already_done, "total_triples": 0}
        
    # Worker function - runs in its own thread with its own GroqClient
    # Uses llama-3.1-8b-instant: 30,000 TPM, 30 RPM, 14,400 RPD
    # Chunk size 3,500 chars = 875 tokens prompt -> ~3800 tokens/call total
    # -> ~10 calls/minute per worker
    
    from ecograph.ingestion.esg_pdf_parser import ESGPDFParser
    from ecograph.llm.groq_client import GroqClient
    
    # Shared results list (protected by a lock)
    results_lock = threading.Lock()
    all_results = []
    
    def _process_pdf(pdf_path: Path) -> dict:
        """Process one PDF in a thread."""
        slug = pdf_path.stem.replace(" ", "_").lower()[:40]
        out_dir = ESG_OUT / slug
        out_file = out_dir / "triples.jsonl"
        done_flag = out_dir / ".done"
        out_dir.mkdir(parents=True, exist_ok=True)
        
        thread_name = threading.current_thread().name
        logger.info("[%s] ⏳ Starting: %s", thread_name, pdf_path.name)
        
        try:
            # Each thread gets its own client with its own token bucket
            # 30k TPM / 3 workers = 10k TPM each - well within free tier
            client = GroqClient(
                model="llama-3.1-8b-instant",
                rpm=10,        # 30 RPM shared across 3 workers = 10 each
                tpm=10_000,    # 30k TPM / 3 workers
                rpd=4_800,     # 14,400 RPD / 3 workers
            )
            parser = ESGPDFParser(
                llm_client=client,
                chunk_size=3_500,     # smaller chunks -> fewer tokens per call
                chunk_overlap=300,
            )
            result = parser.ingest(pdf_path)
            
            with open(out_file, "w", encoding="utf-8") as fh:
                for triple in result.triples:
                    fh.write(json.dumps(triple.to_dict()) + "\n")
                    
            # Flat CSV for easy inspection
            rows = [
                {
                    "subject":      t.subject.name,
                    "relationship": t.relationship,
                    "object":       t.object.name,
                    "confidence":   t.confidence,
                    "chunk":        t.provenance.chunk_index,
                }
                for t in result.triples
            ]
            if rows:
                pd.DataFrame(rows).to_csv(out_dir / "triples_flat.csv", index=False)
                
            done_flag.write_text(
                datetime.now(timezone.utc).isoformat(), encoding="utf-8"
            )
            
            logger.info(
                " [%s] ✅ %s -> %d triples, %d errors",
                thread_name, pdf_path.name,
                result.triple_count, result.error_count,
            )
            return {"pdf": pdf_path.name, "triples": result.triple_count, "errors": result.error_count}
            
        except Exception as exc:
            logger.error(" [%s] ❌ %s failed: %s", thread_name, pdf_path.name, exc)
            return {"pdf": pdf_path.name, "error": str(exc)}
            
    # Run up to 3 PDFs in parallel
    workers = min(3, len(pending))
    logger.info(
        " 🚀 Processing %d PDFs with %d parallel workers\n"
        "   (model=llama-3.1-8b-instant, chunk=3500 chars)",
        len(pending), workers
    )
    
    total_triples = 0
    total_errors = 0
    processed = []
    
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="esg") as pool:
        futures = {pool.submit(_process_pdf, pdf): pdf for pdf in pending}
        for future in as_completed(futures):
            res = future.result()
            processed.append(res)
            total_triples += res.get("triples", 0)
            total_errors += res.get("errors", 0)
            
    summary = {
        "step":           4,
        "name":           "ESG PDF reports",
        "pdfs_processed": len(processed) + already_done,
        "total_triples":  total_triples,
        "total_errors":   total_errors,
        "details":        processed,
        "output_dir":     str(ESG_OUT),
    }
    logger.info(
        " 🎉 Step 4 done - %d total triples from %d PDFs",
        total_triples, len(processed),
    )
    return summary


# ===========================================================================
# STEP 5 - Bootstrap Neo4j (load all processed triples into graph)
# ===========================================================================

def step5_bootstrap_neo4j() -> dict:
    """Create schema + load all processed JSONL triples into Neo4j."""
    logger.info("--- STEP 5: Bootstrap Neo4j ---")

    try:
        db = get_neo4j_client()
        db.connect()
        logger.info("✅ Neo4j connected: %s", settings.NEO4J_URI)
    except Exception as exc:
        logger.error("❌ Neo4j connection failed: %s", exc)
        return {"step": 5, "name": "Bootstrap Neo4j", "error": str(exc)}

    # --- Create schema ---
    constraints = [
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Supplier) REQUIRE n.entity_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Company) REQUIRE n.entity_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Facility) REQUIRE n.entity_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Region) REQUIRE n.entity_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Evidence) REQUIRE n.entity_id IS UNIQUE",
    ]
    indexes = [
        "CREATE INDEX IF NOT EXISTS FOR (n:Supplier) ON (n.name)",
        "CREATE INDEX IF NOT EXISTS FOR (n:Supplier) ON (n.country_code)",
        "CREATE INDEX IF NOT EXISTS FOR (n:Supplier) ON (n.co2_scope3)",
    ]
    for cypher in constraints + indexes:
        try:
            db.execute_write(cypher)
        except Exception as exc:
            logger.warning("Schema: %s - %s", cypher[:60], exc)

    logger.info("Schema constraints + indexes created")

    # --- Load ERP triples ---
    erp_jsonl = Path("ERP_OUT / triples.jsonl")
    n_loaded = 0
    if erp_jsonl.exists():
        n_loaded += _load_triples_to_neo4j(db, erp_jsonl, "ERP")

    # --- Load ESG triples ---
    for jsonl in Path("ESG.OUT").rglob("*.jsonl"):
        n_loaded += _load_triples_to_neo4j(db, jsonl, jsonl.parent.name)

    # --- Also load from graph import if any pre-exported files exist ---
    for jsonl in Path("GRAPH_IMPORT").rglob("*.jsonl"):
        n_loaded += _load_triples_to_neo4j(db, jsonl, "graph_import")

    # --- Load synthetic supplier CO2 data ---
    n_loaded += _seed_supplier_co2(db)

    summary = {
        "step": 5,
        "name": "Bootstrap Neo4j",
        "triples_loaded": n_loaded,
    }

    logger.info("✅ Step 5 done - %d triples loaded into Neo4j", n_loaded)
    return summary

def _load_triples_to_neo4j(db, jsonl_path: Path, source_label: str) -> int:
    """Load a JSONL file of GraphTriple dicts into Neo4j via MERGE."""
    loaded = 0
    errors = 0
    with open(jsonl_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                t = json.loads(line)
                subj = t["subject"]
                obj = t["object"]
                rel = t["relationship"]
                props = t.get("properties", {})
                props["confidence"] = t.get("confidence", 1.0)
                props["provenance_source"] = source_label

                cypher = f"""
                MERGE (a:{subj['label']} {{entity_id: $s_id}})
                ON CREATE SET a.name = $s_name, a += $s_extra
                MERGE (b:{obj['label']} {{entity_id: $o_id}})
                ON CREATE SET b.name = $o_name, b += $o_extra
                MERGE (a)-[r:{rel}]->(b)
                ON CREATE SET r += $props
                """
                db.execute_write(
                    cypher,
                    {
                        "s_id": subj["entity_id"],
                        "s_name": subj["name"],
                        "s_extra": subj.get("extra", {}),
                        "o_id": obj["entity_id"],
                        "o_name": obj["name"],
                        "o_extra": obj.get("extra", {}),
                        "props": props,
                    },
                )
                loaded += 1
            except Exception as exc:
                errors += 1
                if errors <= 3:
                    logger.debug("Triple load error: %s", exc)
    logger.info("kg: loaded %d triples (%d errors), %s", loaded, errors, source_label)
    return loaded

def _seed_supplier_co2(db) -> int:
    """
    Seed Supplier nodes with realistic CO2 scope3 values so the
    Supply Chain Map shows data immediately, even before ESG PDFs run.
    """
    suppliers = [
        ("Global Steel Corp", "CN", 8_500_000),
        ("Samsung Electronics", "KR", 3_200_000),
        ("TSMC", "TW", 2_100_000),
        ("Vale SA", "BR", 12_000_000),
        ("BHP Group", "AU", 9_700_000),
        ("Foxconn", "TW", 4_300_000),
        ("Glencore", "CH", 15_000_000),
        ("POSCO", "KR", 7_800_000),
        ("ArcelorMittal", "LU", 11_000_000),
        ("Sinopec", "CN", 22_000_000),
        ("Apple Inc", "US", 22_600_000),
        ("Microsoft", "US", 14_500_000),
        ("NVIDIA", "US", 1_200_000),
        ("H&M Group", "SE", 4_600_000),
        ("Rio Tinto", "AU", 18_200_000),
    ]

    loaded = 0
    for name, country, co2 in suppliers:
        entity_id = hashlib.md5(f"supplier:{name.lower()}".encode()).hexdigest()[:16]
        try:
            db.execute_write(
                """
                MERGE (s:Supplier {entity_id: $id})
                SET s.name = $name,
                    s.country_code = $country,
                    s.co2_scope3 = $co2
                """,
                {"id": entity_id, "name": name, "country": country, "co2": co2},
            )
            loaded += 1
        except Exception as exc:
            logger.warning("Seed supplier failed (%s): %s", name, exc)

    # Add supply relationships between seeded nodes
    relationships = [
        ("Apple Inc", "TSMC"),
        ("Apple Inc", "Foxconn"),
        ("Apple Inc", "Samsung Electronics"),
        ("Microsoft", "NVIDIA"),
        ("H&M Group", "Global Steel Corp"),
        ("Samsung Electronics", "POSCO"),
        ("Foxconn", "Sinopec"),
    ]
    for buyer_name, sup_name in relationships:
        b_id = hashlib.md5(f"supplier:{buyer_name.lower()}".encode()).hexdigest()[:16]
        s_id = hashlib.md5(f"supplier:{sup_name.lower()}".encode()).hexdigest()[:16]
        try:
            db.execute_write(
                """
                MATCH (a:Supplier {entity_id: $b_id})
                MATCH (b:Supplier {entity_id: $s_id})
                MERGE (a)-[:HAS_SUPPLIER {weight: 1.0}]->(b)
                """,
                {"b_id": b_id, "s_id": s_id},
            )
        except Exception:
            pass

    logger.info("Seeded %d supplier nodes with CO2 data", loaded)

    # Seed Observation nodes for the Audit Trail
    _seed_observations(db)

    return loaded

def _seed_observations(db) -> None:
    """Seed Observation nodes so the Audit Trail page has data to show."""
    observations = [
        ("Sinopec", "co2_scope3", 22_000_000, "tCO2e", "satellite", "TROPOMI/SSP", 0.82),
        ("Apple Inc", "co2_scope3", 22_600_000, "tCO2e", "self_reported", "ESG Report 2023", 0.95),
        ("Apple Inc", "co2_scope3", 20_000_000, "tCO2e", "satellite", "TROPOMI/SSP", 0.78),
        ("Rio Tinto", "co2_scope3", 18_200_000, "tCO2e", "self_reported", "ESG Report 2025", 0.95),
        ("Glencore", "co2_scope3", 15_000_000, "tCO2e", "self_reported", "ESG Report 2024", 0.98),
        ("Microsoft", "co2_scope3", 14_500_000, "tCO2e", "self_reported", "Sustainability Report 2025", 0.97),
        ("Microsoft", "co2_scope1", 100_000, "tCO2e", "self_reported", "Sustainability Report 2025", 0.99),
        ("Microsoft", "co2_scope2", 1_800_000, "tCO2e", "self_reported", "Sustainability Report 2025", 0.99),
        ("BHP Group", "co2_scope3", 9_700_000, "tCO2e", "self_reported", "ESG Report 2025", 0.91),
        ("Global Steel Corp", "co2_scope3", 8_500_000, "tCO2e", "satellite", "TROPOMI/SSP", 0.88),
        ("POSCO", "co2_scope3", 7_800_000, "tCO2e", "self_reported", "ESG Report 2024", 0.93),
        ("H&M Group", "co2_scope3", 4_600_000, "tCO2e", "satellite", "TROPOMI/SSP", 0.71),
        ("Foxconn", "co2_scope3", 4_300_000, "tCO2e", "self_reported", "Sustainability Report 2025", 0.94),
        ("Samsung Electronics", "co2_scope3", 3_200_000, "tCO2e", "self_reported", "ESG Report 2024", 0.96),
        ("TSMC", "co2_scope3", 2_100_000, "tCO2e", "self_reported", "Sustainability Report 2024", 0.97),
        ("NVIDIA", "co2_scope3", 1_200_000, "tCO2e", "self_reported", "Sustainability Report FY2025", 0.97),
    ]

    base_time = datetime.now(timezone.utc) - timedelta(days=30)
    seeded = 0
    for i, (name, metric, value, unit, method, source, conf) in enumerate(observations):
        sup_id = hashlib.md5(f"supplier:{name.lower()}".encode()).hexdigest()[:16]
        obs_id = hashlib.md5(f"obs:{name}:{metric}:{i}".encode()).hexdigest()[:16]
        ts = (base_time + timedelta(days=i)).isoformat()
        try:
            db.execute_write(
                """
                MATCH (s:Supplier {entity_id: $sup_id})
                MERGE (o:Observation {entity_id: $obs_id})
                SET o.metric = $metric,
                    o.value = $value,
                    o.unit = $unit,
                    o.method = $method,
                    o.source = $source,
                    o.confidence = $conf,
                    o.timestamp = $ts,
                    o.supplier_name = $name
                MERGE (s)-[:HAS_OBSERVATION]->(o)
                """,
                {
                    "sup_id": sup_id,
                    "obs_id": obs_id,
                    "metric": metric,
                    "value": value,
                    "unit": unit,
                    "method": method,
                    "source": source,
                    "conf": conf,
                    "ts": ts,
                    "name": name,
                },
            )
            seeded += 1
        except Exception as exc:
            logger.warning("Observation seed failed (%s): %s", name, exc)
    logger.info("Seeded %d observation nodes for Audit Trail", seeded)

# --- Main runner ---
STEPS = {
    1: ("ERP invoices", None), # Placeholder for actual function references
    2: ("Emission factors", None),
    3: ("Supply chain facilities", None),
    4: ("ESG PDF reports", None),
    5: ("Bootstrap Neo4j", step5_bootstrap_neo4j),
}

def main() -> None:
    parser = argparse.ArgumentParser(description="EcoGraph data pipeline")
    parser.add_argument("--steps", nargs="+", type=int, help="Steps to run (default: all). Example: --steps 1 2 3")
    parser.add_argument("--skip", nargs="+", type=int, default=[], help="Steps to skip. Example: --skip 4")
    args = parser.parse_args()

    to_run = sorted(args.steps or STEPS.keys())
    to_run = [s for s in to_run if s not in args.skip]

    logger.info("=" * 60)
    logger.info("EcoGraph Data Pipeline")
    logger.info("Steps to run: %s", to_run)
    logger.info("Output root: %s", "PROCESSED")
    logger.info("=" * 60)

    t_start = time.perf_counter()
    summaries = []

    for step_num in to_run:
        if step_num not in STEPS:
            logger.warning("Unknown step %d - skipping", step_num)
            continue
        name, fn = STEPS[step_num]
        logger.info("")
        t0 = time.perf_counter()
        try:
            summary = fn()
            summary["elapsed_s"] = round(time.perf_counter() - t0, 1)
            summaries.append(summary)
        except Exception as exc:
            logger.error("Step %d (%s) FAILED: %s", step_num, name, exc, exc_info=True)
            summaries.append({"step": step_num, "name": name, "error": str(exc)})

    total_elapsed = round(time.perf_counter() - t_start, 1)

    # Save summary JSON
    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "total_elapsed_s": total_elapsed,
        "steps": summaries,
    }
    SUMMARY_FILE = Path("pipeline_summary.json")
    SUMMARY_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")

    logger.info("")
    logger.info("=" * 60)
    logger.info("Pipeline complete in %.1fs", total_elapsed)
    logger.info("Summary saved to %s", SUMMARY_FILE)
    logger.info("=" * 60)

    # Print table
    print("\n| Step | Name | Result |")
    print("|------|------|--------|")
    for s in summaries:
        status = "❌" if "error" in s else "✅"
        print(f"| {s['step']} | {s['name'][:20]} | {status} ({s.get('elapsed_s', '?')}s) |")
    print("\n")

if __name__ == "__main__":
    main()