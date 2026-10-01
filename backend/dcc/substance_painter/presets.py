# presets.py - Painter export presets shipped with FLUX (2026-09-26).
#
# The studio presets (resources/painter/export-presets/*.spexp, e.g. FLUX_BEAUTY_MAPS)
# are copied into Painter's user export presets when the Painter bridge is installed, so
# they show up in Painter's own export dialog too. A project names the ones it uses
# (project.json "texturing.painter_presets", picked at project creation): the Publisher
# only offers those.

from __future__ import annotations

import os
import shutil
from pathlib import Path

from core.logger import get_logger
from dcc.user_dirs import documents_dir

log = get_logger(__name__)

_BUNDLED_DIR = Path(__file__).resolve().parents[2] / "resources" / "painter" / "export-presets"
_PAINTER_PRESETS = ("Adobe", "Adobe Substance 3D Painter", "assets", "export-presets")
# Names the presets shipped under before (2026-09-26: "FLUX_*, pas LR_INSECT_*").
_RENAMED = {"LR_INSECT_BEAUTY_MAPS": "FLUX_BEAUTY_MAPS", "LR_INSECT_UTIL_MAPS": "FLUX_UTIL_MAPS"}


def bundled_presets() -> list[str]:
    """Names of the export presets FLUX ships (file stem = preset name in Painter)."""
    return sorted(p.stem for p in _BUNDLED_DIR.glob("*.spexp")) if _BUNDLED_DIR.is_dir() else []


def painter_presets_dir() -> Path:
    """Painter user export presets folder (override: FLUX_SP_PRESETS_DIR)."""
    override = os.environ.get("FLUX_SP_PRESETS_DIR")
    if override:
        return Path(override)
    return documents_dir().joinpath(*_PAINTER_PRESETS)


def install_presets() -> list[str]:
    """Copy the shipped presets into Painter (copy when missing or changed). Painter
    reads them at its next start. Returns the installed paths; never raises."""
    dest_dir = painter_presets_dir()
    installed: list[str] = []
    for src in sorted(_BUNDLED_DIR.glob("*.spexp")) if _BUNDLED_DIR.is_dir() else []:
        dest = dest_dir / src.name
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            if not dest.is_file() or dest.read_bytes() != src.read_bytes():
                shutil.copyfile(src, dest)
            installed.append(str(dest))
        except OSError as exc:
            log.warning("Painter preset %s not installed: %s", src.name, exc)
    # Drop the copies FLUX installed under the old names (only when identical to ours,
    # so a preset the user edited is never touched).
    for old, new in _RENAMED.items():
        stale, src = dest_dir / f"{old}.spexp", _BUNDLED_DIR / f"{new}.spexp"
        try:
            if stale.is_file() and src.is_file() and stale.read_bytes() == src.read_bytes():
                stale.unlink()
        except OSError as exc:
            log.warning("Old Painter preset %s not removed: %s", stale.name, exc)
    if installed:
        log.info("Painter export presets installed -> %s", dest_dir)
    return installed



def find_installed_presets() -> list[Path]:
    """FLUX presets present in Painter AND still identical to the shipped copy."""
    dest_dir = painter_presets_dir()
    found: list[Path] = []
    for src in sorted(_BUNDLED_DIR.glob("*.spexp")) if _BUNDLED_DIR.is_dir() else []:
        dest = dest_dir / src.name
        try:
            if dest.is_file() and dest.read_bytes() == src.read_bytes():
                found.append(dest)
        except OSError:
            continue
    return found


def remove_presets() -> list[str]:
    """Delete the FLUX presets from Painter (FLUX uninstaller). A preset the user edited
    no longer matches the shipped copy and is kept. Returns the deleted paths."""
    removed: list[str] = []
    for f in find_installed_presets():
        try:
            f.unlink()
            removed.append(str(f))
        except OSError as exc:
            log.warning("Painter preset %s not removed: %s", f.name, exc)
    return removed

def project_presets(project_path: str | Path) -> list[str]:
    """Export presets the project uses (empty = no choice made: every preset)."""
    from features.folder_manager.project_config import read_project_config

    cfg = read_project_config(Path(project_path)) or {}
    names = (cfg.get("texturing") or {}).get("painter_presets") or []
    out: list[str] = []
    for n in (str(n).strip() for n in names):
        n = _RENAMED.get(n, n)
        if n and n not in out:
            out.append(n)
    return out
