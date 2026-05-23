"""
src/ecograph/config

Public surface of the config package.

Import pattern for consumers:
    from ecograph.config import settings, setup_logging
    from ecograph.config.settings import NEO4J_URI, GEMINI_MODEL

We explicitly re-export only what the rest of the codebase should use.
Nothing else in this package is part of the public API.
"""

from ecograph.config.logger_config import setup_logging
from ecograph.config import settings

__all__ = [
    "settings",
    "setup_logging",
]