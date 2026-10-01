"""Ship the FLUX manual (HTML) into <FLUX_ROOT>/FLUX_UPDATE so every artist finds it there."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

MANUAL_FILENAME = "FLUX_Manuel.html"
# Package root / resources / manual (same resolution as shelf_core, works when frozen).
MANUAL_SOURCE = Path(__file__).parent.parent.parent / "resources" / "manual" / MANUAL_FILENAME


def ensure_manual(update_dir: Path, source: Path = MANUAL_SOURCE) -> Path | None:
    """Copy the bundled manual into ``update_dir`` when missing or different.

    Returns the destination path, or None when there is nothing to copy.
    """
    if not source.is_file():
        log.warning("[FLUX] Manual not bundled: %s", source)
        return None
    dest = update_dir / MANUAL_FILENAME
    try:
        if dest.is_file() and dest.read_bytes() == source.read_bytes():
            return dest
        update_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
    except OSError as exc:  # read-only share, file open elsewhere: never fatal
        log.warning("[FLUX] Manual copy to %s failed: %s", dest, exc)
        return None
    log.info("[FLUX] Manual copied to %s", dest)
    return dest


def ensure_manual_in_flux_root() -> Path | None:
    """Same as ensure_manual, on the configured FLUX_ROOT (no-op before first launch)."""
    from core import paths
    if paths.get_flux_root() is None:
        return None
    return ensure_manual(paths.get_update_dir())
