# maya_usd_light_export.py — extract a skinned asset from Maya and publish it as a
# light layered UsdSkel asset (model + skel + anim joints only).
#
# Runs inside Maya (Python 3.10). Builds a features.usd_export.LightAsset from the
# scene, then hands it to publish_light_asset() which authors the layers with pxr.
# Maya has no pxr dependency here: extraction is pure maya.cmds / OpenMaya, the USD
# authoring happens in the pure core.

from __future__ import annotations

from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)

try:
    import maya.api.OpenMaya as om           # type: ignore[import]
    import maya.api.OpenMayaAnim as oma      # type: ignore[import]
    import maya.cmds as cmds                 # type: ignore[import]
    _IN_MAYA = True
except ImportError:
    om = oma = cmds = None                   # type: ignore[assignment]
    _IN_MAYA = False


def _short(name: str) -> str:
    """Leaf name of a (possibly full) DAG path."""
    return name.rsplit("|", 1)[-1].rsplit(":", 1)[-1]


def _joint_chain(root_joint: str) -> list[str]:
    """Return root_joint + all descendant joints (full DAG paths), depth-first."""
    chain = cmds.ls(root_joint, long=True) or []
    if not chain:
        return []
    root = chain[0]
    descendants = cmds.listRelatives(root, allDescendents=True, type="joint", fullPath=True) or []
    # allDescendents is deepest-first; reverse for a stable top-down order.
    return [root] + list(reversed(descendants))


def _token_paths(joints_dag: list[str]) -> list[str]:
    """Map each joint DAG path to a UsdSkel joint token path relative to the root.

    e.g. root "Root", child "Root/Hip", grandchild "Root/Hip/Knee".
    """
    from features.usd_assembler.structure.naming import sanitize_token

    root_parent = joints_dag[0].rsplit("|", 1)[0]   # DAG prefix above the root
    tokens: list[str] = []
    for dag in joints_dag:
        rel = dag[len(root_parent):].lstrip("|") if root_parent else dag.lstrip("|")
        parts = [sanitize_token(_short(p)) for p in rel.split("|") if p]
        tokens.append("/".join(parts))
    return tokens


def _matrix16(values) -> tuple:
    """Coerce a Maya 16-float matrix (row-major) into a plain tuple."""
    return tuple(float(v) for v in values)


def _skin_cluster(mesh: str) -> str | None:
    """Return the skinCluster deforming *mesh*, or None."""
    history = cmds.listHistory(mesh, pruneDagObjects=True) or []
    skins = cmds.ls(history, type="skinCluster") or []
    return skins[0] if skins else None


def _extract_skeleton(joints_dag: list[str], tokens: list[str], skin: str):
    """Return (bind_transforms, rest_transforms) parallel to joints_dag.

    bind = world-space bind pose (inverse of the skinCluster bindPreMatrix when the
    joint is an influence, else the current world matrix). rest = local matrix.
    """
    from features.usd_export.contract import SkeletonData

    # Map influence DAG -> its bindPreMatrix logical index via the skin function set.
    bind_by_dag: dict[str, tuple] = {}
    if skin:
        sel = om.MSelectionList()
        sel.add(skin)
        skin_fn = oma.MFnSkinCluster(sel.getDependNode(0))
        for dp in skin_fn.influenceObjects():
            dag = dp.fullPathName()
            logical = skin_fn.indexForInfluenceObject(dp)
            bpm = cmds.getAttr(f"{skin}.bindPreMatrix[{logical}]")
            world_bind = om.MMatrix(bpm).inverse()
            bind_by_dag[dag] = _matrix16(world_bind)

    bind_transforms: list[tuple] = []
    rest_transforms: list[tuple] = []
    for dag in joints_dag:
        if dag in bind_by_dag:
            bind_transforms.append(bind_by_dag[dag])
        else:
            bind_transforms.append(_matrix16(cmds.getAttr(f"{dag}.worldMatrix[0]")))
        rest_transforms.append(_matrix16(cmds.getAttr(f"{dag}.matrix")))

    return SkeletonData(joints=tokens, bind_transforms=bind_transforms, rest_transforms=rest_transforms)


def _extract_mesh(mesh: str, skin: str, joints_dag: list[str]):
    """Return a MeshData with geometry + full skin binding for *mesh*."""
    from features.usd_export.contract import MeshData

    mesh_short = _short(mesh)
    points_flat = cmds.xform(f"{mesh}.vtx[*]", q=True, os=True, t=True) or []
    points = [tuple(points_flat[i:i + 3]) for i in range(0, len(points_flat), 3)]

    # Face topology.
    vtx_counts: list[int] = []
    vtx_indices: list[int] = []
    face_count = cmds.polyEvaluate(mesh, face=True)
    for f in range(int(face_count)):
        verts = cmds.polyInfo(f"{mesh}.f[{f}]", faceToVertex=True)[0].split(":")[1].split()
        idx = [int(v) for v in verts]
        vtx_counts.append(len(idx))
        vtx_indices.extend(idx)

    data = MeshData(
        name=mesh_short,
        points=points,
        face_vertex_counts=vtx_counts,
        face_vertex_indices=vtx_indices,
    )
    if not skin:
        return data

    # Skin weights via OpenMaya: flat, vertex-major, one entry per influence.
    sel = om.MSelectionList()
    sel.add(skin)
    skin_fn = oma.MFnSkinCluster(sel.getDependNode(0))

    mesh_sel = om.MSelectionList()
    mesh_sel.add(mesh)
    mesh_dag = mesh_sel.getDagPath(0)
    comp = om.MFnSingleIndexedComponent().create(om.MFn.kMeshVertComponent)
    num_verts = len(points)
    om.MFnSingleIndexedComponent(comp).addElements(list(range(num_verts)))

    weights, num_inf = skin_fn.getWeights(mesh_dag, comp)

    # Influence order -> skeleton joint index.
    dag_to_index = {dag: i for i, dag in enumerate(joints_dag)}
    inf_indices: list[int] = []
    for dp in skin_fn.influenceObjects():
        dag = dp.fullPathName()
        if dag not in dag_to_index:
            log.warning("influence %s is not under the skeleton root — skipped", _short(dag))
            inf_indices.append(0)
        else:
            inf_indices.append(dag_to_index[dag])

    data.influences_per_point = int(num_inf)
    data.joint_indices = inf_indices * num_verts          # same mapping every point
    data.joint_weights = [float(w) for w in weights]      # vertex-major weight rows
    if skin:
        data.geom_bind_transform = _matrix16(cmds.getAttr(f"{skin}.geomMatrix"))
    return data


def _extract_anim(joints_dag: list[str], tokens: list[str], frame_start: int, frame_end: int):
    """Sample local transforms over the range and keep only the joints that move."""
    from features.usd_export.contract import AnimData, filter_animated_joints

    times = list(range(int(frame_start), int(frame_end) + 1))
    if len(times) < 2:
        return None

    # transforms_per_time[t][j] = local matrix of joint j at time t.
    local_per_time: list[list[tuple]] = []
    trs_per_time: list[list] = []   # decomposed (T, quat, S) per joint per time
    for t in times:
        cmds.currentTime(t, edit=True)
        row_mat: list[tuple] = []
        row_trs: list = []
        for dag in joints_dag:
            m16 = _matrix16(cmds.getAttr(f"{dag}.matrix"))
            row_mat.append(m16)
            tm = om.MTransformationMatrix(om.MMatrix(m16))
            tr = tm.translation(om.MSpace.kTransform)
            q = tm.rotation(asQuaternion=True)
            s = tm.scale(om.MSpace.kTransform)
            row_trs.append(((tr[0], tr[1], tr[2]), (q[0], q[1], q[2], q[3]), (s[0], s[1], s[2])))
        local_per_time.append(row_mat)
        trs_per_time.append(row_trs)

    animated = filter_animated_joints(tokens, local_per_time)
    if not animated:
        return None
    keep = [tokens.index(a) for a in animated]

    translations = [[trs_per_time[ti][j][0] for j in keep] for ti in range(len(times))]
    rotations    = [[trs_per_time[ti][j][1] for j in keep] for ti in range(len(times))]
    scales       = [[trs_per_time[ti][j][2] for j in keep] for ti in range(len(times))]
    return AnimData(
        joints=animated,
        times=[float(t) for t in times],
        translations=translations,
        rotations=rotations,
        scales=scales,
    )


def _build_light_asset(
    asset: str,
    mesh: str | None,
    root_joint: str | None,
    frame_start: int | None,
    frame_end: int | None,
):
    """Extract a LightAsset from the Maya scene. Returns None (and logs) on error."""
    from features.usd_export.contract import LightAsset

    # Resolve mesh from arg or selection.
    if mesh is None:
        sel = cmds.ls(selection=True, long=True, type="transform") or []
        meshes = [s for s in sel if cmds.listRelatives(s, shapes=True, type="mesh")]
        if not meshes:
            log.error("light export: select a skinned mesh (none found in selection)")
            return None
        mesh = meshes[0]
    mesh = (cmds.ls(mesh, long=True) or [mesh])[0]

    skin = _skin_cluster(mesh)
    if skin is None:
        log.error("light export: no skinCluster on %s", _short(mesh))
        return None

    # Resolve the skeleton root: walk up from the first influence to the top joint.
    if root_joint is None:
        infl = cmds.skinCluster(skin, q=True, inf=True) or []
        if not infl:
            log.error("light export: skinCluster %s has no influences", skin)
            return None
        node = (cmds.ls(infl[0], long=True) or [infl[0]])[0]
        while True:
            parent = cmds.listRelatives(node, parent=True, type="joint", fullPath=True)
            if not parent:
                break
            node = parent[0]
        root_joint = node

    joints_dag = _joint_chain(root_joint)
    if not joints_dag:
        log.error("light export: no joints under root %s", root_joint)
        return None
    tokens = _token_paths(joints_dag)

    if frame_start is None:
        frame_start = int(cmds.playbackOptions(q=True, min=True))
    if frame_end is None:
        frame_end = int(cmds.playbackOptions(q=True, max=True))

    skeleton = _extract_skeleton(joints_dag, tokens, skin)
    mesh_data = _extract_mesh(mesh, skin, joints_dag)
    anim = _extract_anim(joints_dag, tokens, frame_start, frame_end)
    return LightAsset(asset=asset, skeleton=skeleton, meshes=[mesh_data], anim=anim)


def run_light_export(
    asset: str,
    result_path: str,
    mesh: str | None = None,
    root_joint: str | None = None,
    frame_start: int | None = None,
    frame_end: int | None = None,
) -> None:
    """Extract a light asset from Maya and write a JSON envelope to *result_path*.

    Writes ``{ok, asset:<LightAsset dict|null>, logs:[{level,msg}]}``. USD authoring
    is NOT done here (Maya has no reliable pxr): the Flux backend reads this envelope,
    rebuilds the LightAsset and publishes it. Called via commandPort by the hub.
    """
    import dataclasses
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

    data = None
    try:
        if not _IN_MAYA:
            log.error("run_light_export: not running inside Maya")
        else:
            light = _build_light_asset(asset, mesh, root_joint, frame_start, frame_end)
            if light is not None:
                data = dataclasses.asdict(light)
    except Exception as exc:  # pragma: no cover - defensive
        records.append({"level": "ERROR", "msg": f"light export raised: {exc!r}"})
    finally:
        flux_root.removeHandler(collector)

    try:
        with open(result_path, "w", encoding="utf-8") as fh:
            json.dump({"ok": data is not None, "asset": data, "logs": records}, fh)
    except OSError as exc:
        log.error("run_light_export: cannot write result envelope: %s", exc)
