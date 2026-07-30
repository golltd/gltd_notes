"""Application logging with daily log files in the config directory."""

from __future__ import annotations

import logging
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

_log_handlers_initialized: bool = False
_log_dir: Optional[Path] = None


def setup_logging(log_dir: Path) -> logging.Logger:
    global _log_handlers_initialized, _log_dir  # noqa: PLW0603
    _log_dir = Path(log_dir)
    _log_dir.mkdir(parents=True, exist_ok=True)

    logger = get_global_logger()

    if not _log_handlers_initialized:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_path = _log_dir / f"gltd_notes_{today}.log"
        fh = logging.FileHandler(str(log_path), encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
        logger.setLevel(logging.DEBUG)
        _log_handlers_initialized = True

    logger.info("GLTD Notes iniciado — logs em %s", _log_dir)
    return logger


def get_global_logger() -> logging.Logger:
    logger = logging.getLogger("gltd_notes")
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    return logger


def log_exception(logger: logging.Logger, msg: str, exc: BaseException) -> None:
    logger.error(f"{msg}: {exc}")
    logger.debug(traceback.format_exc())


def get_log_dir() -> Optional[Path]:
    return _log_dir


def list_log_files() -> List[Path]:
    if not _log_dir or not _log_dir.exists():
        return []
    files = sorted(
        _log_dir.glob("gltd_notes_*.log"),
        key=lambda p: p.name,
        reverse=True,
    )
    return files
