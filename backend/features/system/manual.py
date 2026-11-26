"""Ship the FLUX manual (HTML) into <FLUX_ROOT>/FLUX_DOC so every artist finds it there.

Two documents: the FLUX manual (FLUX_Manuel.html, hand written) and the Flows manual
(FLUX_Flows.html, built from docs/user/flows/ by features/system/flows_doc.py). Settings > Doc
shows one tab per document.

ADR 0049: the manual used to land in FLUX_UPDATE (next to the installers). It now lives
in FLUX_DOC; the old copy in FLUX_UPDATE is removed, but only when it is the FLUX manual.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

MANUAL_FILENAME = "FLUX_Manuel.html"
DOC_DIRNAME = "FLUX_DOC"
LEGACY_DIRNAME = "FLUX_UPDATE"
# Package root / resources / manual (same resolution as shelf_core, works when frozen).
MANUAL_SOURCE = Path(__file__).parent.parent.parent / "resources" / "manual" / MANUAL_FILENAME
FLOWS_FILENAME = "FLUX_Flows.html"
FLOWS_SOURCE = MANUAL_SOURCE.parent / FLOWS_FILENAME
DOCS = ("flux", "flows")
# Every FLUX manual carries this title: a file without it is not ours and is never removed.
_MANUAL_MARKER = b"<title>Manuel de FLUX</title>"


def ensure_manual(doc_dir: Path, source: Path = MANUAL_SOURCE,
                  legacy_dir: Path | None = None, filename: str = MANUAL_FILENAME) -> Path | None:
    """Copy the bundled manual into ``doc_dir`` when missing or different.

    When ``legacy_dir`` is given, the stale copy left there by older FLUX versions
    is removed (only when it is the FLUX manual, see _is_flux_manual).
    Returns the destination path, or None when there is nothing to copy.
    """
    if not source.is_file():
        log.warning("[FLUX] Manual not bundled: %s", source)
        return None
    dest = doc_dir / filename
    try:
        # Size first: a different size means a different manual without reading the
        # copy on the share (every backend start runs this).
        if not (dest.is_file() and dest.stat().st_size == source.stat().st_size
                and dest.read_bytes() == source.read_bytes()):
            doc_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
            log.info("[FLUX] Manual copied to %s", dest)
    except OSError as exc:  # read-only share, file open elsewhere: never fatal
        log.warning("[FLUX] Manual copy to %s failed: %s", dest, exc)
        return None
    if legacy_dir is not None:
        remove_legacy_manual(legacy_dir, source)
    return dest


def remove_legacy_manual(legacy_dir: Path, source: Path = MANUAL_SOURCE) -> bool:
    """Delete <legacy_dir>/FLUX_Manuel.html when it is the FLUX manual. Never fatal."""
    old = legacy_dir / MANUAL_FILENAME
    try:
        if not old.is_file() or not _is_flux_manual(old, source):
            return False
        old.unlink()
    except OSError as exc:
        log.warning("[FLUX] Old manual %s not removed: %s", old, exc)
        return False
    log.info("[FLUX] Old manual removed from %s", legacy_dir)
    return True


def _is_flux_manual(path: Path, source: Path) -> bool:
    data = path.read_bytes()
    if source.is_file() and data == source.read_bytes():
        return True
    return _MANUAL_MARKER in data[:4096]


def ensure_manual_in_root(root: Path, source: Path = MANUAL_SOURCE) -> Path | None:
    """Manuals into <root>/FLUX_DOC, old copy out of <root>/FLUX_UPDATE."""
    ensure_manual(root / DOC_DIRNAME, FLOWS_SOURCE, filename=FLOWS_FILENAME)
    return ensure_manual(root / DOC_DIRNAME, source, legacy_dir=root / LEGACY_DIRNAME)


def ensure_manual_in_flux_root() -> Path | None:
    """Same as ensure_manual_in_root, on the configured FLUX_ROOT (no-op before first launch)."""
    from core import paths
    root = paths.get_flux_root()
    if root is None:
        return None
    ensure_manual(paths.get_doc_dir(), FLOWS_SOURCE, filename=FLOWS_FILENAME)
    return ensure_manual(paths.get_doc_dir(), legacy_dir=paths.get_update_dir())


def manual_path(doc: str = "flux") -> Path | None:
    """The manual to show (``doc``: flux or flows): the local bundled copy (installed
    with the app, no network read), else the FLUX_DOC copy on the shared root."""
    source, filename = (FLOWS_SOURCE, FLOWS_FILENAME) if doc == "flows" else (MANUAL_SOURCE, MANUAL_FILENAME)
    if source.is_file():
        return source
    from core import paths
    try:
        if paths.get_flux_root() is not None:
            copy = paths.get_doc_dir() / filename
            if copy.is_file():
                return copy
    except (OSError, RuntimeError):
        pass
    return None
