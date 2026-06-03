from pathlib import Path
from ecograph.ingestion.erp_connector import ERPConnector

repo_root = Path(__file__).resolve().parents[4]
csv_path = repo_root / "data" / "raw" / "erp_invoices" / "synthetic_invoices.csv"

connector = ERPConnector()
result = connector.ingest(csv_path)
print(result.summary())
print("Triples extracted:", result.triple_count)