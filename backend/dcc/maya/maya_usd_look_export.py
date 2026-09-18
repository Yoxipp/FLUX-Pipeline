# maya_usd_look_export.py — export the materials of a Maya scene to a throwaway USD.
#
# Runs INSIDE Maya (commandPort), like maya_usd_light_export: Maya writes a temp
# .usda with mayaUSDExport, the FLUX backend rewrites it into the look department
# layer with pxr (features/usd_export/look_export.py, ADR 0019 A1b).
#
# Maya has no reliable pxr: nothing here imports pxr.

from __future__ import annotations

from core.logger import get_logger

log = get_logger(__name__)

try:
    from maya import cmds
    _IN_MAYA = True
except ImportError:                       # pragma: no cover - outside Maya
    cmds = None                           # type: ignore[assignment]
    _IN_MAYA = False


def _ensure_plugin() -> None:
    if not cmds.pluginInfo("mayaUsdPlugin", query=True, loaded=True):
        cmds.loadPlugin("mayaUsdPlugin")


def export_look(out_path: str, *, scope: str = "scene") -> str | None:
    """Write the scene (or the selection) to *out_path* with its materials.

    Geometry rides along on purpose: the backend reads the bindings off the meshes,
    then keeps only the materials and the bindings (the file itself is thrown away).
    Returns the written path, or None.
    """
    _ensure_plugin()
    selection = scope == "selection"
    scene = cmds.file(query=True, sceneName=True) or "untitled"
    if selection and not cmds.ls(selection=True):
        log.error("look export: rien de selectionne dans Maya (scene : %s)", scene)
        return None
    if not cmds.ls(type="mesh"):
        log.error("look export: aucun mesh dans la scene Maya %s", scene)
        return None

    opts: dict = {
        "file": out_path,
        "selection": selection,
        "shadingMode": "useRegistry",
        "convertMaterialsTo": ["UsdPreviewSurface"],
        "exportUVs": True,
        "exportDisplayColor": False,
        "exportSkels": "none",
        "exportSkin": "none",
        "exportBlendShapes": False,
        "defaultUSDFormat": "usda",
        "materialsScopeName": "mtl",
    }
    try:
        cmds.mayaUSDExport(**opts)
    except TypeError:
        # Older mayaUsd: drop the flags it does not know rather than failing the export.
        for flag in ("materialsScopeName", "exportBlendShapes", "defaultUSDFormat"):
            opts.pop(flag, None)
        cmds.mayaUSDExport(**opts)
    log.info("look export: %s (%s)", out_path, "selection" if selection else "scene")
    return out_path


def run_look_export(out_path: str, result_path: str, scope: str = "scene") -> None:
    """Export the look to *out_path* and write a JSON envelope to *result_path*.

    Envelope: ``{ok, usd: <path|null>, logs: [{level, msg}]}`` — same shape as the
    light export, so the hub mirrors Maya's logs into the FLUX console.
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

    written = None
    try:
        if not _IN_MAYA:
            log.error("run_look_export: not running inside Maya")
        else:
            written = export_look(out_path, scope=scope)
    except Exception as exc:              # pragma: no cover - defensive
        records.append({"level": "ERROR", "msg": f"look export raised: {exc!r}"})
    finally:
        flux_root.removeHandler(collector)

    try:
        with open(result_path, "w", encoding="utf-8") as fh:
            json.dump({"ok": written is not None, "usd": written, "logs": records}, fh)
    except OSError as exc:
        log.error("run_look_export: cannot write result envelope: %s", exc)
