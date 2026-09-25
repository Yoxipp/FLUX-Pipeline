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
    # Creating the shader copy selects it: keep the artist's selection for the export.
    picked = cmds.ls(selection=True, long=True) or []
    stand_in = _stand_in_for_default_material()
    try:
        cmds.select(picked, replace=True) if picked else cmds.select(clear=True)
        try:
            cmds.mayaUSDExport(**opts)
        except TypeError:
            # Older mayaUsd: drop the flags it does not know rather than failing the export.
            for flag in ("materialsScopeName", "exportBlendShapes", "defaultUSDFormat"):
                opts.pop(flag, None)
            cmds.mayaUSDExport(**opts)
    finally:
        _restore_default_material(stand_in)
        cmds.select(picked, replace=True) if picked else cmds.select(clear=True)
    log.info("look export: %s (%s)", out_path, "selection" if selection else "scene")
    return out_path


def _is_default_node(node: str) -> bool:
    return bool(cmds.ls(node, defaultNodes=True))


def _copy_shader(src: str) -> str:
    """A new node of *src*'s type carrying its values and inputs (Maya's default
    shaders are internal nodes it refuses to duplicate). Textures stay connected."""
    dst = cmds.shadingNode(cmds.nodeType(src), asShader=True, name=f"{src}_flux")
    for attr in cmds.listAttr(src, settable=True, scalar=True) or []:
        try:
            if cmds.getAttr(f"{dst}.{attr}", settable=True):
                cmds.setAttr(f"{dst}.{attr}", cmds.getAttr(f"{src}.{attr}"))
        except (RuntimeError, ValueError, TypeError):
            continue
    for attr in cmds.listAttr(src, settable=True) or []:
        try:
            if "." in attr or not cmds.attributeQuery(attr, node=src, usedAsColor=True):
                continue
            cmds.setAttr(f"{dst}.{attr}", *cmds.getAttr(f"{src}.{attr}")[0], type="double3")
        except (RuntimeError, ValueError, TypeError):
            continue
    pairs = cmds.listConnections(src, source=True, destination=False,
                                 connections=True, plugs=True) or []
    for dst_plug, src_plug in zip(pairs[0::2], pairs[1::2]):
        attr = dst_plug.split(".", 1)[1]
        if attr == "message":
            continue
        try:
            cmds.connectAttr(src_plug, f"{dst}.{attr}", force=True)
        except RuntimeError:
            continue
    return dst


def _stand_in_for_default_material() -> list[dict]:
    """Plug a real copy of Maya's default shaders into their shading groups for the export.

    mayaUSDExport skips default shader nodes (lambert1, standardSurface1): a mesh on
    them, even recoloured, publishes an EMPTY Material. The shading group (and so the
    published material name) stays; only its surface shader is swapped, and
    ``_restore_default_material`` plugs the original back.
    """
    swaps: list[dict] = []
    try:
        for sg in cmds.ls(type="shadingEngine") or []:
            if not cmds.sets(sg, query=True):
                continue
            plugs = cmds.listConnections(f"{sg}.surfaceShader", source=True, plugs=True) or []
            if not plugs:
                continue
            shader = plugs[0].split(".", 1)[0]
            if not _is_default_node(shader):
                continue
            swap = {"sg": sg, "plug": plugs[0], "copy": None}
            swaps.append(swap)
            swap["copy"] = _copy_shader(shader)
            cmds.connectAttr(f"{swap['copy']}.outColor", f"{sg}.surfaceShader", force=True)
            log.info("look export: shader par defaut %s de %s exporte via une copie", shader, sg)
    except Exception:
        _restore_default_material(swaps)      # never leave the scene half swapped
        raise
    return swaps


def _restore_default_material(swaps: list[dict]) -> None:
    """Undo ``_stand_in_for_default_material``: the artist's scene is left as it was."""
    for swap in swaps or []:
        try:
            cmds.connectAttr(swap["plug"], f"{swap['sg']}.surfaceShader", force=True)
        finally:
            if swap["copy"] and cmds.objExists(swap["copy"]):
                cmds.delete(swap["copy"])


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
