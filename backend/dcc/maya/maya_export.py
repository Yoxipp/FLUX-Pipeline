# maya_export.py — export Maya scene / selection to disk.
# Runs inside Maya (Python 3.10). Called via socket-dispatched commands or shelf.
#
# Per-format export options arrive as a plain dict (keys defined in the frontend
# schema app/src/lib/mayaExportOptions.ts) and are mapped here onto each format's
# real command: cmds.file flags (ma/mb), FBXExport* MEL (fbx), an options string
# (obj), AbcExport -j flags (abc) and mayaUSDExport kwargs (usd). Every option's
# default reproduces the pre-options export exactly, so an empty/None options dict
# behaves like the old code path.

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


# ── option readers ────────────────────────────────────────────────────────────

def _b(options: dict | None, key: str, default: bool) -> bool:
    if not options or key not in options:
        return default
    return bool(options[key])


def _s(options: dict | None, key: str, default: str) -> str:
    if not options or key not in options:
        return default
    return str(options[key])


def _i(options: dict | None, key: str, default: int) -> int:
    if not options or key not in options:
        return default
    try:
        return int(options[key])
    except (TypeError, ValueError):
        return default


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


# ── Maya scene (.ma / .mb) ────────────────────────────────────────────────────

def _maya_scene_kwargs(options: dict | None) -> dict:
    """cmds.file export flags for mayaAscii/mayaBinary. Defaults == Maya defaults."""
    return {
        "constructionHistory": _b(options, "construction_history", True),
        "channels":            _b(options, "channels", True),
        "constraints":         _b(options, "constraints", True),
        "expressions":         _b(options, "expressions", True),
        "shader":              _b(options, "shaders", True),
        "preserveReferences":  _b(options, "preserve_references", False),
    }


# ── FBX (.fbx) ────────────────────────────────────────────────────────────────

def _export_fbx(file_path: Path, selection_only: bool, options: dict | None) -> bool:
    """Export FBX via the FBXExport* MEL API (deterministic, explicit settings).

    cmds.file(type="FBX export") uses whatever the plugin's persisted prefs are;
    driving FBXExport* directly makes every publish reproducible regardless of the
    artist's local FBX preferences. Each property set is guarded so one option
    unsupported by the running FBX plugin version never fails the whole export.
    """
    if not _ensure_plugin("fbxmaya"):
        log.error("FBX export: 'fbxmaya' plugin could not be loaded")
        return False

    import maya.mel as mel  # type: ignore[import]

    o = options or {}
    path_fwd = str(file_path).replace("\\", "/")

    def _safe(expr: str) -> None:
        try:
            mel.eval(expr)
        except Exception as exc:  # unsupported flag on this FBX version — skip it
            log.warning("FBX option skipped (%s): %s", expr, exc)

    def _flag(cmd: str, val: bool) -> None:
        _safe(f'{cmd} -v {"true" if val else "false"}')

    # Start from plugin defaults so nothing leaks from a previous export.
    _safe("FBXResetExport")

    # Geometry
    _flag("FBXExportSmoothingGroups", _b(o, "smoothing_groups", True))
    _flag("FBXExportSmoothMesh", _b(o, "smooth_mesh", True))
    _flag("FBXExportHardEdges", _b(o, "split_vertex_normals", False))
    _flag("FBXExportTangents", _b(o, "tangents", False))
    _flag("FBXExportTriangulate", _b(o, "triangulate", False))
    _flag("FBXExportInstances", _b(o, "instances", False))
    _flag("FBXExportReferencedAssetsContent", _b(o, "referenced_assets", False))

    # Deformers
    _flag("FBXExportSkins", _b(o, "skins", True))
    _flag("FBXExportShapes", _b(o, "blend_shapes", True))
    _flag("FBXExportSkeletonDefinitions", _b(o, "skeleton_definitions", False))

    # Animation / baking
    bake = _b(o, "bake_animation", False)
    _flag("FBXExportBakeComplexAnimation", bake)
    if bake:
        _safe(f'FBXExportBakeComplexStart -v {_i(o, "bake_start", 1)}')
        _safe(f'FBXExportBakeComplexEnd -v {_i(o, "bake_end", 100)}')
        _safe(f'FBXExportBakeComplexStep -v {_i(o, "bake_step", 1)}')
        _flag("FBXExportBakeResampleAnimation", _b(o, "resample_all", False))
    _flag("FBXExportApplyConstantKeyReducer", _b(o, "constant_key_reducer", False))
    _safe(f'FBXExportQuaternion -v {_s(o, "quaternion", "resample")}')

    # Scene content
    _flag("FBXExportConstraints", _b(o, "constraints", False))
    _flag("FBXExportCameras", _b(o, "cameras", True))
    _flag("FBXExportLights", _b(o, "lights", True))
    _flag("FBXExportEmbeddedTextures", _b(o, "embed_media", False))
    _flag("FBXExportInputConnections", _b(o, "input_connections", True))
    _flag("FBXExportIncludeChildren", _b(o, "include_children", True))
    _flag("FBXExportUseSceneName", _b(o, "use_scene_name", False))

    # More scene content / animation options
    _flag("FBXExportAnimationOnly", _b(o, "animation_only", False))
    _flag("FBXExportAudio", _b(o, "audio", False))
    _flag("FBXExportCacheFile", _b(o, "cache_file", False))
    _flag("FBXExportShapeAttributes", _b(o, "shape_attributes", False))
    _flag("FBXExportSplitAnimationIntoTakes", _b(o, "split_takes", False))
    _flag("FBXExportGenerateLog", _b(o, "generate_log", False))

    # File format
    _flag("FBXExportInAscii", _b(o, "ascii", False))
    _safe(f'FBXExportUpAxis {_s(o, "up_axis", "y")}')
    _safe(f'FBXExportFileVersion -v {_s(o, "file_version", "FBX202000")}')

    # The actual export must not be swallowed — let it raise to the outer guard.
    try:
        if selection_only:
            mel.eval(f'FBXExport -f "{path_fwd}" -s')
        else:
            mel.eval(f'FBXExport -f "{path_fwd}"')
        log.info("Exported (FBX) → %s", file_path.name)
        return True
    except Exception as exc:
        log.error("FBX export failed: %s", exc)
        return False


# ── OBJ (.obj) ────────────────────────────────────────────────────────────────

def _obj_options_str(options: dict | None) -> str:
    """Build the OBJexport options string (groups/ptgroups/materials/smoothing/normals)."""
    def bit(key: str, default: bool) -> str:
        return "1" if _b(options, key, default) else "0"
    return (
        f"groups={bit('groups', True)};"
        f"ptgroups={bit('point_groups', False)};"
        f"materials={bit('materials', True)};"
        f"smoothing={bit('smoothing', True)};"
        f"normals={bit('normals', True)}"
    )


# ── Alembic (.abc) ────────────────────────────────────────────────────────────

def _export_abc(
    file_path: Path,
    selection_only: bool,
    frame_start: int | None = None,
    frame_end: int | None = None,
    options: dict | None = None,
    frame_step: float | None = None,
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

    o = options or {}
    job_parts: list[str] = []
    if frame_start is not None and frame_end is not None:
        job_parts.append(f"-frameRange {frame_start} {frame_end}")
        if frame_step and float(frame_step) != 1.0:
            job_parts.append(f"-step {float(frame_step)}")
    if _b(o, "uv_write", True):
        job_parts.append("-uvWrite")
    if _b(o, "world_space", True):
        job_parts.append("-worldSpace")
    if _b(o, "write_visibility", True):
        job_parts.append("-writeVisibility")
    if _b(o, "renderable_only", False):
        job_parts.append("-renderableOnly")
    if _b(o, "strip_namespaces", False):
        job_parts.append("-stripNamespaces")
    if _b(o, "write_color_sets", False):
        job_parts.append("-writeColorSets")
    if _b(o, "write_uv_sets", False):
        job_parts.append("-writeUVSets")
    if _b(o, "write_face_sets", False):
        job_parts.append("-writeFaceSets")
    if _b(o, "euler_filter", False):
        job_parts.append("-eulerFilter")
    if _b(o, "no_normals", False):
        job_parts.append("-noNormals")
    if _b(o, "write_creases", False):
        job_parts.append("-writeCreases")
    if _b(o, "auto_subd", False):
        job_parts.append("-autoSubd")
    job_parts.append(f"-dataFormat {_s(o, 'data_format', 'ogawa')}")
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


# ── USD (.usd / .usda / .usdc) ────────────────────────────────────────────────

def _load_usd_plugin() -> bool:
    """Load the Maya USD plugin.

    The `mayaUSDExport` command is provided by `mayaUsdPlugin` (Maya 2022+).
    `mayaUsdExport` is kept as a fallback for older/renamed builds.
    """
    for plugin in ("mayaUsdPlugin", "mayaUsdExport"):
        if _ensure_plugin(plugin):
            return True
    return False


# mayaUSDExport flags the UI may pass. Keys == exact mayaUSDExport long flag names,
# so options flow straight through (see mayaExportOptions.ts USD schema).
_USD_BOOL_FLAGS: frozenset[str] = frozenset({
    "exportUVs", "exportMaterials", "exportBlendShapes", "exportColorSets",
    "exportDisplayColor", "exportComponentTags", "exportVisibility", "exportInstances",
    "mergeTransformAndShape", "stripNamespaces", "eulerFilter", "staticSingleSample",
    "worldspace", "preserveUVSetNames", "normalizeNurbs",
    # Custom preset (2026-09-26): every other mayaUSDExport on|off flag.
    "exportAssignedMaterials", "exportMaterialCollections", "exportCollectionBasedBindings",
    "exportRefsAsInstanceable", "includeEmptyTransforms", "exportDistanceUnit", "writeDefaults",
})
_USD_STR_FLAGS: frozenset[str] = frozenset({
    "exportSkels", "exportSkin", "defaultMeshScheme", "geomSidedness", "upAxis", "kind",
    "shadingMode", "animationType", "materialsScopeName", "rootPrim", "rootPrimType",
    "defaultPrim", "renderLayerMode", "exportRelativeTextures",
})
# Multi-use string flags: one value from the UI, passed as a list.
_USD_LIST_FLAGS: frozenset[str] = frozenset({"convertMaterialsTo"})
# Flags without value: set only when on.
_USD_SWITCH_FLAGS: frozenset[str] = frozenset({"renderableOnly", "defaultCameras"})


def _export_usd(
    file_path: Path,
    selection_only: bool,
    options: dict | None = None,
    frame_start: int | None = None,
    frame_end: int | None = None,
    frame_step: float | None = None,
) -> bool:
    if not _load_usd_plugin():
        log.error("USD export: Maya USD plugin unavailable (tried mayaUsdPlugin)")
        return False
    path_fwd = str(file_path).replace("\\", "/")
    # .usda -> ascii text, .usdc / .usd -> binary crate (standard, compact).
    usd_format = "usda" if file_path.suffix.lower() == ".usda" else "usdc"
    o = options or {}
    kwargs: dict = {"file": path_fwd, "defaultUSDFormat": usd_format}
    if selection_only:
        kwargs["selection"] = True
    # Animated export: time samples over the range into this single file.
    if frame_start is not None and frame_end is not None:
        kwargs["frameRange"] = (float(frame_start), float(frame_end))
        if frame_step and float(frame_step) != 1.0:
            kwargs["frameStride"] = float(frame_step)

    # Pass known flags straight through (keys are the real mayaUSDExport flag names).
    for key, val in o.items():
        if key in _USD_BOOL_FLAGS:
            kwargs[key] = 1 if bool(val) else 0
        elif key in _USD_STR_FLAGS:
            sval = str(val).strip()
            if sval:
                kwargs[key] = sval
        elif key in _USD_LIST_FLAGS:
            sval = str(val).strip()
            if sval and sval != "none":
                kwargs[key] = [sval]
        elif key in _USD_SWITCH_FLAGS and bool(val):
            kwargs[key] = True

    # Preserve Flux defaults when the UI did not provide them.
    kwargs.setdefault("exportUVs", 1)
    kwargs.setdefault("exportSkels", "none")
    kwargs.setdefault("defaultMeshScheme", "none")

    # An older mayaUsd refuses a flag it does not know ("Invalid flag 'x'"): drop that
    # flag and try again rather than failing the whole export.
    import re as _re
    for _ in range(8):
        try:
            cmds.mayaUSDExport(**kwargs)  # type: ignore[union-attr]
            return True
        except TypeError as exc:
            m = _re.search(r"[Ii]nvalid flag '?(\w+)'?", str(exc))
            flag = m.group(1) if m else None
            if not flag or flag not in kwargs or flag in ("file", "selection"):
                log.error("USD export failed: %s", exc)
                return False
            log.warning("USD export: option %s inconnue de ce mayaUsd, ignoree", flag)
            kwargs.pop(flag)
        except Exception as exc:
            log.error("USD export failed: %s", exc)
            return False
    log.error("USD export failed: too many unknown options")
    return False


# ── shared export core ────────────────────────────────────────────────────────

def _do_export(
    file_path: str | Path,
    extension: str,
    selection_only: bool,
    frame_start: int | None,
    frame_end: int | None,
    options: dict | None,
    frame_step: float | None = None,
) -> Path | None:
    ext = _normalise_ext(extension).lower()
    out = Path(file_path).with_suffix(ext)
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        if ext == ".abc":
            return out if _export_abc(out, selection_only, frame_start, frame_end, options, frame_step) else None

        if ext in _USD_EXTS:
            return out if _export_usd(out, selection_only, options, frame_start, frame_end, frame_step) else None

        if ext == ".fbx":
            return out if _export_fbx(out, selection_only, options) else None

        if ext == ".obj":
            if not _ensure_plugin("objExport"):
                log.error("OBJ export: 'objExport' plugin could not be loaded")
                return None
            opts_str = _obj_options_str(options)
            if selection_only:
                cmds.file(str(out), force=True, type="OBJexport", options=opts_str, exportSelected=True)  # type: ignore[union-attr]
            else:
                cmds.file(str(out), force=True, type="OBJexport", options=opts_str, exportAll=True)  # type: ignore[union-attr]
            log.info("Exported (OBJ) → %s", out.name)
            return out

        # mayaAscii / mayaBinary
        file_type = _FILE_TYPES.get(ext)
        if file_type is None:
            log.error("Unsupported export extension: %s", ext)
            return None
        scene_kwargs = _maya_scene_kwargs(options)
        if selection_only:
            cmds.file(str(out), force=True, type=file_type, exportSelected=True, **scene_kwargs)  # type: ignore[union-attr]
        else:
            cmds.file(str(out), force=True, type=file_type, exportAll=True, **scene_kwargs)  # type: ignore[union-attr]
        log.info("Exported %s → %s", "selection" if selection_only else "scene", out.name)
        return out
    except Exception as exc:
        log.error("export failed for %s: %s", out.name, exc)
        return None


# ── public API ────────────────────────────────────────────────────────────────

# Formats that carry an animation range inside ONE file (time samples).
_ANIM_EXTS: frozenset[str] = frozenset({".abc", ".usd", ".usda", ".usdc"})


def export_selection(
    file_path: str | Path,
    extension: str,
    frame_start: int | None = None,
    frame_end: int | None = None,
    options: dict | None = None,
    frame_step: float | None = None,
) -> Path | None:
    """Export the current Maya selection to *file_path*.

    Supported extensions: .mb .ma .abc .fbx .obj .usd .usda .usdc
    frame_start/frame_end/frame_step apply to .abc and USD (one animated file);
    *options* is the per-format option dict (see module docstring). Returns the
    exported path, None on failure.
    """
    if not _IN_MAYA:
        log.error("export_selection: not running inside Maya")
        return None
    return _do_export(file_path, extension, True, frame_start, frame_end, options, frame_step)


def export_scene(
    file_path: str | Path,
    extension: str,
    frame_start: int | None = None,
    frame_end: int | None = None,
    options: dict | None = None,
    frame_step: float | None = None,
) -> Path | None:
    """Export the entire Maya scene to *file_path*.

    Supported extensions: .mb .ma .abc .fbx .obj .usd .usda .usdc
    frame_start/frame_end/frame_step apply to .abc and USD (one animated file);
    *options* is the per-format option dict (see module docstring). Returns the
    exported path, None on failure.
    """
    if not _IN_MAYA:
        log.error("export_scene: not running inside Maya")
        return None
    return _do_export(file_path, extension, False, frame_start, frame_end, options, frame_step)


def run_publish_export(
    file_path: str,
    extension: str,
    scope: str,
    result_path: str,
    frame_start: int | None = None,
    frame_end: int | None = None,
    options_b64: str = "",
    frame_step: float | None = None,
) -> None:
    """Export for the Flux publisher and persist a JSON result envelope.

    Runs inside Maya. Maya is a separate process from the Flux hub, so its log
    messages are otherwise invisible to the user. This captures every 'flux.*'
    log record emitted during the export and writes
    ``{ok, path, logs:[{level,msg}]}`` to *result_path*, letting the hub surface
    the real failure reason (e.g. a missing plugin) in the Flux console.

    *scope* is 'scene' for a full-scene export, anything else exports the selection.
    *options_b64* is base64(JSON) of the per-format option dict (empty = defaults).
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

    # Decode per-format options (base64(JSON)). Never let a bad payload abort the export.
    options: dict | None = None
    if options_b64:
        try:
            import base64
            options = json.loads(base64.b64decode(options_b64).decode("utf-8"))
        except Exception as exc:
            records.append({"level": "WARNING", "msg": f"could not decode export options: {exc!r}"})

    result: Path | None = None
    try:
        export_fn = export_scene if scope == "scene" else export_selection
        if extension in _ANIM_EXTS and frame_start is not None and frame_end is not None:
            result = export_fn(file_path, extension, frame_start=frame_start, frame_end=frame_end,
                               options=options, frame_step=frame_step)
        else:
            result = export_fn(file_path, extension, options=options)
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
