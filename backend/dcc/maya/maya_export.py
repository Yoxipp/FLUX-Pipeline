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

# USD container extensions, all routed through mayaUSDExport.
_USD_EXTS: frozenset[str] = frozenset({".usd", ".usda", ".usdc"})


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


def _load_usd_plugin() -> bool:
    """Load the Maya USD plugin.

    The `mayaUSDExport` command is provided by `mayaUsdPlugin` (Maya 2022+).
    `mayaUsdExport` is kept as a fallback for older/renamed builds.
    """
    for plugin in ("mayaUsdPlugin", "mayaUsdExport"):
        if _ensure_plugin(plugin):
            return True
    return False


def _export_usd(file_path: Path, selection_only: bool) -> bool:
    if not _load_usd_plugin():
        log.error("USD export: Maya USD plugin unavailable (tried mayaUsdPlugin)")
        return False
    path_fwd = str(file_path).replace("\\", "/")
    # .usda -> ascii text, .usdc / .usd -> binary crate (standard, compact).
    usd_format = "usda" if file_path.suffix.lower() == ".usda" else "usdc"
    kwargs: dict = {
        "file":              path_fwd,
        "defaultUSDFormat":  usd_format,
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

    Supported extensions: .mb .ma .abc .fbx .obj .usd .usda .usdc
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

        if ext in _USD_EXTS:
            return out if _export_usd(out, selection_only=True) else None

        # Some formats are provided by a plugin that Maya does not load by default.
        # Loading it up front turns "unknown file type" errors into an actionable one.
        if ext == ".fbx" and not _ensure_plugin("fbxmaya"):
            log.error("FBX export: 'fbxmaya' plugin could not be loaded")
            return None
        if ext == ".obj" and not _ensure_plugin("objExport"):
            log.error("OBJ export: 'objExport' plugin could not be loaded")
            return None

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

    Supported extensions: .mb .ma .abc .fbx .obj .usd .usda .usdc
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

        if ext in _USD_EXTS:
            return out if _export_usd(out, selection_only=False) else None

        # Load plugin-provided formats up front (see export_selection for rationale).
        if ext == ".fbx" and not _ensure_plugin("fbxmaya"):
            log.error("FBX export: 'fbxmaya' plugin could not be loaded")
            return None
        if ext == ".obj" and not _ensure_plugin("objExport"):
            log.error("OBJ export: 'objExport' plugin could not be loaded")
            return None

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


def run_publish_export(
    file_path: str,
    extension: str,
    scope: str,
    result_path: str,
    frame_start: int | None = None,
    frame_end: int | None = None,
) -> None:
    """Export for the Flux publisher and persist a JSON result envelope.

    Runs inside Maya. Maya is a separate process from the Flux hub, so its log
    messages are otherwise invisible to the user. This captures every 'flux.*'
    log record emitted during the export and writes
    ``{ok, path, logs:[{level,msg}]}`` to *result_path*, letting the hub surface
    the real failure reason (e.g. a missing plugin) in the Flux console.

    *scope* is 'scene' for a full-scene export, anything else exports the selection.
    """
    import json
    import logging

    records: list[dict] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                msg = record.getMessage()
            except Exception:
                msg = str(record.msg)
            records.append({"level": record.levelname, "msg": msg})

    collector = _Collector()
    collector.setLevel(logging.INFO)
    flux_root = logging.getLogger("flux")
    flux_root.addHandler(collector)

    result: Path | None = None
    try:
        export_fn = export_scene if scope == "scene" else export_selection
        if extension == ".abc" and frame_start is not None and frame_end is not None:
            result = export_fn(file_path, extension, frame_start=frame_start, frame_end=frame_end)
        else:
            result = export_fn(file_path, extension)
    except Exception as exc:  # pragma: no cover - defensive; export_fn already guards
        records.append({"level": "ERROR", "msg": f"export raised: {exc!r}"})
    finally:
        flux_root.removeHandler(collector)

    envelope = {
        "ok":   result is not None,
        "path": str(result) if result else None,
        "logs": records,
    }
    try:
        with open(result_path, "w", encoding="utf-8") as fh:
            json.dump(envelope, fh)
    except OSError as exc:
        log.error("run_publish_export: cannot write result envelope: %s", exc)


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

