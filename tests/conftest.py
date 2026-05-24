"""
tests/conftest.py

Shared pytest configuration and fixtures for all tests.

Provides:
- Mock Neo4j driver
- Mock LLM clients
- Temporary file handling
- Database fixtures
- Configuration fixtures
"""

import pytest
import logging
from pathlib import Path
from typing import Generator, Any, Dict
from unittest.mock import Mock, MagicMock, patch
import tempfile
import pandas as pd

logger = logging.getLogger(__name__)


# ============================================================================
# PYTEST CONFIGURATION
# ============================================================================


def pytest_configure(config):
    """Configure pytest."""
    # Suppress verbose logging during tests
    logging.getLogger("neo4j").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)


def pytest_collection_modifyitems(config, items):
    """Add markers to tests based on their names."""
    for item in items:
        if "integration" in item.nodeid:
            item.add_marker(pytest.mark.integration)
        if "slow" in item.nodeid:
            item.add_marker(pytest.mark.slow)
        if "external" in item.nodeid:
            item.add_marker(pytest.mark.external)


# ============================================================================
# MOCK DRIVERS & CLIENTS
# ============================================================================


@pytest.fixture
def mock_neo4j_driver() -> Mock:
    """
    Create a mock Neo4j driver for testing.
    
    Mocks:
    - Session creation
    - Query execution
    - Transaction handling
    """
    driver = MagicMock()

    # Mock session context manager
    session = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=None)

    # Mock query results
    result = MagicMock()
    result.data.return_value = [{"n": {"name": "test"}}]
    result.single.return_value = {"count": 1}
    session.run.return_value = result

    # Mock close
    driver.close = MagicMock()

    return driver


@pytest.fixture
def mock_gemini_client() -> Mock:
    """
    Create a mock Gemini LLM client for testing.
    
    Mocks:
    - Content generation
    - Embedding API
    - Token counting
    """
    client = MagicMock()

    # Mock generate_content
    response = MagicMock()
    response.text = (
        '{'
        '"subject_name": "Apple Inc",'
        '"relationship": "REPORTS_EMISSION",'
        '"object_name": "CO2 Emissions",'
        '"confidence": 0.95'
        '}'
    )
    client.generate_content.return_value = response

    # Mock embeddings
    embedding_response = MagicMock()
    embedding_response.embedding = [0.1, 0.2, 0.3] * 128  # 384 dims
    client.embed_content.return_value = embedding_response

    return client


@pytest.fixture
def mock_qdrant_client() -> Mock:
    """
    Create a mock Qdrant vector store client for testing.
    
    Mocks:
    - Point insertion
    - Search
    - Collection operations
    """
    client = MagicMock()

    # Mock search
    search_result = [
        MagicMock(
            id=1,
            payload={
                "text": "Sample ESG text",
                "supplier_id": "SUP_001",
                "page": 1,
            },
            score=0.95,
        )
    ]
    client.search.return_value = search_result

    # Mock upsert
    client.upsert.return_value = None

    # Mock health check
    client.get_collections.return_value = MagicMock()

    return client


@pytest.fixture
def mock_splink_linker() -> Mock:
    """
    Create a mock Splink linker for entity resolution testing.
    
    Mocks:
    - Model training
    - Predictions
    - Comparisons
    """
    linker = MagicMock()

    # Mock predictions
    predictions = MagicMock()
    predictions_df = pd.DataFrame({
        "index_l": [0, 1],
        "index_r": [1, 2],
        "match_probability": [0.92, 0.87],
    })
    predictions.as_pandas.return_value = predictions_df
    linker.predict.return_value = predictions

    # Mock training
    linker.estimate_parameters_using_expectation_maximisation.return_value = None

    return linker


@pytest.fixture
def mock_torch_model() -> Mock:
    """
    Create a mock PyTorch model for CNN testing.
    
    Mocks:
    - Forward pass
    - Parameter access
    - Device management
    """
    model = MagicMock()

    # Mock forward pass
    import torch

    batch_size = 4
    output = torch.zeros(batch_size, 1, 256, 256)  # Segmentation output
    model.return_value = output

    # Mock training mode
    model.train.return_value = model
    model.eval.return_value = model

    # Mock parameters
    model.parameters.return_value = [MagicMock()]

    # Mock to (device)
    model.to.return_value = model

    return model


# ============================================================================
# TEMPORARY FILES & DIRECTORIES
# ============================================================================


@pytest.fixture
def temp_csv_file() -> Generator[Path, None, None]:
    """Create temporary CSV file for testing."""
    with tempfile.NamedTemporaryFile(
        mode="w",
        delete=False,
        suffix=".csv",
    ) as f:
        temp_path = Path(f.name)

    yield temp_path

    # Cleanup
    if temp_path.exists():
        temp_path.unlink()


@pytest.fixture
def temp_netcdf_file() -> Generator[Path, None, None]:
    """Create temporary NetCDF file for testing."""
    with tempfile.NamedTemporaryFile(
        delete=False,
        suffix=".nc",
    ) as f:
        temp_path = Path(f.name)

    yield temp_path

    # Cleanup
    if temp_path.exists():
        temp_path.unlink()


@pytest.fixture
def temp_pdf_file() -> Generator[Path, None, None]:
    """Create temporary PDF file for testing."""
    with tempfile.NamedTemporaryFile(
        delete=False,
        suffix=".pdf",
    ) as f:
        temp_path = Path(f.name)

    yield temp_path

    # Cleanup
    if temp_path.exists():
        temp_path.unlink()


@pytest.fixture
def temp_directory() -> Generator[Path, None, None]:
    """Create temporary directory for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


# ============================================================================
# CONFIGURATION FIXTURES
# ============================================================================


@pytest.fixture
def mock_settings() -> Dict[str, Any]:
    """
    Create mock settings dictionary for testing.
    
    Provides:
    - API keys (mocked)
    - Database URLs
    - Model paths
    """
    return {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USERNAME": "neo4j",
        "NEO4J_PASSWORD": "test_password",
        "GEMINI_API_KEY": "test_api_key_12345",
        "GEMINI_MODEL": "gemini-1.5-flash",
        "QDRANT_URL": "http://localhost:6333",
        "QDRANT_API_KEY": "test_qdrant_key",
        "LOG_LEVEL": "DEBUG",
        "PDF_CHUNK_SIZE": 8000,
        "SPLINK_MATCH_THRESHOLD": 0.85,
        "CNN_MODEL_PATH": "/tmp/test_model.onnx",
    }


@pytest.fixture
def mock_env_vars(mock_settings, monkeypatch):
    """
    Apply mock settings to environment variables.
    
    Usage:
        def test_something(mock_env_vars):
            # All env vars are now mocked
            pass
    """
    for key, value in mock_settings.items():
        monkeypatch.setenv(key, str(value))
    return mock_settings


# ============================================================================
# DATA FIXTURES
# ============================================================================


@pytest.fixture
def sample_invoice_data() -> pd.DataFrame:
    """Create sample invoice DataFrame for testing."""
    return pd.DataFrame({
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
    })


@pytest.fixture
def sample_entities_data() -> pd.DataFrame:
    """Create sample entity DataFrame for ER testing."""
    return pd.DataFrame({
        "name": [
            "Global Steel",
            "GlobalSteel_01",
            "GSC Ltd",
            "Apple Inc",
            "Apple",
        ],
        "country": ["China", "China", "China", "USA", "USA"],
        "latitude": [31.2, 31.21, None, None, None],
        "longitude": [121.4, 121.41, None, None, None],
        "tax_id": ["CN123456", "CN123456", None, "US789012", None],
        "source": ["ERP", "SATELLITE", "ESG", "ERP", "ESG"],
    })


@pytest.fixture
def sample_facility_data() -> pd.DataFrame:
    """Create sample facility DataFrame for satellite testing."""
    return pd.DataFrame({
        "name": [
            "Global Steel Factory 01",
            "Intel Fab Arizona",
            "Samsung Semiconductor",
        ],
        "latitude": [31.2, 32.4, 37.5],
        "longitude": [121.4, -110.5, 127.0],
        "entity_id": ["FAC_001", "FAC_002", "FAC_003"],
        "bbox_km": [30.0, 30.0, 30.0],
    })


@pytest.fixture
def sample_triple_data() -> list:
    """Create sample GraphTriple objects for testing."""
    return [
        {
            "subject": {"label": "Company", "name": "Apple Inc"},
            "relationship": "PURCHASES",
            "object": {"label": "Supplier", "name": "Global Steel"},
            "properties": {
                "volume_usd": 500000.0,
                "date": "2024-01-15",
            },
            "provenance": {
                "source": "ERP",
                "file": "invoices.csv",
                "row": 0,
            },
            "confidence": 1.0,
        },
        {
            "subject": {"label": "Company", "name": "Apple Inc"},
            "relationship": "REPORTS_EMISSION",
            "object": {"label": "EmissionMetric", "name": "Scope 3 Emissions"},
            "properties": {
                "value": 250000.0,
                "unit": "tCO2e",
                "year": 2024,
            },
            "provenance": {
                "source": "ESG_PDF",
                "file": "Apple_Report_2024.pdf",
                "page": 42,
            },
            "confidence": 0.87,
        },
    ]


# ============================================================================
# CONTEXT MANAGERS & UTILITIES
# ============================================================================


@pytest.fixture
def capture_logs(caplog):
    """
    Fixture to capture and assert on log messages.
    
    Usage:
        def test_something(capture_logs):
            # Your code that logs
            assert "expected message" in capture_logs.text
    """
    return caplog


@pytest.fixture
def assert_performance(request):
    """
    Fixture to assert execution time.
    
    Usage:
        def test_performance(assert_performance):
            with assert_performance(max_seconds=1.0):
                # Code to measure
                pass
    """
    from contextlib import contextmanager
    import time

    @contextmanager
    def _assert_performance(max_seconds: float):
        start = time.time()
        yield
        elapsed = time.time() - start
        assert (
            elapsed < max_seconds
        ), f"Execution took {elapsed:.2f}s, expected < {max_seconds}s"

    return _assert_performance


# ============================================================================
# CLEANUP & TEARDOWN
# ============================================================================


@pytest.fixture(autouse=True)
def cleanup_after_test():
    """
    Automatically cleanup after each test.
    
    Runs after every test to ensure clean state.
    """
    yield
    # Cleanup code here if needed
    logger.debug("Test cleanup completed")


# ============================================================================
# MARKERS
# ============================================================================


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests (deselect with '-m \"not integration\"')",
    )
    config.addinivalue_line(
        "markers",
        "slow: marks tests as slow (deselect with '-m \"not slow\"')",
    )
    config.addinivalue_line(
        "markers",
        "external: marks tests requiring external services",
    )
    config.addinivalue_line(
        "markers",
        "gpu: marks tests requiring GPU",
    )