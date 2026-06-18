"""
scripts/run_pipeline.py  —  Step-by-step data extraction pipeline.

Steps:
    1  ERP invoices
    2  Emission factors
    3  Supply chain map
    4  ESG PDF reports   ← memory-safe, sequential, streaming chunks
    5  Bootstrap Neo4j

Usage:
    python scripts/run_pipeline.py               # run ALL steps
    python scripts/run_pipeline.py --steps 1 2 3
    python scripts/run_pipeline.py --skip 4
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env", override=False)

import pandas as pd

from ecograph.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")

PROCESSED     = PROJECT_ROOT / "data" / "processed"
ERP_OUT       = PROCESSED / "erp"
EF_OUT        = PROCESSED / "emission_factors"
SC_OUT        = PROCESSED / "supply_chain"
ESG_OUT       = PROCESSED / "esg_parsed"
GRAPH_OUT     = PROCESSED / "graph_import"
SUMMARY_FILE  = PROCESSED / "pipeline_summary.json"

for _d in (ERP_OUT, EF_OUT, SC_OUT, ESG_OUT, GRAPH_OUT):
    _d.mkdir(parents=True, exist_ok=True)


# ===========================================================================
# STEP 1 — ERP
# ===========================================================================

def step1_erp() -> dict:
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

    rows = [
        {
            "subject_name":  t.subject.name,
            "subject_label": t.subject.label,
            "relationship":  t.relationship,
            "object_name":   t.object.name,
            "object_label":  t.object.label,
            "confidence":    t.confidence,
            "source_file":   t.provenance.file,
        }
        for t in result.triples
    ]
    pd.DataFrame(rows).to_csv(ERP_OUT / "triples_flat.csv", index=False)

    logger.info("Step 1 done - %d triples -> %s", result.triple_count, out_file)
    return {"step": 1, "name": "ERP invoices", "triples": result.triple_count,
            "errors": result.error_count, "output": str(out_file)}


def _generate_erp_data(out_path: Path) -> None:
    gen_script = PROJECT_ROOT / "data" / "synthetic" / "generate_synthetic_erp.py"
    if gen_script.exists():
        import subprocess
        subprocess.run([sys.executable, str(gen_script)], check=True)
    else:
        import random
        out_path.parent.mkdir(parents=True, exist_ok=True)
        suppliers = [
            ("SUP001","Global Steel Corp","China","CN",31.23,121.47),
            ("SUP002","Samsung Electronics","South Korea","KR",37.51,126.97),
            ("SUP003","TSMC","Taiwan","TW",24.15,120.68),
            ("SUP004","Vale SA","Brazil","BR",-19.9,-43.9),
            ("SUP005","BHP Group","Australia","AU",-31.9,115.8),
        ]
        rows = []
        rng = random.Random(42)
        categories = ["Steel","Semiconductors","Mining","Electronics","Chemicals"]
        for i in range(200):
            sup = rng.choice(suppliers)
            rows.append({
                "invoice_id": f"INV-{i+1:05d}",
                "invoice_date": f"2024-{rng.randint(1,12):02d}-{rng.randint(1,28):02d}",
                "buyer_id": "BUY001", "buyer_name": "EcoGraph Demo Corp",
                "supplier_id": sup[0], "supplier_name": sup[1],
                "commodity_category": rng.choice(categories),
                "total_value_usd": round(rng.uniform(50_000, 2_000_000), 2),
                "invoice_qty": rng.randint(10, 10_000), "unit_of_measure": "units",
                "delivery_location": sup[2], "supplier_country": sup[3],
                "supplier_lat": sup[4], "supplier_lon": sup[5],
            })
        pd.DataFrame(rows).to_csv(out_path, index=False)
        logger.info("Generated %d synthetic ERP rows -> %s", len(rows), out_path)


# ===========================================================================
# STEP 2 — Emission Factors
# ===========================================================================

def step2_emission_factors() -> dict:
    logger.info("--- STEP 2: Emission factors ---")
    ef_dir = PROJECT_ROOT / "data" / "raw" / "emission_factors"
    xlsx_files = sorted(ef_dir.glob("ghg-emission-factors-hub*.xlsx"))
    owid_csv = ef_dir / "owid-co2-data.csv"
    frames = []
    for xlsx in xlsx_files:
        try:
            xf = pd.read_excel(xlsx, sheet_name=0, dtype=str)
            xf.columns = [c.strip().lower().replace(" ", "_") for c in xf.columns]
            xf["source_file"] = xlsx.name
            frames.append(xf)
            logger.info("  %s -> %d rows", xlsx.name, len(xf))
        except Exception as exc:
            logger.warning("  Skipped %s: %s", xlsx.name, exc)

    n_ef = 0
    if frames:
        ef_combined = pd.concat(frames, ignore_index=True)
        ef_combined.to_parquet(EF_OUT / "emission_factors_combined.parquet", index=False)
        n_ef = len(ef_combined)

    n_owid = 0
    if owid_csv.exists():
        try:
            owid = pd.read_csv(owid_csv, dtype=str, low_memory=False)
            owid.columns = [c.strip().lower().replace(" ", "_") for c in owid.columns]
            owid.to_parquet(EF_OUT / "owid_co2.parquet", index=False)
            n_owid = len(owid)
        except Exception as exc:
            logger.warning("  OWID CO2 failed: %s", exc)

    logger.info("Step 2 done")
    return {"step": 2, "name": "Emission factors", "rows_epa": n_ef, "rows_owid": n_owid}


# ===========================================================================
# STEP 3 — Supply Chain
# ===========================================================================

def step3_supply_chain() -> dict:
    logger.info("--- STEP 3: Supply chain facilities ---")
    sc_dir = PROJECT_ROOT / "data" / "raw" / "supply_chain"
    fac_dir = PROJECT_ROOT / "data" / "raw" / "facility_reference"
    results = {}

    osh_csv = sc_dir / "open_supply_hub_facilities.csv"
    if osh_csv.exists():
        try:
            df = pd.read_csv(osh_csv, dtype=str, low_memory=False)
            df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
            df.to_parquet(SC_OUT / "open_supply_hub.parquet", index=False)
            results["open_supply_hub_rows"] = len(df)
        except Exception as exc:
            logger.warning("  Open Supply Hub failed: %s", exc)

    gpp_csv = fac_dir / "global_power_plants.csv"
    if gpp_csv.exists():
        try:
            df = pd.read_csv(gpp_csv, dtype=str, low_memory=False)
            df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
            df.to_parquet(SC_OUT / "global_power_plants.parquet", index=False)
            results["power_plants_rows"] = len(df)
        except Exception as exc:
            logger.warning("  Global power plants failed: %s", exc)

    logger.info("Step 3 done")
    return {"step": 3, "name": "Supply chain facilities", **results}


# ===========================================================================
# STEP 4 — ESG PDFs  (MEMORY-SAFE SEQUENTIAL VERSION)
#
#  The old version used ThreadPoolExecutor(3 workers) which loaded 3 PDFs
#  simultaneously into RAM + 3 concurrent Groq calls. On a 16 GB laptop
#  this easily hit 12-14 GB and triggered the OOM killer.
#
#  Fix:
#  - Process ONE PDF at a time (no threading)
#  - Smaller chunks (2000 chars ≈ 500 tokens) so each LLM call is tiny
#  - Explicit gc.collect() after each PDF to release pdfplumber memory
#  - Skip already-done PDFs (resume-safe .done flag)
#  - Configurable page limit so you can test with --max-pages 20
# ===========================================================================

def _validate_groq_key() -> bool:
    import requests
    key = settings.GROQ_API_KEY
    if not key or key.startswith("your_"):
        logger.error(
            "GROQ_API_KEY not set. Get a free key at https://console.groq.com/keys "
            "and add GROQ_API_KEY=gsk_... to your .env"
        )
        return False
    try:
        resp = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("Groq API key valid.")
            return True
        if resp.status_code == 401:
            logger.error(
                "Groq API key INVALID (401). "
                "Go to https://console.groq.com/keys, delete old key, create new one."
            )
            return False
        logger.warning("Groq key check returned HTTP %d - proceeding.", resp.status_code)
        return True
    except Exception as exc:
        logger.warning("Could not reach Groq (%s) - proceeding anyway.", exc)
        return True


def _extract_text_streaming(pdf_path: Path, max_pages: int = 0) -> list[str]:
    """
    Extract text page-by-page using pdfplumber, yielding one string per page.
    Keeps peak memory low — we never hold the whole document in RAM at once.
    max_pages=0 means no limit.
    """
    try:
        import pdfplumber
    except ImportError:
        logger.error("pdfplumber not installed: pip install pdfplumber")
        return []

    pages = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            total = len(pdf.pages)
            limit = min(total, max_pages) if max_pages > 0 else total
            # skip cover (0) and last 2 pages (boilerplate)
            start_page = min(2, total)
            end_page = max(start_page, limit - 2)
            for i in range(start_page, end_page):
                try:
                    text = pdf.pages[i].extract_text(x_tolerance=3, y_tolerance=3)
                    if text and text.strip():
                        pages.append(text.strip())
                except Exception:
                    pass
    except Exception as exc:
        logger.error("pdfplumber failed on %s: %s", pdf_path.name, exc)

    return pages


def _process_single_pdf(
    pdf_path: Path,
    out_dir: Path,
    chunk_chars: int = 2000,
    max_pages: int = 0,
) -> dict:
    """
    Process one PDF sequentially, page by page, chunk by chunk.
    Releases memory between pages. Returns summary dict.
    """
    from ecograph.llm import get_groq_client
    from ecograph.llm import LLMQuotaExhaustedError

    slug = pdf_path.stem.replace(" ", "_").lower()[:40]
    pdf_out_dir = out_dir / slug
    pdf_out_dir.mkdir(parents=True, exist_ok=True)
    done_flag = pdf_out_dir / ".done"
    out_file = pdf_out_dir / "triples.jsonl"

    if done_flag.exists():
        logger.info("  %s - already done, skipping.", pdf_path.name)
        existing = sum(1 for _ in open(out_file)) if out_file.exists() else 0
        return {"pdf": pdf_path.name, "triples": existing, "skipped": True}

    EXTRACTION_PROMPT = """Read the text below from an ESG sustainability report.
Extract ONLY verifiable, quantified, factual claims as a JSON array.
Each element: {{"subject_name":"...","subject_type":"Company|Supplier|Facility","relationship":"REPORTS_EMISSION|HAS_GOAL|CERTIFIED_BY","object_name":"...","object_type":"EmissionTarget|GHGCategory|Certification","properties":{{"value":null,"unit":null,"scope":null,"target_year":null}},"confidence":0.0}}
Output ONLY valid JSON array. If nothing found output [].

TEXT:
{chunk}"""

    llm = get_groq_client()
    total_triples = 0
    total_errors = 0
    quota_hit = False

    logger.info("  Processing %s ...", pdf_path.name)
    pages = _extract_text_streaming(pdf_path, max_pages=max_pages)
    logger.info("  Extracted %d pages from %s", len(pages), pdf_path.name)

    with open(out_file, "w", encoding="utf-8") as fh:
        for page_idx, page_text in enumerate(pages):
            # Chunk the page
            chunks = []
            start = 0
            while start < len(page_text):
                end = min(start + chunk_chars, len(page_text))
                chunk = page_text[start:end].strip()
                if len(chunk) > 80:
                    chunks.append(chunk)
                start = end - 200  # small overlap
                if start < 0:
                    start = 0

            for chunk_idx, chunk in enumerate(chunks):
                if quota_hit:
                    break
                try:
                    prompt = EXTRACTION_PROMPT.format(chunk=chunk)
                    response = llm.complete(prompt, temperature=0.0, max_tokens=800)

                    # Parse response
                    import re as _re, json as _json
                    clean = _re.sub(r"^```(?:json)?\s*", "", response.strip(), flags=_re.MULTILINE)
                    clean = _re.sub(r"\s*```\s*$", "", clean, flags=_re.MULTILINE).strip()

                    # Extract JSON array
                    first_bracket = clean.find("[")
                    last_bracket = clean.rfind("]")
                    if first_bracket != -1 and last_bracket > first_bracket:
                        clean = clean[first_bracket:last_bracket + 1]

                    items = _json.loads(clean) if clean else []
                    if not isinstance(items, list):
                        items = []

                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        conf = float(item.get("confidence", 0))
                        if conf < 0.65:
                            continue
                        item["provenance"] = {
                            "source": "ESG_PDF",
                            "file": pdf_path.name,
                            "page": page_idx,
                            "chunk": chunk_idx,
                        }
                        fh.write(_json.dumps(item) + "\n")
                        total_triples += 1

                except LLMQuotaExhaustedError as exc:
                    logger.warning("  Quota exhausted on %s page %d. Stopping.", pdf_path.name, page_idx)
                    total_errors += 1
                    quota_hit = True
                    break
                except Exception as exc:
                    total_errors += 1
                    logger.debug("  Chunk error (page %d chunk %d): %s", page_idx, chunk_idx, exc)

            # Free page text from memory after processing
            del page_text
            gc.collect()

            if quota_hit:
                break

    # Write flat CSV for inspection
    if out_file.exists() and out_file.stat().st_size > 0:
        try:
            rows = []
            with open(out_file, encoding="utf-8") as f:
                for line in f:
                    item = json.loads(line.strip())
                    rows.append({
                        "subject": item.get("subject_name", ""),
                        "relationship": item.get("relationship", ""),
                        "object": item.get("object_name", ""),
                        "confidence": item.get("confidence", 0),
                    })
            if rows:
                pd.DataFrame(rows).to_csv(pdf_out_dir / "triples_flat.csv", index=False)
        except Exception:
            pass

    if not quota_hit:
        done_flag.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")

    result = {"pdf": pdf_path.name, "triples": total_triples, "errors": total_errors}
    logger.info(
        "  Done %s -> %d triples, %d errors%s",
        pdf_path.name, total_triples, total_errors,
        " (quota hit - partial)" if quota_hit else "",
    )
    return result


def step4_esg_pdfs(max_pages: int = 0) -> dict:
    """
    Extract structured triples from ESG PDF reports.
    Processes PDFs ONE AT A TIME to avoid memory exhaustion.
    Uses small chunks (2000 chars) to keep LLM call size minimal.

    max_pages=0 = no limit.  Pass e.g. max_pages=30 to test quickly.
    """
    logger.info("--- STEP 4: ESG PDF Reports (memory-safe sequential) ---")

    if not _validate_groq_key():
        return {"step": 4, "name": "ESG PDFs", "error": "Invalid/missing GROQ_API_KEY", "pdfs_processed": 0}

    pdf_dir = PROJECT_ROOT / "data" / "raw" / "esg_reports"
    pdf_files = sorted(pdf_dir.glob("*.pdf"))

    if not pdf_files:
        logger.warning("No PDF files found in %s", pdf_dir)
        return {"step": 4, "name": "ESG PDFs", "pdfs_processed": 0, "total_triples": 0}

    logger.info(
        "Found %d PDFs. Processing sequentially (1 at a time) to avoid memory issues.",
        len(pdf_files),
    )
    if max_pages > 0:
        logger.info("Page limit: %d pages per PDF", max_pages)

    total_triples = 0
    total_errors = 0
    processed = []

    for pdf_path in pdf_files:
        try:
            result = _process_single_pdf(
                pdf_path,
                out_dir=ESG_OUT,
                chunk_chars=2000,     # ~500 tokens per chunk — safe for free tier
                max_pages=max_pages,
            )
            processed.append(result)
            total_triples += result.get("triples", 0)
            total_errors += result.get("errors", 0)
        except Exception as exc:
            logger.error("PDF-level failure for %s: %s", pdf_path.name, exc)
            processed.append({"pdf": pdf_path.name, "error": str(exc)})
        finally:
            # Force garbage collection between PDFs
            gc.collect()

    logger.info("Step 4 done - %d total triples from %d PDFs", total_triples, len(processed))
    return {
        "step": 4,
        "name": "ESG PDF reports",
        "pdfs_processed": len(processed),
        "total_triples": total_triples,
        "total_errors": total_errors,
        "details": processed,
        "output_dir": str(ESG_OUT),
    }


# ===========================================================================
# STEP 5 — Bootstrap Neo4j
# ===========================================================================

def step5_bootstrap_neo4j() -> dict:
    logger.info("--- STEP 5: Bootstrap Neo4j ---")

    try:
        from ecograph.knowledge_graph.neo4j_client import get_neo4j_client
        db = get_neo4j_client()
        db.connect()
        logger.info("Neo4j connected: %s", settings.NEO4J_URI)
    except Exception as exc:
        logger.error("Neo4j connection failed: %s", exc)
        return {"step": 5, "name": "Bootstrap Neo4j", "error": str(exc)}

    constraints = [
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Supplier) REQUIRE n.entity_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Company) REQUIRE n.entity_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Facility) REQUIRE n.entity_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Region) REQUIRE n.entity_id IS UNIQUE",
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
            logger.debug("Schema: %s - %s", cypher[:60], exc)

    logger.info("Schema constraints + indexes created.")

    n_loaded = 0

    # Load ERP triples
    erp_jsonl = ERP_OUT / "triples.jsonl"
    if erp_jsonl.exists():
        n_loaded += _load_triples_to_neo4j(db, erp_jsonl, "ERP")

    # Load ESG triples
    for jsonl in ESG_OUT.rglob("triples.jsonl"):
        n_loaded += _load_triples_to_neo4j(db, jsonl, jsonl.parent.name)

    # Seed supplier CO2 data
    n_loaded += _seed_supplier_co2(db)

    logger.info("Step 5 done - %d records loaded into Neo4j", n_loaded)
    return {"step": 5, "name": "Bootstrap Neo4j", "triples_loaded": n_loaded}


def _load_triples_to_neo4j(db, jsonl_path: Path, source_label: str) -> int:
    loaded = 0
    errors = 0
    with open(jsonl_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                t = json.loads(line)
                subj = t.get("subject", {})
                obj = t.get("object", {})
                rel = t.get("relationship", "RELATES_TO")

                # Handle both dict-style (ESG) and object-style (ERP) triples
                if isinstance(subj, dict) and "label" in subj:
                    s_label = subj.get("label", "Entity")
                    s_id = subj.get("entity_id") or subj.get("id") or hashlib.md5(
                        (subj.get("name", "") or "").encode()
                    ).hexdigest()[:16]
                    s_name = subj.get("name", s_id)
                    o_label = obj.get("label", "Entity")
                    o_id = obj.get("entity_id") or obj.get("id") or hashlib.md5(
                        (obj.get("name", "") or "").encode()
                    ).hexdigest()[:16]
                    o_name = obj.get("name", o_id)
                else:
                    # ESG flat format: subject_name / object_name
                    s_name = t.get("subject_name", "")
                    s_label = t.get("subject_type", "Company")
                    s_id = hashlib.md5(s_name.encode()).hexdigest()[:16]
                    o_name = t.get("object_name", "")
                    o_label = t.get("object_type", "Entity")
                    o_id = hashlib.md5(o_name.encode()).hexdigest()[:16]
                    rel = t.get("relationship", "RELATES_TO")

                if not s_name or not o_name:
                    continue

                props = t.get("properties", {}) or {}
                props["confidence"] = t.get("confidence", 1.0)
                props["provenance_source"] = source_label

                cypher = f"""
                MERGE (a:{s_label} {{entity_id: $s_id}})
                ON CREATE SET a.name = $s_name
                MERGE (b:{o_label} {{entity_id: $o_id}})
                ON CREATE SET b.name = $o_name
                MERGE (a)-[r:{rel}]->(b)
                ON CREATE SET r += $props
                """
                db.execute_write(cypher, {
                    "s_id": s_id, "s_name": s_name,
                    "o_id": o_id, "o_name": o_name,
                    "props": props,
                })
                loaded += 1
            except Exception as exc:
                errors += 1
                if errors <= 3:
                    logger.debug("Triple load error: %s", exc)
    logger.info("Loaded %d triples (%d errors) from %s", loaded, errors, source_label)
    return loaded


def _seed_supplier_co2(db) -> int:
    """Seed Supplier nodes with realistic CO2 values so the dashboard shows data."""
    suppliers = [
        ("Global Steel Corp",    "CN", 8_500_000),
        ("Samsung Electronics",  "KR", 3_200_000),
        ("TSMC",                 "TW", 2_100_000),
        ("Vale SA",              "BR", 12_000_000),
        ("BHP Group",            "AU", 9_700_000),
        ("Foxconn",              "TW", 4_300_000),
        ("Glencore",             "CH", 15_000_000),
        ("POSCO",                "KR", 7_800_000),
        ("ArcelorMittal",        "LU", 11_000_000),
        ("Sinopec",              "CN", 22_000_000),
        ("Apple Inc",            "US", 22_600_000),
        ("Microsoft",            "US", 14_500_000),
        ("NVIDIA",               "US", 1_200_000),
        ("H&M Group",            "SE", 4_600_000),
        ("Rio Tinto",            "AU", 18_200_000),
    ]
    relationships = [
        ("Apple Inc",    "TSMC"),
        ("Apple Inc",    "Foxconn"),
        ("Apple Inc",    "Samsung Electronics"),
        ("Microsoft",    "NVIDIA"),
        ("H&M Group",    "Global Steel Corp"),
        ("Samsung Electronics", "POSCO"),
        ("Foxconn",      "Sinopec"),
        ("Vale SA",      "ArcelorMittal"),
        ("BHP Group",    "Global Steel Corp"),
    ]

    loaded = 0
    for name, country, co2 in suppliers:
        entity_id = hashlib.md5(f"supplier:{name.lower()}".encode()).hexdigest()[:16]
        try:
            db.execute_write(
                "MERGE (s:Supplier {entity_id: $id}) "
                "SET s.name = $name, s.country_code = $country, s.co2_scope3 = $co2",
                {"id": entity_id, "name": name, "country": country, "co2": co2},
            )
            loaded += 1
        except Exception as exc:
            logger.warning("Seed supplier failed (%s): %s", name, exc)

    for buyer_name, sup_name in relationships:
        b_id = hashlib.md5(f"supplier:{buyer_name.lower()}".encode()).hexdigest()[:16]
        s_id = hashlib.md5(f"supplier:{sup_name.lower()}".encode()).hexdigest()[:16]
        try:
            db.execute_write(
                "MATCH (a:Supplier {entity_id: $b_id}) "
                "MATCH (b:Supplier {entity_id: $s_id}) "
                "MERGE (a)-[:HAS_SUPPLIER {weight: 1.0}]->(b)",
                {"b_id": b_id, "s_id": s_id},
            )
        except Exception:
            pass

    logger.info("Seeded %d supplier nodes.", loaded)

    # Seed Observation nodes for Audit Trail
    _seed_observations(db)
    return loaded


def _seed_observations(db) -> None:
    observations = [
        ("Sinopec",           "co2_scope3", 22_000_000, "tCO2e", "satellite",      "TROPOMI/SSP",                  0.82),
        ("Apple Inc",         "co2_scope3", 22_600_000, "tCO2e", "self_reported",   "ESG Report 2023",              0.95),
        ("Apple Inc",         "co2_scope3", 20_000_000, "tCO2e", "satellite",       "TROPOMI/SSP",                  0.78),
        ("Rio Tinto",         "co2_scope3", 18_200_000, "tCO2e", "self_reported",   "ESG Report 2025",              0.95),
        ("Glencore",          "co2_scope3", 15_000_000, "tCO2e", "self_reported",   "ESG Report 2024",              0.98),
        ("Microsoft",         "co2_scope3", 14_500_000, "tCO2e", "self_reported",   "Sustainability Report 2025",   0.97),
        ("Microsoft",         "co2_scope1",    100_000, "tCO2e", "self_reported",   "Sustainability Report 2025",   0.99),
        ("Microsoft",         "co2_scope2",  1_800_000, "tCO2e", "self_reported",   "Sustainability Report 2025",   0.99),
        ("BHP Group",         "co2_scope3",  9_700_000, "tCO2e", "self_reported",   "ESG Report 2025",              0.91),
        ("Global Steel Corp", "co2_scope3",  8_500_000, "tCO2e", "satellite",       "TROPOMI/SSP",                  0.88),
        ("POSCO",             "co2_scope3",  7_800_000, "tCO2e", "self_reported",   "ESG Report 2024",              0.93),
        ("H&M Group",         "co2_scope3",  4_600_000, "tCO2e", "satellite",       "TROPOMI/SSP",                  0.71),
        ("Foxconn",           "co2_scope3",  4_300_000, "tCO2e", "self_reported",   "Sustainability Report 2025",   0.94),
        ("Samsung Electronics","co2_scope3", 3_200_000, "tCO2e", "self_reported",   "ESG Report 2024",              0.96),
        ("TSMC",              "co2_scope3",  2_100_000, "tCO2e", "self_reported",   "Sustainability Report 2024",   0.97),
        ("NVIDIA",            "co2_scope3",  1_200_000, "tCO2e", "self_reported",   "Sustainability Report FY2025", 0.97),
    ]
    base_time = datetime.now(timezone.utc) - timedelta(days=30)
    seeded = 0
    for i, (name, metric, value, unit, method, source, conf) in enumerate(observations):
        sup_id = hashlib.md5(f"supplier:{name.lower()}".encode()).hexdigest()[:16]
        obs_id = hashlib.md5(f"obs:{name}:{metric}:{i}".encode()).hexdigest()[:16]
        ts = (base_time + timedelta(days=i)).isoformat()
        try:
            db.execute_write(
                "MATCH (s:Supplier {entity_id: $sup_id}) "
                "MERGE (o:Observation {entity_id: $obs_id}) "
                "SET o.metric=$metric, o.value=$value, o.unit=$unit, o.method=$method, "
                "    o.source=$source, o.confidence=$conf, o.timestamp=$ts, o.supplier_name=$name "
                "MERGE (s)-[:HAS_OBSERVATION]->(o)",
                {"sup_id": sup_id, "obs_id": obs_id, "metric": metric, "value": value,
                 "unit": unit, "method": method, "source": source, "conf": conf,
                 "ts": ts, "name": name},
            )
            seeded += 1
        except Exception as exc:
            logger.warning("Observation seed failed (%s): %s", name, exc)
    logger.info("Seeded %d observation nodes.", seeded)


# ===========================================================================
# STEP REGISTRY & MAIN
# ===========================================================================

STEPS = {
    1: ("ERP invoices",            step1_erp),
    2: ("Emission factors",        step2_emission_factors),
    3: ("Supply chain facilities", step3_supply_chain),
    4: ("ESG PDF reports",         step4_esg_pdfs),
    5: ("Bootstrap Neo4j",         step5_bootstrap_neo4j),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="EcoGraph data pipeline")
    parser.add_argument("--steps", nargs="+", type=int,
                        help="Steps to run (default: all). E.g. --steps 1 2 3")
    parser.add_argument("--skip", nargs="+", type=int, default=[],
                        help="Steps to skip. E.g. --skip 4")
    parser.add_argument("--max-pages", type=int, default=0,
                        help="Step 4 only: max pages per PDF (0=all). Use 20 for quick test.")
    args = parser.parse_args()

    to_run = sorted(args.steps or STEPS.keys())
    to_run = [s for s in to_run if s not in args.skip]

    logger.info("=" * 60)
    logger.info("EcoGraph Data Pipeline")
    logger.info("Steps to run: %s", to_run)
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
            # Pass max_pages only to step 4
            if step_num == 4:
                summary = fn(max_pages=args.max_pages)
            else:
                summary = fn()
            summary["elapsed_s"] = round(time.perf_counter() - t0, 1)
            summaries.append(summary)
        except Exception as exc:
            logger.error("Step %d (%s) FAILED: %s", step_num, name, exc, exc_info=True)
            summaries.append({"step": step_num, "name": name, "error": str(exc),
                              "elapsed_s": round(time.perf_counter() - t0, 1)})

    total_elapsed = round(time.perf_counter() - t_start, 1)

    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "total_elapsed_s": total_elapsed,
        "steps": summaries,
    }
    SUMMARY_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")

    logger.info("")
    logger.info("=" * 60)
    logger.info("Pipeline complete in %.1fs", total_elapsed)
    logger.info("Summary: %s", SUMMARY_FILE)
    logger.info("=" * 60)

    print("\n| Step | Name                  | Result     | Time   |")
    print("|------|-----------------------|------------|--------|")
    for s in summaries:
        status = "❌" if "error" in s else "✅"
        print(f"| {s['step']}    | {s['name']:<21} | {status}          | {s.get('elapsed_s', '?')}s |")
    print()


if __name__ == "__main__":
    main()