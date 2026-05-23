"""
src/config/logger_config.py - Structured JSON logging configuration

Logs are written in JSON format for easy parsing and aggregation.
Supports both file and console output.
"""

import logging
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

class JSONFormatter(logging.Formatter):
    """Custom formatter that outputs JSON-structured logs."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields if provided
        if hasattr(record, "extra_fields"):
            log_data.update(record.extra_fields)
        
        return json.dumps(log_data, default=str)

class PlainFormatter(logging.Formatter):
    """Simple text formatter for readability."""
    
    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"[{timestamp}] [{record.levelname}] {record.name} "
            f"({record.funcName}:{record.lineno}): {record.getMessage()}"
        )

def setup_logging(
    log_file: Optional[Path] = None,
    log_format: str = "json",
    log_level: str = "INFO",
) -> None:
    """
    Configure structured logging for the entire application.
    
    Args:
        log_file: Path to write logs. If None, logs to console only.
        log_format: "json" or "text"
        log_level: DEBUG, INFO, WARNING, ERROR, CRITICAL
    """
    # Create root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    # Remove any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Choose formatter
    formatter = (
        JSONFormatter() if log_format.lower() == "json"
        else PlainFormatter()
    )
    
    # Console handler (always)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)  # Only INFO+ to console
    root_logger.addHandler(console_handler)
    
    # File handler (if log_file provided)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        file_handler.setLevel(getattr(logging, log_level.upper()))
        root_logger.addHandler(file_handler)
    
    # Suppress noisy third-party loggers
    logging.getLogger("neo4j").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)