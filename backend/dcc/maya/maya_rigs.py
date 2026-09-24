# maya_rigs.py — base Camera Rig and Light Rig of the Flux shelf (ADR 0023 points 12, 13).
#
# Camera Rig (2026-09-24): CAM_RIG_root > CAM_RIG_pan > CAM_RIG_tilt > CAM_RIG_cam.
#   root = placement (translate / rotate), pan = rotate Y, tilt = rotate X (+ roll Z),
#   camera: focal 35 mm, film back 36 x 24 mm, clip 0.1 / 10000. The camera itself is
#   locked: the controls carry the animation.
# Light Rig (2026-09-24): Maya native 3 points + dome, under LIGHT_RIG:
#   key / fill / rim directional lights (scale independent) + a dome: aiSkyDomeLight when
#   Arnold (mtoa) is loaded, else an ambient light.
# Every top node is tagged flux_rig = "camera" / "light" (same idea as the flux_* import
# tags of maya_update.py). Runs inside Maya, called by the Flux shelf buttons.

from __future__ import annotations

from core.logger import get_logger

log = get_logger(__name__)

try:
    import maya.cmds as cmds  # type: ignore[import]
    _IN_MAYA = True
except ImportError:
    cmds = None
    _IN_MAYA = False

INCH = 25.4
CAMERA = {"focalLength": 35.0, "horizontalFilmAperture": 36.0 / INCH,
          "verticalFilmAperture": 24.0 / INCH, "nearClipPlane": 0.1, "farClipPlane": 10000.0}
# name, rotation (x, y, z), intensity: key high front-left, fill low opposite, rim behind.
THREE_POINTS = (("key", (-40.0, 35.0, 0.0), 1.0),
                ("fill", (-15.0, -60.0, 0.0), 0.35),
                ("rim", (-30.0, 160.0, 0.0), 0.7))
DOME_INTENSITY = 0.25


def _tag(node: str, kind: str) -> None:
    if not cmds.attributeQuery("flux_rig", node=node, exists=True):
        cmds.addAttr(node, longName="flux_rig", dataType="string")
    cmds.setAttr(f"{node}.flux_rig", kind, type="string")


def _lock(node: str, attrs: list[str]) -> None:
    for attr in attrs:
        cmds.setAttr(f"{node}.{attr}", lock=True, keyable=False, channelBox=False)


def _control(name: str, radius: float, parent: str | None = None) -> str:
    """NURBS circle control (lying flat), parented under *parent*."""
    ctrl = cmds.circle(name=name, normal=(0, 1, 0), radius=radius, constructionHistory=False)[0]
    if parent:
        ctrl = cmds.parent(ctrl, parent)[0]
    return ctrl


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
def create_camera_rig(name: str = "CAM_RIG") -> dict:
    """Root > Pan > Tilt > Cam. Returns the created node names."""
    root = _control(f"{name}_root", 3.0)
    pan = _control(f"{name}_pan", 2.0, root)
    tilt = _control(f"{name}_tilt", 1.2, pan)
    cam, shape = cmds.camera(name=f"{name}_cam")
    cam = cmds.parent(cam, tilt)[0]
    shape = (cmds.listRelatives(cam, shapes=True, fullPath=False) or [shape])[0]
    for attr, value in CAMERA.items():
        cmds.setAttr(f"{shape}.{attr}", value)
    _lock(pan, ["tx", "ty", "tz", "rx", "rz", "sx", "sy", "sz"])          # pan: rotate Y only
    _lock(tilt, ["tx", "ty", "tz", "ry", "sx", "sy", "sz"])               # tilt: rotate X, roll Z
    _lock(cam, ["tx", "ty", "tz", "rx", "ry", "rz", "sx", "sy", "sz"])    # animate the controls
    _lock(root, ["sx", "sy", "sz"])
    _tag(root, "camera")
    cmds.select(root, replace=True)
    log.info("Camera rig created: %s", root)
    return {"root": root, "pan": pan, "tilt": tilt, "camera": cam, "shape": shape}


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
