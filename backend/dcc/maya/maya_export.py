# maya_export.py — export Maya scene / selection to disk.
# Runs inside Maya (Python 3.10). Called via socket-dispatched commands or shelf.

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)

try:
    import maya.cmds as cmds  # type: ignore[import]
    _IN_MAYA = True
except ImportError:
    cmds = None
    _IN_MAYA = False

# cmds.file() type identifiers per extension
_FILE_TYPES: dict[str, str] = {
    ".mb":  "mayaBinary",
    ".ma":  "mayaAscii",
    ".fbx": "FBX export",
    ".obj": "OBJexport",
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _ensure_plugin(plugin: str) -> bool:
    """Load *plugin* into Maya if not already loaded. Return True on success."""
    try:
        if not cmds.pluginInfo(plugin, q=True, loaded=True):  # type: ignore[union-attr]
            cmds.loadPlugin(plugin, quiet=True)  # type: ignore[union-attr]
        return True
    except Exception as exc:
        log.error("Cannot load plugin %s: %s", plugin, exc)
        return False


def _normalise_ext(extension: str) -> str:
    return extension if extension.startswith(".") else f".{extension}"


def _export_abc(file_path: Path, selection_only: bool) -> bool:
    if not _ensure_plugin("AbcExport"):
        return False
    flags = "-writeVisibility -uvWrite"
    if selection_only:
        flags += " -selection"
    path_fwd = str(file_path).replace("\\", "/")
    try:
        cmds.AbcExport(j=f"{flags} -file {path_fwd}")  # type: ignore[union-attr]
        return True
    except Exception as exc:
        log.error("ABC export failed: %s", exc)
        return False


# ── public API ────────────────────────────────────────────────────────────────

def export_selection(file_path: str | Path, extension: str) -> Path | None:
    """Export the current Maya selection to *file_path*.

    Supported extensions: .mb .ma .abc .fbx .obj
    Returns the exported path on success, None on failure.
    """
    if not _IN_MAYA:
        log.error("export_selection: not running inside Maya")
        return None

    ext = _normalise_ext(extension).lower()
    out = Path(file_path).with_suffix(ext)
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        if ext == ".abc":
            return out if _export_abc(out, selection_only=True) else None

        if ext == ".fbx":
            _ensure_plugin("fbxmaya")

        file_type = _FILE_TYPES.get(ext)
        if file_type is None:
            log.error("Unsupported export extension: %s", ext)
            return None

        cmds.file(str(out), force=True, type=file_type, exportSelected=True)  # type: ignore[union-attr]
        log.info("Exported selection → %s", out.name)
        return out
    except Exception as exc:
        log.error("export_selection failed: %s", exc)
        return None


def export_scene(file_path: str | Path, extension: str) -> Path | None:
    """Export the entire Maya scene to *file_path*.

    Supported extensions: .mb .ma .abc .fbx .obj
    Returns the exported path on success, None on failure.
    """
    if not _IN_MAYA:
        log.error("export_scene: not running inside Maya")
        return None

    ext = _normalise_ext(extension).lower()
    out = Path(file_path).with_suffix(ext)
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        if ext == ".abc":
            return out if _export_abc(out, selection_only=False) else None

        if ext == ".fbx":
            _ensure_plugin("fbxmaya")

        file_type = _FILE_TYPES.get(ext)
        if file_type is None:
            log.error("Unsupported export extension: %s", ext)
            return None

        cmds.file(str(out), force=True, type=file_type, exportAll=True)  # type: ignore[union-attr]
        log.info("Exported scene → %s", out.name)
        return out
    except Exception as exc:
        log.error("export_scene failed: %s", exc)
        return None


def export_scene_to_temp(extension: str = ".mb") -> Path | None:
    """Export the current Maya scene to a temp file and return its path.

    Used by maya_publish as an intermediate step before publish_core.
    Caller is responsible for deleting the temp file.
    """
    if not _IN_MAYA:
        return None
    ext = _normalise_ext(extension)
    try:
        fd, tmp = tempfile.mkstemp(suffix=ext, prefix="flux_publish_")
        os.close(fd)
        return export_scene(tmp, ext)
    except Exception as exc:
        log.error("export_scene_to_temp failed: %s", exc)
        return None

