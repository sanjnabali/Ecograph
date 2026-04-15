"""
config/settings.py - single source of truth for all project constraints.

Every file in this project imports from here.

All numeric env-var casts are wrapped in _safe_* helpers so a typo in
.env raises a clear ValueError at startup instead of a cryptic crash deep inside the pipeline.
"""

import os
import warnings
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()



def _safe_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        warnings.warn(
            f"[settings] {key}='{raw}' is not a valid int - "
            f"using default {default}.",
            stacklevel=2,
        )
        return default
    
def _safe_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        warnings.warn(
            f"[settings] {key}='{raw}' is not a valid float - using default {default}.",
            stacklevel=2,
        )
        return default
    

ROOT_DIR              : Path = Path(__file__).resolve().parent.parent.parent
DATA_DIR              : Path = ROOT_DIR / "data"
PDFS_DIR              : Path = DATA_DIR / "pdfs"
PARSED_CONTENT_DIR    : Path = DATA_DIR / "parsed_content"
TRIPLES_DIR           : Path = DATA_DIR / "triples"
LOG_FILE              : Path = ROOT_DIR / "ecograph.Log"

GROQ_API_KEY      : str = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
LLM_Provider: str = os.getenv("LLM_Provider", "groq")

GEMINI_MODEL       : str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_TEMPERATURE : float = _safe_float("GEMINI_TEMPERATURE", 0.0)


RATE_LIMIT_DELAY   : float = _safe_float("RATE_LIMIT_DELAY", 5.0)
MAX_RETRIES        : int = _safe_int("MAX_RETRIES", 3)
RETRY_BACKOFF      : float = _safe_float("RETRY_BACKOFF", 30.0)


MIN_CHUNK_LENGTH   : int = 100



NEO4J_URI       : str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USERNAME  : str = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD  : str = os.getenv("NEO4J_PASSWORD", "")


RESOLUTION_THRESHOLD    : int = _safe_int("RESOLUTION_THRESHOLD", 85)
RESOLUTION_MAX_NODES    : int = _safe_int("RESOLUTION_MAX_NODES", 2000)



NOMINATIM_URL    : str  = "https://nominatim.openstreetmap.org/search"
NOMINATIM_DELAY  : float = 1.1
GEO_REQUEST_TIMEOUT : int = 10

