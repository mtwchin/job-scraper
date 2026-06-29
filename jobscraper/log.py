"""Centralized logging setup."""
from __future__ import annotations

import logging
import os

_configured = False


def configure() -> None:
    global _configured
    if _configured:
        return
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    _configured = True


def get(name: str = "jobscraper") -> logging.Logger:
    configure()
    return logging.getLogger(name)
