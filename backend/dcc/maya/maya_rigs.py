# maya_rigs.py — base Camera Rig and Light Rig of the Flux shelf (ADR 0023 points 12, 13).
#
# Camera Rig (2026-09-26): the maintainer's rig, imported from resources/rigs/maya/flux_cam_rig.ma
#   (Flux_Cam_Rig > Cam + Ctrl_Cam controls + DO_NOT_TOUCH guides, settings on
#   Ctrl_Setting_Cam). The file holds the rig only: no default cameras, no scene globals
#   (render / colour settings), no machine path. A second rig goes into its own namespace.
# Light Rig (2026-09-24): Maya native 3 points + dome, under LIGHT_RIG:
#   key / fill / rim directional lights (scale independent) + a dome: aiSkyDomeLight when
#   Arnold (mtoa) is loaded, else an ambient light.
# Every top node is tagged flux_rig = "camera" / "light" (same idea as the flux_* import
# tags of maya_update.py). Runs inside Maya, called by the Flux shelf buttons.

from __future__ import annotations

from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)

try:
    import maya.cmds as cmds  # type: ignore[import]
    _IN_MAYA = True
except ImportError:
    cmds = None
    _IN_MAYA = False

CAM_RIG_FILE = Path(__file__).resolve().parents[2] / "resources" / "rigs" / "maya" / "flux_cam_rig.ma"
CAM_RIG_ROOT = "Flux_Cam_Rig"
CAM_RIG_NAMESPACE = "CAM"
# name, rotation (x, y, z), intensity: key high front-left, fill low opposite, rim behind.
THREE_POINTS = (("key", (-40.0, 35.0, 0.0), 1.0),
                ("fill", (-15.0, -60.0, 0.0), 0.35),
                ("rim", (-30.0, 160.0, 0.0), 0.7))
DOME_INTENSITY = 0.25


def _tag(node: str, kind: str) -> None:
    if not cmds.attributeQuery("flux_rig", node=node, exists=True):
        cmds.addAttr(node, longName="flux_rig", dataType="string")
    cmds.setAttr(f"{node}.flux_rig", kind, type="string")


def _chunk(func):
    """One undo step per rig."""
    def wrapper(*args, **kwargs):
        if not _IN_MAYA and cmds is None:
            raise RuntimeError("Maya requis : lance ce bouton depuis la shelf Flux de Maya")
        cmds.undoInfo(openChunk=True)
        try:
            return func(*args, **kwargs)
        finally:
            cmds.undoInfo(closeChunk=True)
    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


@_chunk
def create_camera_rig() -> dict:
    """Import the FLUX Camera Rig file. Returns the root, the camera and the namespace."""
    if not CAM_RIG_FILE.is_file():
        raise RuntimeError(f"Camera Rig introuvable : {CAM_RIG_FILE}")
    # First rig keeps the clean names; the next ones get CAM:, CAM1: ... so nothing is renamed.
    namespace = CAM_RIG_NAMESPACE if cmds.objExists(CAM_RIG_ROOT) else ""
    kwargs = {"namespace": namespace, "mergeNamespacesOnClash": False} if namespace else {}
    new_nodes = cmds.file(str(CAM_RIG_FILE).replace("\\", "/"), i=True, type="mayaAscii",
                          ignoreVersion=True, returnNewNodes=True, **kwargs) or []
    roots = [n for n in new_nodes if n.split("|")[-1].split(":")[-1] == CAM_RIG_ROOT]
    if not roots:
        raise RuntimeError("Camera Rig importe sans son groupe Flux_Cam_Rig")
    root = roots[0]
    shapes = cmds.ls(new_nodes, type="camera", long=True) or []
    camera = (cmds.listRelatives(shapes[0], parent=True, fullPath=True) or [""])[0] if shapes else ""
    _tag(root, "camera")
    cmds.select(root, replace=True)
    log.info("Camera rig imported: %s", root)
    return {"root": root, "camera": camera, "namespace": namespace}


def _arnold_loaded() -> bool:
    try:
        return bool(cmds.pluginInfo("mtoa", query=True, loaded=True))
    except Exception:           # noqa: BLE001 - unknown plug-in = not loaded
        return False


def _dome(name: str) -> tuple[str, str]:
    """(transform, kind) of the dome: Arnold sky dome when mtoa is loaded, else ambient."""
    if _arnold_loaded():
        shape = cmds.shadingNode("aiSkyDomeLight", asLight=True, name=f"{name}_domeShape")
        transform = (cmds.listRelatives(shape, parent=True) or [shape])[0]
        transform = cmds.rename(transform, f"{name}_dome")
        shape = (cmds.listRelatives(transform, shapes=True) or [shape])[0]
        cmds.setAttr(f"{shape}.intensity", DOME_INTENSITY)
        return transform, "aiSkyDomeLight"
    shape = cmds.ambientLight(name=f"{name}_dome", intensity=DOME_INTENSITY)
    return (cmds.listRelatives(shape, parent=True) or [shape])[0], "ambientLight"


@_chunk
def create_light_rig(name: str = "LIGHT_RIG") -> dict:
    """Key / fill / rim + dome under one group. Returns the created node names."""
    group = cmds.group(empty=True, name=name)
    lights = {}
    for role, rotation, intensity in THREE_POINTS:
        shape = cmds.directionalLight(name=f"{name}_{role}", intensity=intensity)
        transform = (cmds.listRelatives(shape, parent=True) or [shape])[0]
        transform = cmds.parent(transform, group)[0]
        cmds.setAttr(f"{transform}.rotate", *rotation, type="double3")
        lights[role] = transform
    dome, dome_kind = _dome(name)
    lights["dome"] = cmds.parent(dome, group)[0]
    _tag(group, "light")
    cmds.select(group, replace=True)
    log.info("Light rig created: %s (dome %s)", group, dome_kind)
    return {"group": group, "dome_kind": dome_kind, **lights}
