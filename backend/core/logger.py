# logger.py — centralised logging for all Flux modules.

from __future__ import annotations

import logging
import os
import sys
from datetime import date
from pathlib import Path


_LOG_DIR: Path | None = None
_handlers_initialised = False


def _get_log_dir() -> Path:
    """Return the log directory, defaulting to APPDATA/Flux/logs/."""
    if _LOG_DIR is not None:
        return _LOG_DIR
    appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return appdata / "Flux" / "logs"


def _ensure_file_handler(root_logger: logging.Logger) -> None:
    """Add a rotating file handler to *root_logger* if not already present."""
    log_dir = _get_log_dir()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"flux_{date.today().isoformat()}.log"
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
            datefmt="%H:%M:%S",
        ))
        root_logger.addHandler(fh)
    except OSError:
        pass  # log dir not writable — file logging silently disabled


def _initialise_root() -> None:
    global _handlers_initialised
    if _handlers_initialised:
        return
    _handlers_initialised = True

    root = logging.getLogger("flux")
    root.setLevel(logging.DEBUG)

    # Console handler — coloured via simple prefix trick
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(_ColourFormatter())
    root.addHandler(ch)

    _ensure_file_handler(root)


def get_logger(module_name: str) -> logging.Logger:
    """Return a child logger named 'flux.<module_name>'.

    Usage:
        log = get_logger(__name__)
        log.info("something happened")
    """
    _initialise_root()
    return logging.getLogger(f"flux.{module_name}")


class _ColourFormatter(logging.Formatter):
    """Minimal ANSI colour for console output."""

    _COLOURS = {
        logging.DEBUG:    "\033[90m",   # grey
        logging.INFO:     "\033[0m",    # default
        logging.WARNING:  "\033[33m",   # yellow
        logging.ERROR:    "\033[31m",   # red
        logging.CRITICAL: "\033[1;31m", # bold red
    }
    _RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        colour = self._COLOURS.get(record.levelno, "")
        message = super().format(record)
        return f"{colour}{message}{self._RESET}"

    def __init__(self) -> None:
        super().__init__(
            fmt="%(levelname)-8s %(name)s — %(message)s",
        )
