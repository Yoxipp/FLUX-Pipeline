# maya_rigs.py — base Camera Rig and Light Rig of the Flux shelf (ADR 0023 points 12, 13).
#
# Both rigs are the maintainer's (2026-09-26), shipped as Maya ASCII files in resources/rigs/maya/
# and imported by the CAM / LIGHT shelf buttons:
#   flux_cam_rig.ma   Flux_Cam_Rig > Cam + Ctrl_Cam controls + DO_NOT_TOUCH guides,
#                     camera settings on Ctrl_Setting_Cam.
#   flux_light_rig.ma Flux_Light_Rig > Light_Key / Light_Fill / Light_Rim (directional)
#                     + Light_Dom (ambient).
# The files hold the rig only (exported from Maya 2024): no default cameras, no scene
# globals (render / colour settings), no machine path. The first rig keeps its names, the
# next ones go into a namespace (CAM:, LIGHT:) so nothing gets renamed. Every root is
# tagged flux_rig = "camera" / "light" (same idea as the flux_* import tags of
# maya_update.py). Runs inside Maya, called by the Flux shelf buttons.

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

_RIGS_DIR = Path(__file__).resolve().parents[2] / "resources" / "rigs" / "maya"
CAM_RIG_FILE = _RIGS_DIR / "flux_cam_rig.ma"
LIGHT_RIG_FILE = _RIGS_DIR / "flux_light_rig.ma"
CAM_RIG_ROOT = "Flux_Cam_Rig"
LIGHT_RIG_ROOT = "Flux_Light_Rig"


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


def _import_rig(path: Path, root_name: str, namespace: str, kind: str) -> tuple[str, list[str], str]:
    """Import one rig file. Returns (root, new nodes, namespace used)."""
    if not path.is_file():
        raise RuntimeError(f"Rig introuvable : {path}")
    ns = namespace if cmds.objExists(root_name) else ""
    kwargs = {"namespace": ns, "mergeNamespacesOnClash": False} if ns else {}
    new_nodes = cmds.file(str(path).replace("\\", "/"), i=True, type="mayaAscii",
                          ignoreVersion=True, returnNewNodes=True, **kwargs) or []
    roots = [n for n in new_nodes if n.split("|")[-1].split(":")[-1] == root_name]
    if not roots:
        raise RuntimeError(f"Rig importe sans son groupe {root_name}")
    _tag(roots[0], kind)
    cmds.select(roots[0], replace=True)
    log.info("%s rig imported: %s", kind, roots[0])
    return roots[0], new_nodes, ns


@_chunk
def create_camera_rig() -> dict:
    """Import the FLUX Camera Rig. Returns the root, the camera and the namespace."""
    root, new_nodes, ns = _import_rig(CAM_RIG_FILE, CAM_RIG_ROOT, "CAM", "camera")
    shapes = cmds.ls(new_nodes, type="camera", long=True) or []
    camera = (cmds.listRelatives(shapes[0], parent=True, fullPath=True) or [""])[0] if shapes else ""
    return {"root": root, "camera": camera, "namespace": ns}


@_chunk
def create_light_rig() -> dict:
    """Import the FLUX Light Rig. Returns the root, its lights and the namespace."""
    root, new_nodes, ns = _import_rig(LIGHT_RIG_FILE, LIGHT_RIG_ROOT, "LIGHT", "light")
    shapes = cmds.ls(new_nodes, lights=True, long=True) or []
    lights = [p for s in shapes for p in (cmds.listRelatives(s, parent=True, fullPath=True) or [])]
    return {"root": root, "lights": lights, "namespace": ns}
