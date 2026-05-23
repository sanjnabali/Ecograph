"""
src/ecograph/ingestion/erp_connector.py

Ingests structured ERP invoice / BOM data from CSV files.

Each CSV row produces three triples:
  1. (Company) -[:PURCHASES]-> (Supplier)
  2. (Supplier) -[:LOCATED_IN]-> (Region)           when country present
  3. (Supplier) -[:OPERATES]-> (Facility)            when location present

Design decisions:
- We read the entire CSV into a DataFrame once, then iterate rows. For files
  up to a few million rows this is fine on 16GB RAM. For larger files, replace
  pd.read_csv with pd.read_csv(..., chunksize=...) and loop over chunks.
- Column name normalisation (strip, lower, replace spaces) means we handle
  inconsistently formatted exports without changing the caller.
- Type coercion is explicit — float("nan") values from pandas become None
  in properties rather than NaN, which Neo4j cannot store.
- Every row failure is accumulated as an error string rather than re-raised,
  so a single bad row does not abort the entire file.
- The ingest() method validates required columns upfront, before iterating
  rows, so we fail fast with a clear message rather than crashing midway.
"""

import logging
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from ecograph.graph.schema import NodeLabel, RelationshipType
from ecograph.ingestion.base_ingestor import (
    BaseIngestor,
    GraphTriple,
    IngestionResult,
    NodeRef,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column mapping — maps our canonical names to what we expect in the CSV
# (after normalisation: strip + lower + replace spaces with _)
# ---------------------------------------------------------------------------

_REQUIRED_COLUMNS = {
    "invoice_id",
    "invoice_date",
    "buyer_id",
    "buyer_name",
    "supplier_id",
    "supplier_name",
}

_OPTIONAL_COLUMNS = {
    "commodity_category",
    "total_value_usd",
    "invoice_qty",
    "unit_of_measure",
    "delivery_location",
    "supplier_country",
    "supplier_lat",
    "supplier_lon",
}


# ---------------------------------------------------------------------------
# Ingestor
# ---------------------------------------------------------------------------

class ERPConnector(BaseIngestor):
    """
    Reads ERP invoice CSV exports and converts rows to graph triples.

    Usage:
        connector = ERPConnector()
        result = connector.ingest(filepath="data/raw/erp_invoices/synthetic_invoices.csv")
        # result.triples is a list[GraphTriple]
    """

    def __init__(self) -> None:
        super().__init__(source_name="ERP")

    def ingest(self, filepath: str | Path, **kwargs: Any) -> IngestionResult:
        """
        Parse a CSV file and return graph triples.

        Parameters
        ----------
        filepath :
            Path to the CSV file. Absolute or relative to the project root.

        Returns
        -------
        IngestionResult
            .triples contains one or more GraphTriple objects per valid row.
            .errors contains descriptions of rows that failed.

        Raises
        ------
        FileNotFoundError
            If the CSV file does not exist.
        ValueError
            If required columns are missing from the CSV.
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(
                f"ERP CSV not found: {filepath}. "
                "Run data/synthetic/generate_erp.py to create sample data."
            )

        self._logger.info("Starting ERP ingestion.", extra={"file": str(filepath)})

        df = self._read_csv(filepath)
        self._validate_columns(df, filepath)

        triples: list[GraphTriple] = []
        errors: list[str] = []
        warnings: list[str] = []

        for row_idx, row in df.iterrows():
            try:
                row_triples = self._process_row(row, str(filepath), int(row_idx))
                triples.extend(row_triples)
            except Exception as exc:
                msg = f"Row {row_idx}: {exc}"
                errors.append(msg)
                self._logger.debug("ERP row skipped: %s", msg)

        result = IngestionResult(
            triples=triples,
            error_count=len(errors),
            warning_count=len(warnings),
            errors=errors,
            source="ERP",
        )

        self._logger.info(
            "ERP ingestion complete.",
            extra=result.summary(),
        )
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _read_csv(self, filepath: Path) -> pd.DataFrame:
        """Read CSV, normalise column names, parse dates."""
        df = pd.read_csv(
            filepath,
            dtype=str,               # read everything as str first — we coerce later
            keep_default_na=False,   # don't silently convert "NA" to NaN
        )

        # Normalise column names: strip whitespace, lowercase, spaces→underscore
        df.columns = [
            col.strip().lower().replace(" ", "_").replace("-", "_")
            for col in df.columns
        ]

        self._logger.debug(
            "CSV loaded.",
            extra={"rows": len(df), "columns": list(df.columns)},
        )
        return df

    def _validate_columns(self, df: pd.DataFrame, filepath: Path) -> None:
        """Assert all required columns are present."""
        present = set(df.columns)
        missing = _REQUIRED_COLUMNS - present
        if missing:
            raise ValueError(
                f"ERP CSV '{filepath.name}' is missing required columns: "
                f"{sorted(missing)}. "
                f"Found: {sorted(present)}."
            )

    def _process_row(
        self,
        row: pd.Series,
        filepath: str,
        row_idx: int,
    ) -> list[GraphTriple]:
        """
        Convert one CSV row into one or more GraphTriples.

        Fails fast with a ValueError if core fields are blank/invalid.
        Optional fields silently produce no extra triples when absent.
        """
        buyer_id    = self._clean_str(row, "buyer_id")
        buyer_name  = self._clean_str(row, "buyer_name")
        supplier_id = self._clean_str(row, "supplier_id")
        supplier_name = self._clean_str(row, "supplier_name")

        if not buyer_name:
            raise ValueError("buyer_name is blank.")
        if not supplier_name:
            raise ValueError("supplier_name is blank.")

        provenance = self._provenance(file=filepath, row=row_idx)

        # --- Node references ---
        buyer_node = self._node(
            label=NodeLabel.COMPANY,
            name=buyer_name,
            extra={"external_id": buyer_id},
        )

        # Build supplier extra properties from optional columns
        supplier_extra: dict = {"external_id": supplier_id}
        country = self._clean_str(row, "supplier_country")
        lat     = self._clean_float(row, "supplier_lat")
        lon     = self._clean_float(row, "supplier_lon")

        if country:
            supplier_extra["country"] = country
        if lat is not None:
            supplier_extra["latitude"] = lat
        if lon is not None:
            supplier_extra["longitude"] = lon

        supplier_node = self._node(
            label=NodeLabel.SUPPLIER,
            name=supplier_name,
            extra=supplier_extra,
            entity_id=self._node_id(NodeLabel.SUPPLIER, supplier_name),
        )

        triples: list[GraphTriple] = []

        # --- Triple 1: Company -[:PURCHASES]-> Supplier ---
        purchase_props: dict = {
            "invoice_id":       self._clean_str(row, "invoice_id"),
            "invoice_date":     self._clean_str(row, "invoice_date"),
            "commodity":        self._clean_str(row, "commodity_category"),
            "volume_usd":       self._clean_float(row, "total_value_usd"),
            "invoice_qty":      self._clean_float(row, "invoice_qty"),
            "unit_of_measure":  self._clean_str(row, "unit_of_measure"),
        }
        triples.append(
            self._triple(
                subject=buyer_node,
                relationship=RelationshipType.HAS_SUPPLIER,
                obj=supplier_node,
                properties=purchase_props,
                provenance=provenance,
            )
        )

        # --- Triple 2: Supplier -[:LOCATED_IN]-> Region (when country present) ---
        if country:
            region_node = self._node(
                label=NodeLabel.REGION,
                name=country,
            )
            triples.append(
                self._triple(
                    subject=supplier_node,
                    relationship=RelationshipType.LOCATED_IN,
                    obj=region_node,
                    provenance=provenance,
                )
            )

        # --- Triple 3: Supplier -[:OPERATES]-> Facility (when coordinates present) ---
        delivery = self._clean_str(row, "delivery_location")
        if delivery and lat is not None and lon is not None:
            facility_extra = {
                "latitude":  lat,
                "longitude": lon,
                "country":   country,
            }
            facility_node = self._node(
                label=NodeLabel.FACILITY,
                name=delivery,
                extra=facility_extra,
            )
            triples.append(
                self._triple(
                    subject=supplier_node,
                    relationship=RelationshipType.OPERATES,
                    obj=facility_node,
                    provenance=provenance,
                )
            )

        return triples

    # ------------------------------------------------------------------
    # Value extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_str(row: pd.Series, col: str) -> str:
        """
        Return stripped string value, or empty string if column absent/blank.
        Never returns None or raises for missing optional columns.
        """
        raw = row.get(col, "")
        if pd.isna(raw) or raw is None:
            return ""
        return str(raw).strip()

    @staticmethod
    def _clean_float(row: pd.Series, col: str) -> Optional[float]:
        """
        Parse a float from the row, returning None for blank/non-numeric values.
        Never raises.
        """
        raw = row.get(col, "")
        if pd.isna(raw) or str(raw).strip() == "":
            return None
        try:
            value = float(str(raw).replace(",", "").strip())
            return None if pd.isna(value) else value
        except (ValueError, TypeError):
            return None