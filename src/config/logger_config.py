"""
config/logging_config.py - Central logging step for Ecograph.

Import and call `setup_logging()` ONCE at the very top of main.py.
Every other module just does:
    import logging
    logger = logging.getLogger(__name__)

This gives each module its own named logger 
while all output flows to the same handlers configured here.
"""

import logging
import sys
from pathlib import Path


def setup_logging(log_file: Path = None, level: int = logging.INFO) -> None:
    """
    Configures the root logger with:
    - A streamHandler -> coloured console output
    - A FileHandler -> persistent log file
    
    Safe to call multiple times - handlers are only added once.
    """
    root = logging.getLogger()

    if root.handlers:
        return 
    
    root.setLevel(level)

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s |  %(message)s",

    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)
    
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
