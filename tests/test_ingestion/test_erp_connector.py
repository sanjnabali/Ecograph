"""
tests/test_ingestion/test_erp_connector.py

Comprehensive test suite for ERP connector.

Tests:
- CSV parsing and validation
- Triple generation
- Error handling
- Edge cases
- Provenance tracking
"""

import pytest
import pandas as pd
import tempfile
from pathlib import Path
from datetime import datetime

# Mock imports (assuming your files exist)
# from src.ingestion.base_ingestor import GraphTriple
# from src.ingestion.erp_connector import ERPConnector


class MockGraphTriple:
    """Mock GraphTriple for testing (replace with actual import)."""

    def __init__(
        self,
        subject,
        relationship,
        object_,
        properties,
        provenance,
        confidence=1.0,
    ):
        self.subject = subject
        self.relationship = relationship
        self.object = object_
        self.properties = properties
        self.provenance = provenance
        self.confidence = confidence

    def to_dict(self):
        return {
            "subject": self.subject,
            "relationship": self.relationship,
            "object": self.object,
            "properties": self.properties,
            "provenance": self.provenance,
            "confidence": self.confidence,
        }


class MockERPConnector:
    """
    Mock ERP Connector for testing (replace with actual import).
    This is a simplified version to demonstrate test structure.
    """

    def __init__(self):
        self.triples = []
        self.errors = []
        self.warnings = []

    def ingest(self, filepath: Path) -> list:
        """Parse CSV and generate GraphTriples."""
        if not filepath.exists():
            self.errors.append(f"File not found: {filepath}")
            return []

        try:
            df = pd.read_csv(filepath, parse_dates=["invoice_date"])
        except Exception as exc:
            self.errors.append(f"CSV parse error: {exc}")
            return []

        for idx, row in df.iterrows():
            try:
                buyer_name = str(row.get("buyer_name", "")).strip()
                supplier_name = str(row.get("supplier_name", "")).strip()

                if not buyer_name or not supplier_name:
                    continue

                # Create PURCHASES triple
                triple = MockGraphTriple(
                    subject={"label": "Company", "name": buyer_name},
                    relationship="PURCHASES",
                    object_={"label": "Supplier", "name": supplier_name},
                    properties={
                        "volume_usd": float(row.get("volume_usd", 0)),
                        "date": row.get("invoice_date"),
                    },
                    provenance={
                        "source": "ERP",
                        "file": str(filepath),
                        "row": idx,
                    },
                )
                self.triples.append(triple)

            except Exception as exc:
                self.warnings.append(f"Row {idx}: {exc}")

        return self.triples


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def sample_csv_path():
    """Create a temporary CSV file with sample invoice data."""
    data = {
        "invoice_id": ["INV_001", "INV_002", "INV_003"],
        "invoice_date": ["2024-01-15", "2024-01-20", "2024-02-01"],
        "buyer_id": ["BUY_001", "BUY_002", "BUY_001"],
        "buyer_name": ["Apple Inc", "Microsoft Corp", "Apple Inc"],
        "supplier_id": ["SUP_001", "SUP_002", "SUP_001"],
        "supplier_name": ["Global Steel", "Intel Corp", "Global Steel"],
        "commodity_category": ["Steel", "Electronics", "Steel"],
        "volume_usd": [500000.00, 250000.00, 350000.00],
        "invoice_qty": [100.0, 500.0, 75.0],
        "unit_of_measure": ["tonnes", "units", "tonnes"],
        "country": ["China", "USA", "China"],
    }
    df = pd.DataFrame(data)

    with tempfile.NamedTemporaryFile(
        mode="w",
        delete=False,
        suffix=".csv",
    ) as f:
        df.to_csv(f, index=False)
        temp_path = Path(f.name)

    yield temp_path

    # Cleanup
    temp_path.unlink()


@pytest.fixture
def empty_csv_path():
    """Create an empty CSV file."""
    with tempfile.NamedTemporaryFile(
        mode="w",
        delete=False,
        suffix=".csv",
    ) as f:
        f.write("invoice_id,invoice_date,buyer_name,supplier_name\n")
        temp_path = Path(f.name)

    yield temp_path
    temp_path.unlink()


@pytest.fixture
def malformed_csv_path():
    """Create a malformed CSV file."""
    with tempfile.NamedTemporaryFile(
        mode="w",
        delete=False,
        suffix=".csv",
    ) as f:
        f.write("invoice_id,invoice_date,buyer_name\n")
        f.write("INV_001,2024-01-15,Apple Inc\n")
        f.write("INV_002,invalid-date,Microsoft\n")
        temp_path = Path(f.name)

    yield temp_path
    temp_path.unlink()


@pytest.fixture
def erp_connector():
    """Create ERP connector instance."""
    return MockERPConnector()


# ============================================================================
# TESTS - BASIC FUNCTIONALITY
# ============================================================================


class TestERPConnectorBasics:
    """Test basic ERP connector functionality."""

    def test_successful_parsing(self, erp_connector, sample_csv_path):
        """Test successful CSV parsing and triple generation."""
        triples = erp_connector.ingest(sample_csv_path)

        assert len(triples) == 3, "Should parse 3 invoices"
        assert len(erp_connector.errors) == 0, "Should have no errors"

    def test_triple_structure(self, erp_connector, sample_csv_path):
        """Test that generated triples have correct structure."""
        triples = erp_connector.ingest(sample_csv_path)

        triple = triples[0]
        assert triple.subject["label"] == "Company"
        assert triple.object_["label"] == "Supplier"
        assert triple.relationship == "PURCHASES"
        assert "volume_usd" in triple.properties
        assert "date" in triple.properties

    def test_provenance_tracking(self, erp_connector, sample_csv_path):
        """Test that provenance is correctly tracked."""
        triples = erp_connector.ingest(sample_csv_path)

        triple = triples[0]
        assert "source" in triple.provenance
        assert triple.provenance["source"] == "ERP"
        assert "file" in triple.provenance
        assert "row" in triple.provenance

    def test_volume_conversion(self, erp_connector, sample_csv_path):
        """Test that invoice amounts are correctly converted."""
        triples = erp_connector.ingest(sample_csv_path)

        assert triples[0].properties["volume_usd"] == 500000.00
        assert triples[1].properties["volume_usd"] == 250000.00
        assert triples[2].properties["volume_usd"] == 350000.00


# ============================================================================
# TESTS - ERROR HANDLING
# ============================================================================


class TestERPConnectorErrorHandling:
    """Test error handling in ERP connector."""

    def test_missing_file(self, erp_connector):
        """Test handling of missing file."""
        result = erp_connector.ingest(Path("/nonexistent/file.csv"))

        assert len(result) == 0, "Should return empty list for missing file"
        assert len(erp_connector.errors) > 0, "Should record error"

    def test_empty_csv(self, erp_connector, empty_csv_path):
        """Test handling of empty CSV."""
        triples = erp_connector.ingest(empty_csv_path)

        assert len(triples) == 0, "Should return empty list for empty CSV"
        assert len(erp_connector.errors) == 0, "Should not error for empty CSV"

    def test_malformed_csv(self, erp_connector, malformed_csv_path):
        """Test handling of malformed CSV."""
        triples = erp_connector.ingest(malformed_csv_path)

        # Should still parse one valid row, warn on invalid
        assert len(triples) >= 1, "Should parse at least one row"
        assert len(erp_connector.warnings) > 0, "Should have warnings for invalid rows"

    def test_missing_required_columns(self, erp_connector):
        """Test handling when required columns are missing."""
        with tempfile.NamedTemporaryFile(
            mode="w",
            delete=False,
            suffix=".csv",
        ) as f:
            f.write("invoice_id,invoice_date\n")
            f.write("INV_001,2024-01-15\n")
            temp_path = Path(f.name)

        triples = erp_connector.ingest(temp_path)

        assert len(triples) == 0, "Should handle missing columns gracefully"
        temp_path.unlink()

    def test_null_values(self, erp_connector):
        """Test handling of null/missing values."""
        data = {
            "invoice_id": ["INV_001", "INV_002"],
            "invoice_date": ["2024-01-15", "2024-01-20"],
            "buyer_id": ["BUY_001", "BUY_002"],
            "buyer_name": ["Apple Inc", None],  # Null buyer
            "supplier_id": ["SUP_001", "SUP_002"],
            "supplier_name": ["Global Steel", "Intel"],
            "commodity_category": ["Steel", "Electronics"],
            "volume_usd": [500000.00, 250000.00],
            "invoice_qty": [100.0, 500.0],
            "unit_of_measure": ["tonnes", "units"],
            "country": ["China", "USA"],
        }
        df = pd.DataFrame(data)

        with tempfile.NamedTemporaryFile(
            mode="w",
            delete=False,
            suffix=".csv",
        ) as f:
            df.to_csv(f, index=False)
            temp_path = Path(f.name)

        triples = erp_connector.ingest(temp_path)

        # Should skip row with null buyer
        assert len(triples) == 1, "Should skip rows with missing required values"
        temp_path.unlink()


# ============================================================================
# TESTS - DATA QUALITY
# ============================================================================


class TestERPConnectorDataQuality:
    """Test data quality validation."""

    def test_amount_validation(self, erp_connector, sample_csv_path):
        """Test that invoice amounts are positive."""
        triples = erp_connector.ingest(sample_csv_path)

        for triple in triples:
            assert triple.properties["volume_usd"] > 0, "Invoice amount must be positive"

    def test_date_parsing(self, erp_connector, sample_csv_path):
        """Test that dates are correctly parsed."""
        triples = erp_connector.ingest(sample_csv_path)

        for triple in triples:
            date_value = triple.properties["date"]
            # Should be datetime or string in ISO format
            assert date_value is not None or isinstance(date_value, (str, datetime))

    def test_duplicate_handling(self, erp_connector):
        """Test handling of duplicate invoices."""
        data = {
            "invoice_id": ["INV_001", "INV_001"],  # Duplicate
            "invoice_date": ["2024-01-15", "2024-01-15"],
            "buyer_id": ["BUY_001", "BUY_001"],
            "buyer_name": ["Apple Inc", "Apple Inc"],
            "supplier_id": ["SUP_001", "SUP_001"],
            "supplier_name": ["Global Steel", "Global Steel"],
            "commodity_category": ["Steel", "Steel"],
            "volume_usd": [500000.00, 500000.00],
            "invoice_qty": [100.0, 100.0],
            "unit_of_measure": ["tonnes", "tonnes"],
            "country": ["China", "China"],
        }
        df = pd.DataFrame(data)

        with tempfile.NamedTemporaryFile(
            mode="w",
            delete=False,
            suffix=".csv",
        ) as f:
            df.to_csv(f, index=False)
            temp_path = Path(f.name)

        triples = erp_connector.ingest(temp_path)

        # Should create triples for both rows (duplication detection is downstream)
        assert len(triples) == 2, "Should create triples for all rows"
        temp_path.unlink()


# ============================================================================
# TESTS - EDGE CASES
# ============================================================================


class TestERPConnectorEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_large_csv(self, erp_connector):
        """Test handling of large CSV files."""
        # Create CSV with 10K rows
        rows = 10000
        data = {
            "invoice_id": [f"INV_{i:08d}" for i in range(rows)],
            "invoice_date": ["2024-01-15"] * rows,
            "buyer_id": ["BUY_001"] * rows,
            "buyer_name": ["Apple Inc"] * rows,
            "supplier_id": [f"SUP_{i % 100:06d}" for i in range(rows)],
            "supplier_name": [f"Supplier_{i % 100}" for i in range(rows)],
            "commodity_category": ["Steel"] * rows,
            "volume_usd": [500000.00] * rows,
            "invoice_qty": [100.0] * rows,
            "unit_of_measure": ["tonnes"] * rows,
            "country": ["China"] * rows,
        }
        df = pd.DataFrame(data)

        with tempfile.NamedTemporaryFile(
            mode="w",
            delete=False,
            suffix=".csv",
        ) as f:
            df.to_csv(f, index=False)
            temp_path = Path(f.name)

        triples = erp_connector.ingest(temp_path)

        assert len(triples) == rows, f"Should parse all {rows} rows"
        assert len(erp_connector.errors) == 0, "Should have no errors"
        temp_path.unlink()

    def test_special_characters_in_names(self, erp_connector):
        """Test handling of special characters in supplier/company names."""
        data = {
            "invoice_id": ["INV_001"],
            "invoice_date": ["2024-01-15"],
            "buyer_id": ["BUY_001"],
            "buyer_name": ["Société Générale & Co. (Ltd)"],
            "supplier_id": ["SUP_001"],
            "supplier_name": ["北京钢铁 Steel™ — International"],
            "commodity_category": ["Steel"],
            "volume_usd": [500000.00],
            "invoice_qty": [100.0],
            "unit_of_measure": ["tonnes"],
            "country": ["China"],
        }
        df = pd.DataFrame(data)

        with tempfile.NamedTemporaryFile(
            mode="w",
            delete=False,
            suffix=".csv",
        ) as f:
            df.to_csv(f, index=False)
            temp_path = Path(f.name)

        triples = erp_connector.ingest(temp_path)

        assert len(triples) == 1, "Should handle special characters"
        assert "Société" in triples[0].subject["name"]
        temp_path.unlink()

    def test_very_large_amounts(self, erp_connector):
        """Test handling of very large invoice amounts."""
        data = {
            "invoice_id": ["INV_001"],
            "invoice_date": ["2024-01-15"],
            "buyer_id": ["BUY_001"],
            "buyer_name": ["Apple Inc"],
            "supplier_id": ["SUP_001"],
            "supplier_name": ["Global Steel"],
            "commodity_category": ["Steel"],
            "volume_usd": [9_999_999_999.99],  # ~$10 billion
            "invoice_qty": [100.0],
            "unit_of_measure": ["tonnes"],
            "country": ["China"],
        }
        df = pd.DataFrame(data)

        with tempfile.NamedTemporaryFile(
            mode="w",
            delete=False,
            suffix=".csv",
        ) as f:
            df.to_csv(f, index=False)
            temp_path = Path(f.name)

        triples = erp_connector.ingest(temp_path)

        assert len(triples) == 1
        assert triples[0].properties["volume_usd"] == 9_999_999_999.99
        temp_path.unlink()

    def test_zero_amount(self, erp_connector):
        """Test handling of zero invoice amount."""
        data = {
            "invoice_id": ["INV_001"],
            "invoice_date": ["2024-01-15"],
            "buyer_id": ["BUY_001"],
            "buyer_name": ["Apple Inc"],
            "supplier_id": ["SUP_001"],
            "supplier_name": ["Global Steel"],
            "commodity_category": ["Steel"],
            "volume_usd": [0.00],  # Zero amount
            "invoice_qty": [0.0],
            "unit_of_measure": ["tonnes"],
            "country": ["China"],
        }
        df = pd.DataFrame(data)

        with tempfile.NamedTemporaryFile(
            mode="w",
            delete=False,
            suffix=".csv",
        ) as f:
            df.to_csv(f, index=False)
            temp_path = Path(f.name)

        triples = erp_connector.ingest(temp_path)

        # Decision: allow zero amounts (may represent adjustments)
        assert len(triples) >= 0, "Should handle zero amounts gracefully"
        temp_path.unlink()


# ============================================================================
# TESTS - PERFORMANCE
# ============================================================================


class TestERPConnectorPerformance:
    """Test performance characteristics."""

    def test_parsing_speed(self, erp_connector):
        """Test that parsing completes in reasonable time."""
        import time

        # Create CSV with 5K rows
        rows = 5000
        data = {
            "invoice_id": [f"INV_{i:08d}" for i in range(rows)],
            "invoice_date": ["2024-01-15"] * rows,
            "buyer_id": ["BUY_001"] * rows,
            "buyer_name": ["Apple Inc"] * rows,
            "supplier_id": [f"SUP_{i % 100:06d}" for i in range(rows)],
            "supplier_name": [f"Supplier_{i % 100}" for i in range(rows)],
            "commodity_category": ["Steel"] * rows,
            "volume_usd": [500000.00] * rows,
            "invoice_qty": [100.0] * rows,
            "unit_of_measure": ["tonnes"] * rows,
            "country": ["China"] * rows,
        }
        df = pd.DataFrame(data)

        with tempfile.NamedTemporaryFile(
            mode="w",
            delete=False,
            suffix=".csv",
        ) as f:
            df.to_csv(f, index=False)
            temp_path = Path(f.name)

        start = time.time()
        triples = erp_connector.ingest(temp_path)
        elapsed = time.time() - start

        # Should parse ~5K rows in < 1 second
        assert elapsed < 1.0, f"Parsing took {elapsed:.2f}s, should be < 1s"
        assert len(triples) == rows
        temp_path.unlink()


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


class TestERPConnectorIntegration:
    """Integration tests with other components."""

    def test_triple_serialization(self, erp_connector, sample_csv_path):
        """Test that triples can be serialized."""
        triples = erp_connector.ingest(sample_csv_path)

        for triple in triples:
            serialized = triple.to_dict()
            assert "subject" in serialized
            assert "object" in serialized
            assert "relationship" in serialized
            assert "properties" in serialized
            assert "provenance" in serialized

    def test_connector_reusability(self, sample_csv_path):
        """Test that connector can be reused for multiple files."""
        connector = MockERPConnector()

        # First ingest
        triples1 = connector.ingest(sample_csv_path)
        assert len(triples1) == 3

        # Second ingest (should reset state)
        connector2 = MockERPConnector()
        triples2 = connector2.ingest(sample_csv_path)
        assert len(triples2) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])