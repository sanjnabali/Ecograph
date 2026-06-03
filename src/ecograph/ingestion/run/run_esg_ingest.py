from pathlib import Path
from ecograph.ingestion.esg_pdf_parser import ESGPDFParser

repo_root = Path(__file__).resolve().parents[4]
reports_dir = repo_root / "data" / "raw" / "esg_reports"

parser = ESGPDFParser()
result = parser.ingest_directory(reports_dir)
print(result.summary())
print("Triples extracted:", result.triple_count)