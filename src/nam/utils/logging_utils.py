"""Loguru setup."""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def setup_logging(log_dir: Path, *, verbose: bool = False) -> None:
    """Configure console and file logging."""
    logger.remove()
    logger.add(sys.stderr, level="DEBUG" if verbose else "WARNING", colorize=True)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_dir / "nam.log",
            level="DEBUG",
            rotation="5 MB",
            retention=5,
            enqueue=True,
        )
    except OSError as exc:
        logger.warning("Could not open log file in {}: {}", log_dir, exc)
