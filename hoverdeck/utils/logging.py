"""Logging setup: one rotating file in the data dir plus stderr."""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(log_file: Path, level: int = logging.INFO) -> None:
    """Configure the root ``hoverdeck`` logger. Safe to call once at startup."""
    logger = logging.getLogger("hoverdeck")
    if logger.handlers:  # already configured
        return
    logger.setLevel(level)

    stream = logging.StreamHandler()
    stream.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(stream)

    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=512_000, backupCount=2, encoding="utf-8"
        )
        file_handler.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(file_handler)
    except OSError:
        logger.warning("Could not open log file %s — logging to stderr only.", log_file)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"hoverdeck.{name}")
