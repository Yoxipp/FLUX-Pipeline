# version_resolver.py — scan published folders for versioned files, compute next version.

from __future__ import annotations

import re
from pathlib import Path

from core.constants import ACTIVE_VERSION_LABEL, DEFAULT_PADDING
from core.logger import get_logger

log = get_logger(__name__)

_VERSION_RE = re.compile(r'^v(\d+)$', re.IGNORECASE)


def get_last_file(folder_path: Path, base_name: str) -> Path | None:
    """Return the active LAST file for *base_name* in *folder_path*, or None.

    Flat ``<base>_LAST.ext`` (pointer layer, copy or legacy copy) and the target of
    ``<base>_LAST.ext.link`` (ADR 0017) win over the older nested layouts.
    """
    if not folder_path.exists():
        return None
    # flat derived LAST / .link target / legacy copy, then the nested layouts
    from features.publisher.publish_layout import find_last_file
    hit = find_last_file(folder_path, base_name)
    if hit is not None:
        return hit
    no_ext = folder_path / f"{base_name}_{ACTIVE_VERSION_LABEL}"   # edge case
    return no_ext if no_ext.is_file() else None


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

    from features.publisher.last_pointer import parse_published_name

    max_ver = 0
    prefix = f"{base_name}_"
    for f in folder_path.iterdir():
        if not f.is_file():
            continue
        stem, _ext, role = parse_published_name(f.name)
        if role != "data":
            continue
        if not stem.startswith(prefix):
            continue
        suffix = stem[len(prefix):]
        m = _VERSION_RE.match(suffix)
        if m:
            max_ver = max(max_ver, int(m.group(1)))

    # also count nested-layout archive folders (<base>_<FMT>_Vnnn)
    from features.publisher.publish_layout import highest_version_any
    max_ver = max(max_ver, highest_version_any(folder_path, base_name))

    return max_ver + 1

