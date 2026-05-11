# version_resolver.py — scan published folders for versioned files, compute next version.

from __future__ import annotations

import re
from pathlib import Path

from core.constants import ACTIVE_VERSION_LABEL, DEFAULT_PADDING
from core.logger import get_logger

log = get_logger(__name__)

_VERSION_RE = re.compile(r'^v(\d+)$', re.IGNORECASE)


def get_last_file(folder_path: Path, base_name: str) -> Path | None:
    """Return the *_LAST.* file for *base_name* in *folder_path*, or None."""
    if not folder_path.exists():
        return None
    prefix = f"{base_name}_{ACTIVE_VERSION_LABEL}"
    # with extension
    matches = list(folder_path.glob(f"{prefix}.*"))
    # without extension (edge case)
    no_ext = folder_path / prefix
    if not matches and no_ext.is_file():
        return no_ext
    return matches[0] if matches else None


def get_next_version(
    folder_path: Path,
    base_name: str,
    padding: int = DEFAULT_PADDING,
) -> int:
    """Return the next version number for *base_name* inside *folder_path*.

    Scans for files named <base_name>_v###[.ext] and returns max+1.
    Returns 1 when no versioned file exists.
    """
    if not folder_path.exists():
        return 1

    max_ver = 0
    prefix = f"{base_name}_"
    for f in folder_path.iterdir():
        if not f.is_file():
            continue
        stem = f.stem
        if not stem.startswith(prefix):
            continue
        suffix = stem[len(prefix):]
        m = _VERSION_RE.match(suffix)
        if m:
            max_ver = max(max_ver, int(m.group(1)))

    return max_ver + 1

