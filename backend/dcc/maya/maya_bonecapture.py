# maya_bonecapture.py — export a skinned mesh's bone capture (skin weights) from
# Maya as an FBX, for the rig toolbox. Runs inside Maya (Python 3.10).
#
# Why FBX: it is Maya-native (no pxr needed in-process, unlike the USD light
# export which round-trips through the Flux backend to author). The resulting FBX
# carries the skeleton + skin binding, and the Flux Houdini shelf tool "Import
# KineFX" turns it into a KineFX `boneCapture` point attribute (joints matched by
# name). For a USD boneCapture instead, use the Publisher's light USD export with
# the "Skin weights (boneCapture)" box checked.
#
# Rig-toolbox button command (Python):
#     import dcc.maya.maya_bonecapture as bc; bc.export_bonecapture()

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


def _resolve_skinned_mesh(mesh: str | None) -> str | None:
    """Return the full DAG path of a skinned mesh transform (arg or selection)."""
    if mesh is None:
        sel = cmds.ls(selection=True, long=True, type="transform") or []  # type: ignore[union-attr]
        meshes = [s for s in sel if cmds.listRelatives(s, shapes=True, type="mesh")]  # type: ignore[union-attr]
        if not meshes:
            cmds.warning("Flux boneCapture: sélectionne un mesh skinné.")  # type: ignore[union-attr]
            return None
        mesh = meshes[0]
    return (cmds.ls(mesh, long=True) or [mesh])[0]  # type: ignore[union-attr]


def export_bonecapture(mesh: str | None = None, out_path: str | None = None) -> str | None:
    """Export *mesh*'s skeleton + skin binding to FBX (bone capture).

    *mesh*    — skinned mesh transform; uses the selection when None.
    *out_path*— target .fbx; opens a save dialog when None.
    Returns the written path on success, None otherwise.
    """
    if not _IN_MAYA:
        log.error("export_bonecapture: not running inside Maya")
        return None

    # Reuse the light-export helpers so skin/joint discovery stays identical.
    from dcc.maya.maya_usd_light_export import _joint_chain, _skin_cluster

    mesh = _resolve_skinned_mesh(mesh)
    if mesh is None:
        return None

    skin = _skin_cluster(mesh)
    if not skin:
        cmds.warning("Flux boneCapture: pas de skinCluster sur %s." % mesh.rsplit("|", 1)[-1])  # type: ignore[union-attr]
        return None

    # Skeleton root: walk up from the first influence to the topmost joint.
    infl = cmds.skinCluster(skin, q=True, inf=True) or []  # type: ignore[union-attr]
    if not infl:
        cmds.warning("Flux boneCapture: le skinCluster %s n'a pas d'influence." % skin)  # type: ignore[union-attr]
        return None
    node = (cmds.ls(infl[0], long=True) or [infl[0]])[0]  # type: ignore[union-attr]
    while True:
        parent = cmds.listRelatives(node, parent=True, type="joint", fullPath=True)  # type: ignore[union-attr]
        if not parent:
            break
        node = parent[0]
    joints = _joint_chain(node)
    if not joints:
        cmds.warning("Flux boneCapture: aucun joint sous la racine %s." % node)  # type: ignore[union-attr]
        return None

    # Target path — save dialog when not provided.
    if out_path is None:
        res = cmds.fileDialog2(  # type: ignore[union-attr]
            fileFilter="FBX (*.fbx)", dialogStyle=2, fileMode=0,
            caption="Flux - Export boneCapture (FBX)",
        )
        if not res:
            return None
        out_path = res[0]
    out = Path(out_path).with_suffix(".fbx")

    # Select mesh + full joint chain so FBX exports the skin binding, then export
    # with skins/blendshapes/skeleton on (via the shared FBX exporter).
    prev = cmds.ls(selection=True, long=True) or []  # type: ignore[union-attr]
    try:
        cmds.select([mesh] + joints, replace=True)  # type: ignore[union-attr]
        from dcc.maya.maya_export import _export_fbx
        ok = _export_fbx(
            out, selection_only=True,
            options={
                "skins": True,
                "blend_shapes": True,
                "skeleton_definitions": True,
                "bake_animation": False,
            },
        )
    finally:
        if prev:
            cmds.select(prev, replace=True)  # type: ignore[union-attr]
        else:
            cmds.select(clear=True)  # type: ignore[union-attr]

    if not ok:
        cmds.warning("Flux boneCapture: export FBX échoué (voir la console).")  # type: ignore[union-attr]
        return None

    log.info("boneCapture exported: %s (%d joints) -> %s", mesh.rsplit("|", 1)[-1], len(joints), out.name)
    cmds.inViewMessage(  # type: ignore[union-attr]
        amg="Flux: boneCapture exporté -> <hl>%s</hl>" % out.name,
        pos="midCenter", fade=True,
    ) if hasattr(cmds, "inViewMessage") else None
    return str(out)
