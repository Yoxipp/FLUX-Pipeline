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


def _export_abc(
    file_path: Path,
    selection_only: bool,
    frame_start: int | None = None,
    frame_end: int | None = None,
) -> bool:
    """Export to Alembic matching 'Cache > Alembic Cache > Export {All|Selection} to Alembic'.

    Explicit -root flags are required — AbcExport silently writes an empty file when
    no roots are given on several Maya versions (confirmed via SO/44573304).
    cmds.AbcExport(j=...) is used (Python binding) to avoid nested MEL string quoting.
    """
    if not _ensure_plugin("AbcExport"):
        return False

    path_fwd = str(file_path).replace("\\", "/")

    # AbcExport -root must receive transform/group nodes, never shape nodes.
    # Shapes don't carry transformation data; using them as roots drops hierarchy
    # and produces empty or broken ABC files on many Maya versions.
    if selection_only:
        sel: list[str] = cmds.ls(sl=True, long=True) or []  # type: ignore[union-attr]
        roots: list[str] = []
        for node in sel:
            if cmds.nodeType(node) == "transform":  # type: ignore[union-attr]
                roots.append(node)
            else:
                # Shape or non-transform selected — use its parent transform
                parents: list[str] = cmds.listRelatives(node, parent=True, fullPath=True) or []  # type: ignore[union-attr]
                roots.extend(parents)
        roots = list(dict.fromkeys(roots))  # deduplicate, preserve order
    else:
        # World-level assemblies that contain mesh geometry (equivalent to "Export All")
        all_assemblies: list[str] = cmds.ls(assemblies=True, long=True) or []  # type: ignore[union-attr]
        roots = [
            a for a in all_assemblies
            if cmds.ls(a, dag=True, type="mesh", noIntermediate=True)  # type: ignore[union-attr]
        ]
        if not roots:
            # Fallback for non-standard scenes: direct parents of all mesh shapes
            all_shapes: list[str] = cmds.ls(type="mesh", long=True, noIntermediate=True) or []  # type: ignore[union-attr]
            parents_set: set[str] = set()
            for s in all_shapes:
                p: list[str] = cmds.listRelatives(s, parent=True, fullPath=True) or []  # type: ignore[union-attr]
                parents_set.update(p)
            roots = list(parents_set)

    if not roots:
        log.warning("ABC export: no DAG roots found (selection_only=%s)", selection_only)
        return False

    log.debug("ABC export roots (%d): %s", len(roots), roots)

    job_parts: list[str] = []
    if frame_start is not None and frame_end is not None:
        job_parts.append(f"-frameRange {frame_start} {frame_end}")
    job_parts += ["-uvWrite", "-worldSpace", "-writeVisibility", "-dataFormat ogawa"]
    for root in roots:
        job_parts.append(f"-root {root}")
    job_parts.append(f'-file "{path_fwd}"')

    try:
        cmds.AbcExport(j=" ".join(job_parts))  # type: ignore[union-attr]
        log.info("Exported (ABC) %d roots → %s", len(roots), file_path.name)
        return True
    except Exception as exc:
        log.error("ABC export failed: %s", exc)
        return False


def _export_usd(file_path: Path, selection_only: bool) -> bool:
    if not _ensure_plugin("mayaUsdExport"):
        return False
    path_fwd = str(file_path).replace("\\", "/")
    kwargs: dict = {
        "file":              path_fwd,
        "defaultMeshScheme": "none",
        "exportUVs":         1,
        "exportSkels":       "none",
    }
    if selection_only:
        kwargs["selection"] = True
    try:
        cmds.mayaUSDExport(**kwargs)  # type: ignore[union-attr]
        return True
    except Exception as exc:
        log.error("USD export failed: %s", exc)
        return False


# ── public API ────────────────────────────────────────────────────────────────

def export_selection(
    file_path: str | Path,
    extension: str,
    frame_start: int | None = None,
    frame_end: int | None = None,
) -> Path | None:
    """Export the current Maya selection to *file_path*.

    Supported extensions: .mb .ma .abc .fbx .obj .usd
    frame_start/frame_end only apply to .abc (animated geo).
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
            return out if _export_abc(out, selection_only=True, frame_start=frame_start, frame_end=frame_end) else None

        if ext == ".usd":
            return out if _export_usd(out, selection_only=True) else None

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


def export_scene(
    file_path: str | Path,
    extension: str,
    frame_start: int | None = None,
    frame_end: int | None = None,
) -> Path | None:
    """Export the entire Maya scene to *file_path*.

    Supported extensions: .mb .ma .abc .fbx .obj .usd
    frame_start/frame_end only apply to .abc (animated geo).
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
            return out if _export_abc(out, selection_only=False, frame_start=frame_start, frame_end=frame_end) else None

        if ext == ".usd":
            return out if _export_usd(out, selection_only=False) else None

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

