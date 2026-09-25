# presets.py - Painter export presets shipped with FLUX (2026-09-26).
#
# The studio presets (resources/painter/export-presets/*.spexp, e.g. LR_INSECT_BEAUTY_MAPS)
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
    if installed:
        log.info("Painter export presets installed -> %s", dest_dir)
    return installed


def project_presets(project_path: str | Path) -> list[str]:
    """Export presets the project uses (empty = no choice made: every preset)."""
    from features.folder_manager.project_config import read_project_config

    cfg = read_project_config(Path(project_path)) or {}
    names = (cfg.get("texturing") or {}).get("painter_presets") or []
    return [str(n) for n in names if str(n).strip()]
