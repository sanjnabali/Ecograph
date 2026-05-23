"""
src/config/settings.py - Centralized configuration loader

Reads from .env file and provides typed settings for all modules.
Load order: environment variables → defaults → validation
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# --- Load .env ---
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT_DIR / ".env")

class Settings:
    """All configuration in one place."""
    
    # --- Project Paths ---
    PROJECT_ROOT: Path = ROOT_DIR
    DATA_DIR: Path = ROOT_DIR / "data"
    RAW_DATA_DIR: Path = DATA_DIR / "raw"
    PROCESSED_DATA_DIR: Path = DATA_DIR / "processed"
    SYNTHETIC_DATA_DIR: Path = DATA_DIR / "synthetic"
    LOGS_DIR: Path = ROOT_DIR / "logs"
    WEIGHTS_DIR: Path = ROOT_DIR / "weights"
    
    # Create directories if missing
    for d in [LOGS_DIR, WEIGHTS_DIR, PROCESSED_DATA_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    
    # --- Logging ---
    LOG_FILE: Path = LOGS_DIR / "ecograph_run.log"
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT: str = os.getenv("LOG_FORMAT", "json")  # json | text
    
    # --- Neo4j Configuration ---
    NEO4J_URI: str = os.getenv(
        "NEO4J_URI",
        "neo4j+s://demo.neo4jlabs.com",
    )
    NEO4J_USERNAME: str = os.getenv("NEO4J_USERNAME", "neo4j")
    NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "password")
    NEO4J_TIMEOUT: int = int(os.getenv("NEO4J_TIMEOUT", "30"))  # seconds
    
    # --- Gemini LLM Configuration ---
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    GEMINI_TEMPERATURE: float = float(os.getenv("GEMINI_TEMPERATURE", "0.7"))
    GEMINI_MAX_TOKENS: int = int(os.getenv("GEMINI_MAX_TOKENS", "2000"))
    
    # Rate limiting for free tier (15 req/min, 1500 req/day)
    RATE_LIMIT_DELAY: float = float(os.getenv("RATE_LIMIT_DELAY", "4.0"))  # seconds
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
    RETRY_BACKOFF: int = int(os.getenv("RETRY_BACKOFF", "2"))  # exponential backoff
    
    # --- Qdrant Vector Store ---
    QDRANT_URL: str = os.getenv("QDRANT_URL", "http://localhost:6333")
    QDRANT_API_KEY: Optional[str] = os.getenv("QDRANT_API_KEY")
    QDRANT_COLLECTION: str = os.getenv("QDRANT_COLLECTION", "ecograph_embeddings")
    
    # --- Satellite / ESA Copernicus ---
    COPERNICUS_USERNAME: Optional[str] = os.getenv("COPERNICUS_USERNAME")
    COPERNICUS_PASSWORD: Optional[str] = os.getenv("COPERNICUS_PASSWORD")
    
    # --- Data Paths ---
    ERP_INVOICES_CSV: Path = RAW_DATA_DIR / "erp_invoices" / "synthetic_invoices.csv"
    ESG_REPORTS_DIR: Path = RAW_DATA_DIR / "esg_reports"
    SATELLITE_DATA_DIR: Path = RAW_DATA_DIR / "satellite" / "tropomi_monthly"
    FACILITY_REFERENCE_CSV: Path = RAW_DATA_DIR / "facility_reference" / "global_power_plants.csv"
    SUPPLY_HUB_CSV: Path = RAW_DATA_DIR / "supply_chain" / "open_supply_hub_facilities.csv"
    EMISSION_FACTORS_DIR: Path = RAW_DATA_DIR / "emission_factors"
    
    # Processed outputs
    ENTITIES_RESOLVED_PARQUET: Path = PROCESSED_DATA_DIR / "entities_resolved.parquet"
    GRAPH_NODES_JSONL: Path = PROCESSED_DATA_DIR / "graph_nodes.jsonl"
    GRAPH_EDGES_JSONL: Path = PROCESSED_DATA_DIR / "graph_edges.jsonl"
    
    # --- Ingestion Settings ---
    PDF_CHUNK_SIZE: int = int(os.getenv("PDF_CHUNK_SIZE", "8000"))  # chars
    PDF_CHUNK_OVERLAP: int = int(os.getenv("PDF_CHUNK_OVERLAP", "500"))
    MIN_EXTRACTION_CONFIDENCE: float = float(os.getenv("MIN_EXTRACTION_CONFIDENCE", "0.70"))
    
    # --- Entity Resolution (Splink) ---
    SPLINK_MATCH_THRESHOLD: float = float(os.getenv("SPLINK_MATCH_THRESHOLD", "0.85"))
    SPLINK_EM_CONVERGENCE: float = float(os.getenv("SPLINK_EM_CONVERGENCE", "0.0001"))
    
    # --- Computer Vision ---
    CNN_MODEL_PATH: Path = WEIGHTS_DIR / "plume_detector_int8.onnx"
    CNN_INPUT_SIZE: int = int(os.getenv("CNN_INPUT_SIZE", "256"))
    CNN_CONFIDENCE_THRESHOLD: float = float(os.getenv("CNN_CONFIDENCE_THRESHOLD", "0.50"))
    
    # --- API Server ---
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))
    CORS_ORIGINS: str = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:3001,https://*.vercel.app"
    )
    
    # --- Streamlit ---
    STREAMLIT_PORT: int = int(os.getenv("STREAMLIT_PORT", "8501"))
    
    @classmethod
    def validate(cls) -> None:
        """
        Pre-flight check: ensure all critical env vars are set.
        Raises ValueError if anything is missing.
        """
        required_keys = [
            ("GEMINI_API_KEY", cls.GEMINI_API_KEY),
            ("NEO4J_URI", cls.NEO4J_URI),
            ("NEO4J_PASSWORD", cls.NEO4J_PASSWORD),
        ]
        
        missing = [key for key, val in required_keys if not val]
        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}. "
                f"Copy .env.example to .env and fill in your credentials."
            )

# Create singleton instance
settings = Settings()

# Export commonly used items at module level
LOG_FILE = settings.LOG_FILE
LOG_LEVEL = settings.LOG_LEVEL
NEO4J_URI = settings.NEO4J_URI
GEMINI_API_KEY = settings.GEMINI_API_KEY
GEMINI_MODEL = settings.GEMINI_MODEL
RATE_LIMIT_DELAY = settings.RATE_LIMIT_DELAY