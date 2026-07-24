"""Centralized logging configuration for Satan components."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = Path(os.environ.get("SATAN_DATA_DIR", PROJECT_ROOT / "data"))

def setup_logger(name: str, log_filename: str = "satan.log") -> logging.Logger:
    """Set up and return a logger with rotating file handler and stream handler."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log_file = DATA_DIR / log_filename
    
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # Avoid duplicate handlers if setup_logger is called multiple times
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler with rotation (5 MB per file, max 3 backups)
    file_handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    logger.addHandler(console_handler)

    return logger

logger = setup_logger("satan.backend", "satan-server.log")

