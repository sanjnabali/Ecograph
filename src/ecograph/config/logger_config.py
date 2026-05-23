"""
src/ecograph/config/logger_config.py

Structured logging for EcoGraph.

Design decisions:
- JSON output in production so log aggregators (Datadog, Loki) can index
  fields without regex. Text output in development for readability.
- A single setup_logging() call configures the root logger once.
  Every module does: logger = logging.getLogger(__name__)
  They do NOT call setup_logging() themselves.
- setup_logging() is idempotent — calling it twice does not duplicate
  handlers, which matters in test suites and hot-reload scenarios.
- Third-party libraries that produce excessive DEBUG noise are silenced
  to WARNING at module level.
- We do not use the logging.config.dictConfig approach here because our
  config is dynamic (log level, log file, format are all runtime-determined
  from .env). The explicit handler approach is clearer.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

class _JsonFormatter(logging.Formatter):
    """
    Outputs one JSON object per log line.

    Fields always present:
        ts       - ISO-8601 UTC timestamp
        level    - DEBUG / INFO / WARNING / ERROR / CRITICAL
        logger   - dotted module name (e.g. "ecograph.ingestion.erp_connector")
        msg      - formatted message string
        module   - source file name without extension
        func     - function name
        line     - line number

    Optional fields (only when non-empty):
        exc      - formatted exception traceback
        *        - any extra fields passed via the 'extra' kwarg to the logger
    """

    # Fields the LogRecord carries that we have already mapped to top-level keys
    # and should not be duplicated under 'extra'.
    _SKIP_ATTRS = frozenset({
        "name", "msg", "args", "levelname", "levelno", "pathname",
        "filename", "module", "exc_info", "exc_text", "stack_info",
        "lineno", "funcName", "created", "msecs", "relativeCreated",
        "thread", "threadName", "processName", "process", "message",
        "taskName",
    })

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts":     datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level":  record.levelname,
            "logger": record.name,
            "msg":    record.getMessage(),
            "module": record.module,
            "func":   record.funcName,
            "line":   record.lineno,
        }

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        # Include any extra={...} fields the caller provided
        for key, value in vars(record).items():
            if key not in self._SKIP_ATTRS:
                try:
                    json.dumps(value)   # test serializability
                    payload[key] = value
                except (TypeError, ValueError):
                    payload[key] = repr(value)

        return json.dumps(payload, ensure_ascii=False)


class _TextFormatter(logging.Formatter):
    """
    Human-readable single-line format for development.

    Format:
        2024-01-15T09:12:33Z  INFO     ecograph.ingestion.erp_connector:42  message text
    """

    _WIDTH_LEVEL  = 8
    _WIDTH_LOGGER = 45

    def format(self, record: logging.LogRecord) -> str:
        ts      = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        level   = record.levelname.ljust(self._WIDTH_LEVEL)
        loc     = f"{record.name}:{record.lineno}".ljust(self._WIDTH_LOGGER)
        message = record.getMessage()

        line = f"{ts}  {level}  {loc}  {message}"

        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)

        return line


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def setup_logging(
    log_file: Optional[Path] = None,
    log_format: str = "json",
    log_level: str = "INFO",
) -> None:
    """
    Configure the root logger exactly once.

    Calling this function multiple times is safe — subsequent calls detect
    that EcoGraph handlers are already attached and return immediately.
    This prevents handler duplication in test suites, Streamlit reruns,
    and FastAPI hot-reload cycles.

    Args:
        log_file:   Write log records to this file in addition to stdout.
                    The parent directory is created if it does not exist.
                    Pass None to disable file logging.
        log_format: "json" for structured output (CI, production, log aggregators).
                    "text" for human-readable development output.
        log_level:  Standard Python level name. Case-insensitive.
                    Accepted: DEBUG, INFO, WARNING, ERROR, CRITICAL.

    Raises:
        ValueError: If log_format or log_level is not a recognised value.
    """
    log_format = log_format.lower().strip()
    if log_format not in ("json", "text"):
        raise ValueError(
            f"log_format must be 'json' or 'text'; received '{log_format}'."
        )

    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(
            f"log_level '{log_level}' is not a valid Python logging level."
        )

    root_logger = logging.getLogger()

    # Idempotency guard — detect our sentinel handler
    _SENTINEL = "ecograph_sentinel"
    if any(getattr(h, "_ecograph_sentinel", False) for h in root_logger.handlers):
        return

    root_logger.setLevel(numeric_level)

    # Remove any handlers added before our call (e.g. basicConfig defaults)
    root_logger.handlers.clear()

    formatter: logging.Formatter = (
        _JsonFormatter() if log_format == "json" else _TextFormatter()
    )

    # --- stdout handler (always present) ---
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    stdout_handler.setLevel(numeric_level)
    stdout_handler._ecograph_sentinel = True   # type: ignore[attr-defined]
    root_logger.addHandler(stdout_handler)

    # --- file handler (optional) ---
    if log_file is not None:
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(numeric_level)
        root_logger.addHandler(file_handler)

    # --- silence noisy third-party libraries ---
    _suppress = {
        "neo4j":              logging.WARNING,
        "urllib3":            logging.WARNING,
        "urllib3.connectionpool": logging.ERROR,
        "httpcore":           logging.WARNING,
        "httpx":              logging.WARNING,
        "google":             logging.WARNING,
        "google.auth":        logging.WARNING,
        "grpc":               logging.WARNING,
        "PIL":                logging.WARNING,
        "matplotlib":         logging.WARNING,
        "numexpr":            logging.WARNING,
        "py4j":               logging.WARNING,
        "duckdb":             logging.WARNING,
        "onnxruntime":        logging.WARNING,
        "pyarrow":            logging.WARNING,
        "fsspec":             logging.WARNING,
    }
    for lib_name, level in _suppress.items():
        logging.getLogger(lib_name).setLevel(level)