"""Application-wide logging setup."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_FILE = _LOG_DIR / "app.log"
_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_configured = False


def _configure_root() -> None:
    global _configured
    if _configured:
        return
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    stream = logging.StreamHandler()
    stream.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(stream)

    file_handler = RotatingFileHandler(
        _LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(file_handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    _configure_root()
    return logging.getLogger(name)
