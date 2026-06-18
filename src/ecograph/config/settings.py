"""
src/ecograph/config/settings.py

Single source of truth for all configuration.

Design decisions:
- All values are read once at import time — no repeated os.getenv() calls
  scattered across modules. One module owns environment access.
- Typed class attributes (not a dict) so IDE autocomplete works and typos
  are caught at definition time, not at runtime.
- validate() is called explicitly — not at import time — so unit tests can
  import Settings without a real .env present, providing their own env vars
  via monkeypatch or os.environ overrides before calling validate().
- Paths are always pathlib.Path, never strings, so consumers can safely
  do path / "subdir" without worrying about OS separators.
- All numeric env vars have explicit int()/float() casts with sensible
  defaults; missing vars produce the default, not a crash on first use.
"""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Locate project root (two levels up from this file: config/ -> ecograph/ -> src/ -> ecograph/)
# Adjust if the package layout changes.
# ---------------------------------------------------------------------------
_THIS_FILE = Path(__file__).resolve()
# src/ecograph/config/settings.py  -> parent x3 = project root
PROJECT_ROOT: Path = _THIS_FILE.parent.parent.parent.parent
_ENV_FILE: Path = PROJECT_ROOT / ".env"

# Load .env before reading any os.getenv — silent if file absent (CI/CD case)
load_dotenv(_ENV_FILE, override=False)


# ---------------------------------------------------------------------------
# Internal helpers — keep them private so nothing outside settings.py
# reaches into os.environ directly.
# ---------------------------------------------------------------------------

def _str(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _int(key: str, default: int = 0) -> int:
    raw = os.getenv(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(
            f"Environment variable '{key}' must be an integer; got '{raw}'."
        ) from exc


def _float(key: str, default: float = 0.0) -> float:
    raw = os.getenv(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(
            f"Environment variable '{key}' must be a float; got '{raw}'."
        ) from exc


def _bool(key: str, default: bool = False) -> bool:
    raw = os.getenv(key, "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    raise ValueError(
        f"Environment variable '{key}' must be a boolean value "
        f"(true/false/1/0/yes/no); got '{raw}'."
    )


def _path(key: str, default: Path) -> Path:
    raw = os.getenv(key, "").strip()
    return Path(raw) if raw else default


# ---------------------------------------------------------------------------
# Directory layout — all relative to project root.
# We declare these first so later settings can reference them.
# ---------------------------------------------------------------------------

DATA_DIR:           Path = PROJECT_ROOT / "data"
RAW_DATA_DIR:       Path = DATA_DIR / "raw"
PROCESSED_DATA_DIR: Path = DATA_DIR / "processed"
SYNTHETIC_DATA_DIR: Path = DATA_DIR / "synthetic"
LOGS_DIR:           Path = PROJECT_ROOT / "logs"
WEIGHTS_DIR:        Path = PROJECT_ROOT / "weights"
DOCS_DIR:           Path = PROJECT_ROOT / "docs"

# Ensure writable directories exist at import time — read-only raw/ is not
# created here; it is populated by download scripts.
for _d in (PROCESSED_DATA_DIR, LOGS_DIR, WEIGHTS_DIR, DOCS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_FILE:   Path = _path("LOG_FILE", LOGS_DIR / "ecograph.log")
LOG_LEVEL:  str  = _str("LOG_LEVEL", "INFO").upper()
LOG_FORMAT: str  = _str("LOG_FORMAT", "json")   # "json" | "text"

# Validate log level is a real Python logging level
_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
if LOG_LEVEL not in _VALID_LOG_LEVELS:
    raise ValueError(
        f"LOG_LEVEL='{LOG_LEVEL}' is not valid. "
        f"Choose from: {sorted(_VALID_LOG_LEVELS)}"
    )


# ---------------------------------------------------------------------------
# Neo4j
# ---------------------------------------------------------------------------

NEO4J_URI:          str = _str("NEO4J_URI")
NEO4J_USERNAME:     str = _str("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD:     str = _str("NEO4J_PASSWORD")
NEO4J_DATABASE:     str = _str("NEO4J_DATABASE", "neo4j")
NEO4J_TIMEOUT:      int = _int("NEO4J_TIMEOUT", 30)       # seconds
NEO4J_MAX_POOL:     int = _int("NEO4J_MAX_POOL", 50)
NEO4J_QUERY_API:    str = _str("NEO4J_QUERY_API", "https")  # "bolt" or "http"


# ---------------------------------------------------------------------------
# Gemini / LLM
# ---------------------------------------------------------------------------

GROQ_API_KEY:       str   = _str("GROQ_API_KEY")
GROQ_MODEL:         str   = _str("GROQ_MODEL", "llama3.3-70B-versatile")
GROQ_TEMPERATURE:   float = _float("GROQ_TEMPERATURE", 0.1)
GROQ_MAX_TOKENS:    int   = _int("GROQ_MAX_TOKENS", 2048)
GROQ_API_TIMEOUT:   int   = _int("GROQ_API_TIMEOUT", 45)  # seconds per Groq request

# Free-tier rate limiting: 15 RPM / 1500 RPD
# RATE_LIMIT_DELAY is the minimum inter-request sleep in seconds.
RATE_LIMIT_DELAY: float = _float("RATE_LIMIT_DELAY", 3.0)
MAX_RETRIES:      int   = _int("MAX_RETRIES", 4)
RETRY_BACKOFF:    int   = _int("RETRY_BACKOFF", 5)   # seconds; doubles per attempt
GROQ_TOKENS_PER_MINUTE: int = _int("GROQ_TOKENS_PER_MINUTE", 6000)  # for rate limiting
GROQ_REQUESTS_PER_MINUTE: int = _int("GROQ_REQUESTS_PER_MINUTE", 30)  # for rate limiting
GROQ_REQUESTS_PER_DAY: int = _int("GROQ_REQUESTS_PER_DAY", 14400)  # for rate limiting


# ---------------------------------------------------------------------------
# Qdrant (vector store)
# ---------------------------------------------------------------------------

QDRANT_URL:        str           = _str("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY:    Optional[str] = _str("QDRANT_API_KEY") or None
QDRANT_COLLECTION: str           = _str("QDRANT_COLLECTION", "ecograph_embeddings")


# ---------------------------------------------------------------------------
# ESA Copernicus (satellite data)
# ---------------------------------------------------------------------------

COPERNICUS_USERNAME: Optional[str] = _str("COPERNICUS_USERNAME") or None
COPERNICUS_PASSWORD: Optional[str] = _str("COPERNICUS_PASSWORD") or None


# ---------------------------------------------------------------------------
# Raw data paths — downstream modules use these, never hard-code paths
# ---------------------------------------------------------------------------

ERP_INVOICES_CSV:       Path = RAW_DATA_DIR / "erp_invoices" / "synthetic_invoices.csv"
ESG_REPORTS_DIR:        Path = RAW_DATA_DIR / "esg_reports"
SATELLITE_DATA_DIR:     Path = RAW_DATA_DIR / "satellite" / "tropomi_monthly"
FACILITY_REFERENCE_CSV: Path = RAW_DATA_DIR / "facility_reference" / "global_power_plants.csv"
SUPPLY_HUB_CSV:         Path = RAW_DATA_DIR / "supply_chain" / "open_supply_hub_facilities.csv"
EMISSION_FACTORS_DIR:   Path = RAW_DATA_DIR / "emission_factors"
EPA_FACTORS_XLSX:       Path = EMISSION_FACTORS_DIR / "epa_emission_factors_2024.xlsx"
OWID_CO2_CSV:           Path = EMISSION_FACTORS_DIR / "owid_co2_data.csv"


# ---------------------------------------------------------------------------
# Processed data paths
# ---------------------------------------------------------------------------

NO2_GRIDS_DIR:              Path = PROCESSED_DATA_DIR / "satellite" / "no2_grids"
HOTSPOTS_DIR:               Path = PROCESSED_DATA_DIR / "satellite" / "hotspots"
FLUX_ESTIMATES_DIR:         Path = PROCESSED_DATA_DIR / "satellite" / "flux_estimates"
ESG_TRIPLES_DIR:            Path = PROCESSED_DATA_DIR / "esg_parsed"
ER_RAW_COMBINED:            Path = PROCESSED_DATA_DIR / "entity_resolution" / "raw_entities_combined.parquet"
ER_SPLINK_LABELS:           Path = PROCESSED_DATA_DIR / "entity_resolution" / "splink_training_labels.parquet"
ER_RESOLVED:                Path = PROCESSED_DATA_DIR / "entity_resolution" / "entities_resolved.parquet"
GRAPH_NODES_JSONL:          Path = PROCESSED_DATA_DIR / "graph_import" / "nodes.jsonl"
GRAPH_EDGES_JSONL:          Path = PROCESSED_DATA_DIR / "graph_import" / "edges.jsonl"
EPA_FACTORS_CLEAN_CSV:      Path = PROCESSED_DATA_DIR / "emission_factors" / "epa_factors_clean.csv"
GRID_INTENSITY_CSV:         Path = PROCESSED_DATA_DIR / "emission_factors" / "grid_intensity_by_country.csv"

# Ensure processed subdirectories exist
for _d in (
    NO2_GRIDS_DIR, HOTSPOTS_DIR, FLUX_ESTIMATES_DIR,
    ESG_TRIPLES_DIR,
    PROCESSED_DATA_DIR / "entity_resolution",
    PROCESSED_DATA_DIR / "graph_import",
    PROCESSED_DATA_DIR / "emission_factors",
):
    _d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# CNN / Computer Vision
# ---------------------------------------------------------------------------

CNN_MODEL_PATH:          Path  = WEIGHTS_DIR / "plume_detector_int8.onnx"
CNN_INPUT_SIZE:          int   = _int("CNN_INPUT_SIZE", 256)
CNN_CONFIDENCE_THRESHOLD: float = _float("CNN_CONFIDENCE_THRESHOLD", 0.50)
CNN_BATCH_SIZE:          int   = _int("CNN_BATCH_SIZE", 1)


# ---------------------------------------------------------------------------
# Ingestion pipeline
# ---------------------------------------------------------------------------

PDF_CHUNK_SIZE:              int   = _int("PDF_CHUNK_SIZE", 8000)    # characters
PDF_CHUNK_OVERLAP:           int   = _int("PDF_CHUNK_OVERLAP", 500)
MIN_EXTRACTION_CONFIDENCE:   float = _float("MIN_EXTRACTION_CONFIDENCE", 0.70)
ERP_BATCH_SIZE:              int   = _int("ERP_BATCH_SIZE", 1000)


# ---------------------------------------------------------------------------
# Entity resolution (Splink)
# ---------------------------------------------------------------------------

SPLINK_MATCH_THRESHOLD: float = _float("SPLINK_MATCH_THRESHOLD", 0.85)
SPLINK_EM_CONVERGENCE:  float = _float("SPLINK_EM_CONVERGENCE", 0.0001)
SPLINK_MAX_ITERATIONS:  int   = _int("SPLINK_MAX_ITERATIONS", 20)


# ---------------------------------------------------------------------------
# Satellite physics constants
# These are scientific constants — not user-configurable, but kept here so
# they appear in one place rather than buried in formulas.
# ---------------------------------------------------------------------------

NO2_TO_NOX_FACTOR:    float = 1.32     # standard NO2/NOx ratio for combustion
CO2_NOX_COAL:         float = 333.0    # tCO2 per tNOx for coal combustion
CO2_NOX_GAS:          float = 542.0    # tCO2 per tNOx for natural gas
CO2_NOX_OIL:          float = 358.0    # tCO2 per tNOx for oil combustion
NO2_QA_THRESHOLD:     float = 0.75     # TROPOMI quality flag minimum
DEFAULT_WIND_SPEED_MS: float = 5.0     # fallback when ERA5 unavailable


# ---------------------------------------------------------------------------
# API server
# ---------------------------------------------------------------------------

API_HOST:    str = _str("API_HOST", "0.0.0.0")
API_PORT:    int = _int("API_PORT", 8000)
CORS_ORIGINS: str = _str(
    "CORS_ORIGINS",
    "http://localhost:3000,http://localhost:3001,https://*.vercel.app",
)


# ---------------------------------------------------------------------------
# Validation — call this explicitly from main entry points
# ---------------------------------------------------------------------------

class MissingConfigError(Exception):
    """Raised when a required environment variable is absent."""


def validate() -> None:
    """
    Assert that all required credentials are present.

    Called from:
      - main.py before any pipeline stage
      - api/main.py inside the lifespan context
      - scripts/bootstrap_graph.py

    Not called at import time so that unit tests can import settings freely
    and inject their own values via os.environ or pytest monkeypatch before
    calling validate().

    Raises:
        MissingConfigError — lists every missing key at once rather than
        one per run so the developer fixes them all in one pass.
    """
    required: list[tuple[str, str]] = [
        ("GROQ_API_KEY", GROQ_API_KEY),
        ("NEO4J_URI",      NEO4J_URI),
        ("NEO4J_PASSWORD", NEO4J_PASSWORD),
    ]

    missing = [name for name, value in required if not value]

    if missing:
        raise MissingConfigError(
            f"Required environment variable(s) not set: {', '.join(missing)}. "
            f"Copy .env.example to .env and fill in the missing values."
        )


def validate_satellite() -> None:
    """
    Assert that Copernicus credentials are present.
    Called only by scripts that download satellite data.

    Raises:
        MissingConfigError
    """
    missing = []
    if not COPERNICUS_USERNAME:
        missing.append("COPERNICUS_USERNAME")
    if not COPERNICUS_PASSWORD:
        missing.append("COPERNICUS_PASSWORD")

    if missing:
        raise MissingConfigError(
            f"Copernicus credentials not set: {', '.join(missing)}. "
            f"Register at dataspace.copernicus.eu and add to .env."
        )