"""Public API exports for the ecograph.config package."""

from .logger_config import setup_logging
from . import settings

__all__ = [
    "settings",
    "setup_logging",
]
