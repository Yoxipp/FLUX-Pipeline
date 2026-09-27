# maya_usd_presets.py — what each USD preset of the Publisher takes from a Maya scene
# (2026-09-26, ADR 0034). Runs INSIDE Maya (Python 3.10), pxr-free: it fills the
# features.usd_export contract, the FLUX backend authors the USD.
#
#   model : the meshes only (points, faces, normals, UVs, color sets). No skeleton,
#           no skin, no material. Nothing to export = error.
#   rig   : the skeleton(s) in a neutral rest pose (skinCluster bind pose, or the
#           controllers set to 0) + the skin weights of the meshes it deforms.
#   anim  : the rotations of the joints that move (translations of the root motion
#           as an option), baked per frame then reduced WITHOUT changing the motion,
#           smooth or step (held keys).
# The preview (maya_usd_preview) lists what each preset would take, with the same
# scene sweeps as the export.

from __future__ import annotations

from contextlib import contextmanager

from core.logger import get_logger

log = get_logger(__name__)

try:
    import maya.api.OpenMaya as om           # type: ignore[import]
    import maya.api.OpenMayaAnim as oma      # type: ignore[import]
    import maya.cmds as cmds                 # type: ignore[import]
    _IN_MAYA = True
except ImportError:                          # pragma: no cover - outside Maya
    om = oma = cmds = None                   # type: ignore[assignment]
    _IN_MAYA = False

# Channels reset to find the neutral pose of a rig ("ctrls a 0").
_CTRL_DEFAULTS = {
    "translateX": 0.0, "translateY": 0.0, "translateZ": 0.0,
    "rotateX": 0.0, "rotateY": 0.0, "rotateZ": 0.0,
    "scaleX": 1.0, "scaleY": 1.0, "scaleZ": 1.0,
}


class PresetError(RuntimeError):
    """What the artist must fix in the scene (said in the Publisher as is)."""


# ── scene sweeps (shared with the preview) ──────────────────────────────────────

def _short(name: str) -> str:
    return name.rsplit("|", 1)[-1].rsplit(":", 1)[-1]


def _long(node: str) -> str:
    return (cmds.ls(node, long=True) or [node])[0]


def _selected() -> list[str]:
    return cmds.ls(selection=True, long=True, objectsOnly=True) or []


def mesh_transforms(scope: str, root: str | None = None) -> list[str]:
    """Mesh transforms (full paths) of the scene, of the selection (and everything
    under it) or under *root*. Intermediate shapes (skin "Orig") never count."""
    if root:
        shapes = cmds.listRelatives(root, allDescendents=True, type="mesh", fullPath=True) or []
    elif scope == "scene":
        shapes = cmds.ls(type="mesh", long=True) or []
    else:
        shapes = []
        for node in _selected():
            if cmds.nodeType(node) == "mesh":
                shapes.append(node)
            shapes += cmds.listRelatives(node, allDescendents=True, type="mesh", fullPath=True) or []
    out: list[str] = []
    for shp in shapes:
        if cmds.getAttr(shp + ".intermediateObject"):
            continue
        for tr in cmds.listRelatives(shp, parent=True, fullPath=True) or []:
            if tr not in out:
                out.append(tr)
    return out


def top_joint(joint: str) -> str:
    node = _long(joint)
    while True:
        parent = cmds.listRelatives(node, parent=True, type="joint", fullPath=True)
        if not parent:
            return node
        node = parent[0]


def joint_chain(root_joint: str) -> list[str]:
    """root + every joint under it, parents before children."""
    root = _long(root_joint)
    descendants = cmds.listRelatives(root, allDescendents=True, type="joint", fullPath=True) or []
    return [root] + list(reversed(descendants))


def scoped_joints(scope: str, root: str | None = None) -> list[str]:
    """Joints of the scene, of the selection (selected joints and every joint under a
    selected node) or under *root*."""
    if root:
        found = ([_long(root)] if cmds.nodeType(root) == "joint" else []) + (
            cmds.listRelatives(root, allDescendents=True, type="joint", fullPath=True) or [])
    elif scope == "scene":
        found = cmds.ls(type="joint", long=True) or []
    else:
        found = []
        for node in _selected():
            if cmds.nodeType(node) == "joint":
                found.append(node)
            found += cmds.listRelatives(node, allDescendents=True, type="joint", fullPath=True) or []
    seen: set[str] = set()
    return [j for j in found if not (j in seen or seen.add(j))]


def skeleton_roots(joints: list[str]) -> list[str]:
    """Top joint of each chain the joints belong to, in first-seen order."""
    roots: list[str] = []
    for j in joints:
        top = top_joint(j)
        if top not in roots:
            roots.append(top)
    return roots


def joint_tokens(joints: list[str]) -> list[str]:
    """UsdSkel joint paths ("Root/Hip/Knee"), relative to each chain's top joint, so the
    rig and the anim of one character always name a joint the same way."""
    from features.usd_assembler.structure.naming import sanitize_token

    out: list[str] = []
    for dag in joints:
        prefix = top_joint(dag).rsplit("|", 1)[0]
        rel = dag[len(prefix):].lstrip("|")
        out.append("/".join(sanitize_token(_short(p)) for p in rel.split("|") if p))
    return out


def skin_cluster(mesh: str) -> str | None:
    history = cmds.listHistory(mesh, pruneDagObjects=True) or []
    skins = cmds.ls(history, type="skinCluster") or []
    return skins[0] if skins else None


def skins_of(joints: list[str]) -> list[tuple[str, str]]:
    """(mesh transform, skinCluster) for every skin driven by one of *joints*."""
    jset = set(joints)
    pairs: list[tuple[str, str]] = []
    for sk in cmds.ls(type="skinCluster") or []:
        infl = {_long(i) for i in (cmds.skinCluster(sk, query=True, influence=True) or [])}
        if not infl & jset:
            continue
        for shp in cmds.skinCluster(sk, query=True, geometry=True) or []:
            for tr in cmds.listRelatives(shp, parent=True, fullPath=True) or []:
                pair = (_long(tr), sk)
                if pair not in pairs:
                    pairs.append(pair)
    return pairs


def controllers() -> list[str]:
    """Rig controllers: transforms (not joints) holding a NURBS curve shape."""
    out: list[str] = []
    for crv in cmds.ls(type="nurbsCurve", long=True) or []:
        if cmds.getAttr(crv + ".intermediateObject"):
            continue
        for tr in cmds.listRelatives(crv, parent=True, fullPath=True) or []:
            if cmds.nodeType(tr) != "joint" and tr not in out:
                out.append(tr)
    return out


def scene_key_times(start: float, end: float) -> list[float]:
    """Time of every key of the scene's time-driven curves inside [start, end]."""
    from dcc.maya.maya_keys import TIME_CURVE_TYPES

    curves = cmds.ls(type=list(TIME_CURVE_TYPES)) or []
    times = cmds.keyframe(curves, query=True, timeChange=True) if curves else None
    return sorted({float(t) for t in (times or []) if start - 1e-6 <= float(t) <= end + 1e-6})


# ── low level reads ──────────────────────────────────────────────────────────────

def _dag(node: str):
    sel = om.MSelectionList()
    sel.add(node)
    return sel.getDagPath(0)


def _shape(mesh: str) -> str:
    shapes = cmds.listRelatives(mesh, shapes=True, type="mesh", noIntermediate=True, fullPath=True) or []
    return shapes[0] if shapes else mesh


def _m16(values) -> tuple:
    return tuple(float(v) for v in values)


@contextmanager
def envelope_off(skin: str | None):
    """Read a skinned mesh BEFORE its skinCluster (the rest shape UsdSkel expects)."""
    if not skin:
        yield
        return
    plug = f"{skin}.envelope"
    try:
        value = cmds.getAttr(plug)
        cmds.setAttr(plug, 0.0)
    except Exception as exc:        # locked / connected envelope: deformed shape, said
        log.warning("%s: enveloppe du skin non modifiable (%s), forme lue deformee", skin, exc)
        yield
        return
    try:
        yield
    finally:
        cmds.setAttr(plug, value)


@contextmanager
def controllers_at_zero():
    """Controllers' translate / rotate at 0 and scale at 1 while inside (locked or
    driven channels are left alone), then every value put back."""
    saved: list[tuple[str, object]] = []
    try:
        for ctrl in controllers():
            for attr, value in _CTRL_DEFAULTS.items():
                plug = f"{ctrl}.{attr}"
                try:
                    if not cmds.getAttr(plug, settable=True):
                        continue
                    saved.append((plug, cmds.getAttr(plug)))
                    cmds.setAttr(plug, value)
                except Exception:   # noqa: BLE001 - a missing / odd channel is skipped
                    continue
        yield len({p.split(".", 1)[0] for p, _ in saved})
    finally:
        for plug, value in reversed(saved):
            try:
                cmds.setAttr(plug, value)
            except Exception:       # noqa: BLE001
                log.warning("valeur non remise : %s", plug)
        cmds.currentTime(cmds.currentTime(query=True), edit=True)   # re-evaluate the keys


# ── model ─────────────────────────────────────────────────────────────────────────

def _mesh_data(mesh: str, opts: dict):
    """Geometry of one mesh, read before any skin: points, faces, faceVarying normals
    (hard edges kept), UVs, color sets. The names come from the attribute renamer."""
    from features.usd_export.contract import MeshData

    renames = {str(k): str(v).strip() for k, v in (opts.get("renames") or {}).items() if str(v).strip()}
    skin = skin_cluster(mesh)
    with envelope_off(skin):
        fn = om.MFnMesh(_dag(_shape(mesh)))
        pts = fn.getPoints(om.MSpace.kObject)
        counts, indices = fn.getVertices()
        data = MeshData(
            name=_short(mesh), path=mesh,
            points=[(p.x, p.y, p.z) for p in pts],
            face_vertex_counts=[int(c) for c in counts],
            face_vertex_indices=[int(i) for i in indices],
            subdivision_scheme=str(opts.get("subdivision_scheme") or "none"),
        )
        if opts.get("normals", True):
            normals = fn.getNormals(om.MSpace.kObject)
            _ncounts, nids = fn.getNormalIds()
            data.normals = [(normals[i].x, normals[i].y, normals[i].z) for i in nids]
        if opts.get("uv", True):
            try:
                us, vs = fn.getUVs()
                _uv_counts, uv_ids = fn.getAssignedUVs()
                if len(uv_ids) == len(data.face_vertex_indices):
                    data.uvs = [(float(us[i]), float(vs[i])) for i in range(len(us))]
                    data.uv_indices = [int(x) for x in uv_ids]
                    data.uv_name = renames.get("st", "st")
                else:
                    log.warning("%s: UV incompletes (faces sans UV), UV non exportees", data.name)
            except Exception as exc:    # noqa: BLE001
                log.warning("%s: lecture des UV impossible : %s", data.name, exc)
        if opts.get("color_sets", False):
            for cs in fn.getColorSetNames() or []:
                try:
                    cols = fn.getFaceVertexColors(cs)
                except Exception as exc:    # noqa: BLE001
                    log.warning("%s: color set %s illisible : %s", data.name, cs, exc)
                    continue
                values = [(max(c.r, 0.0), max(c.g, 0.0), max(c.b, 0.0)) for c in cols]
                if len(values) != len(data.face_vertex_indices):
                    continue
                data.primvars.append({"name": renames.get(cs, cs), "type": "color3f",
                                      "interpolation": "faceVarying", "values": values})
    return data


def model_asset(asset: str, scope: str, opts: dict, root: str | None = None):
    from features.usd_export.contract import LightAsset, SkeletonData

    meshes = mesh_transforms(scope, root)
    if not meshes:
        where = "dans la selection" if scope == "selection" else "dans la scene"
        raise PresetError(f"aucune geometrie {where} : rien n'est exporte")
    data = [_mesh_data(m, opts) for m in meshes]
    log.info("model: %d mesh(es), %d points", len(data), sum(len(d.points) for d in data))
    return LightAsset(asset=asset, skeleton=SkeletonData([], [], []), meshes=data)


# ── rig ───────────────────────────────────────────────────────────────────────────

def _bind_worlds(pairs: list[tuple[str, str]]) -> dict[str, "om.MMatrix"]:
    """Joint -> world bind matrix (inverse bindPreMatrix) from every skinCluster."""
    out: dict = {}
    for _mesh, skin in pairs:
        fn = oma.MFnSkinCluster(_dag_node(skin))
        for dp in fn.influenceObjects():
            dag = dp.fullPathName()
            if dag in out:
                continue
            logical = fn.indexForInfluenceObject(dp)
            out[dag] = om.MMatrix(cmds.getAttr(f"{skin}.bindPreMatrix[{logical}]")).inverse()
    return out


def _dag_node(node: str):
    sel = om.MSelectionList()
    sel.add(node)
    return sel.getDependNode(0)


def _locals_from_worlds(joints: list[str], worlds: dict) -> list[tuple]:
    """Local matrices from world ones (Maya row vectors: local = world * parent^-1)."""
    out = []
    for dag in joints:
        parent = dag.rsplit("|", 1)[0]
        pw = worlds.get(parent)
        if pw is None:
            pw = om.MMatrix(_m16(cmds.getAttr(f"{dag}.parentMatrix[0]")))
        out.append(_m16(worlds[dag] * pw.inverse()))
    return out


def _skin_weights(mesh: str, skin: str, joint_index: dict[str, int], opts: dict):
    """MeshData carrying the compacted weights of one skinned mesh (+ rest points to
    find its model mesh)."""
    from features.usd_export.contract import MeshData, compact_weights

    with envelope_off(skin):
        pts = om.MFnMesh(_dag(_shape(mesh))).getPoints(om.MSpace.kObject)
    fn = oma.MFnSkinCluster(_dag_node(skin))
    comp = om.MFnSingleIndexedComponent().create(om.MFn.kMeshVertComponent)
    om.MFnSingleIndexedComponent(comp).addElements(list(range(len(pts))))
    weights, _n = fn.getWeights(_dag(_shape(mesh)), comp)
    infl = []
    for dp in fn.influenceObjects():
        j = joint_index.get(dp.fullPathName(), -1)
        if j < 0:
            log.warning("%s: influence %s hors du squelette exporte, poids ignores",
                        _short(mesh), _short(dp.fullPathName()))
        infl.append(j)
    idx, wts, size = compact_weights(
        infl, list(weights), len(pts),
        max_influences=int(opts.get("max_influences") or 0),
        threshold=float(opts.get("weight_threshold") or 1e-4))
    return MeshData(
        name=_short(mesh), path=mesh, points=[(p.x, p.y, p.z) for p in pts],
        face_vertex_counts=[], face_vertex_indices=[],
        joint_indices=idx, joint_weights=wts, influences_per_point=size,
        geom_bind_transform=_m16(cmds.getAttr(f"{skin}.geomMatrix")), skin_only=True,
    )


def rig_asset(asset: str, scope: str, opts: dict, root: str | None = None):
    """Skeleton in its neutral rest pose + the skin weights of the meshes it deforms.

    rest_pose: "bind" (skinCluster bind pose, joints outside the skin keep their
    current local pose), "zero_ctrls" (controllers at 0) or "current" (this frame).
    The bind transforms always come from the skinCluster (skinning stays exact)."""
    from features.usd_export.contract import LightAsset, SkeletonData

    found = scoped_joints(scope, root)
    if not found:
        where = "dans la selection" if scope == "selection" else "dans la scene"
        raise PresetError(f"aucun joint {where} : selectionne le squelette (ou son groupe)")
    joints = [j for r in skeleton_roots(found) for j in joint_chain(r)]
    tokens = joint_tokens(joints)
    pairs = skins_of(joints)
    bind = _bind_worlds(pairs)
    mode = str(opts.get("rest_pose") or "bind")

    def _current_worlds() -> dict:
        return {j: om.MMatrix(_m16(cmds.getAttr(f"{j}.worldMatrix[0]"))) for j in joints}

    if mode == "zero_ctrls":
        with controllers_at_zero() as n_ctrls:
            worlds = _current_worlds()
            rest = _locals_from_worlds(joints, worlds)   # parents read while still at 0
        log.info("rig: pose neutre = %d controleur(s) a 0", n_ctrls)
    elif mode == "current":
        worlds = _current_worlds()
        rest = [_m16(cmds.getAttr(f"{j}.matrix")) for j in joints]
    else:
        current = _current_worlds()
        worlds = {j: bind.get(j, current[j]) for j in joints}
        rest = _locals_from_worlds(joints, worlds)
    bind_transforms = [_m16(bind.get(j, worlds[j])) for j in joints]
    skeleton = SkeletonData(joints=tokens, bind_transforms=bind_transforms, rest_transforms=rest)

    index = {j: i for i, j in enumerate(joints)}
    meshes = [_skin_weights(m, sk, index, opts) for m, sk in pairs] if opts.get("skin", True) else []
    log.info("rig: %d joint(s) sur %d racine(s), %d mesh(es) skinne(s), pose %s",
             len(joints), len(skeleton_roots(joints)), len(meshes), mode)
    return LightAsset(asset=asset, skeleton=skeleton, meshes=meshes)


# ── anim ──────────────────────────────────────────────────────────────────────────

def _local_trs(dag: str):
    m = om.MTransformationMatrix(om.MMatrix(_m16(cmds.getAttr(f"{dag}.matrix"))))
    t = m.translation(om.MSpace.kTransform)
    q = m.rotation(asQuaternion=True)
    s = m.scale(om.MSpace.kTransform)
    return (t[0], t[1], t[2]), (q[0], q[1], q[2], q[3]), (s[0], s[1], s[2])


def anim_asset(asset: str, scope: str, opts: dict, frame_start: int, frame_end: int,
               root: str | None = None):
    """Rotations of the joints that move over [start, end], baked per frame.

    translate: "all" (default: every translating joint), "root" (the highest translating
    joints: the root motion, whatever the rig calls them) or "none" (rotations only,
    static translations). interpolation "held" holds each key of the
    scene until the next (step); reduce drops the samples a consumer rebuilds exactly."""
    from features.usd_export.contract import (
        AnimData, LightAsset, SkeletonData, hold_keys, reduce_samples, rotation_moves,
        translation_roots, vector_moves,
    )

    found = scoped_joints(scope, root)
    if not found:
        if scope == "selection" and not root:
            raise PresetError("aucun joint selectionne : selectionne le squelette anime "
                              "(ou passe le scope en scene)")
        raise PresetError("aucun joint dans la scene : rien a exporter")
    wanted = set(found)
    joints = [j for r in skeleton_roots(found) for j in joint_chain(r) if j in wanted]
    tokens = joint_tokens(joints)
    times = list(range(int(frame_start), int(frame_end) + 1))
    if len(times) < 2:
        raise PresetError(f"plage {frame_start}-{frame_end} trop courte : il faut au moins 2 images")

    now = cmds.currentTime(query=True)
    rows_t, rows_r, rows_s = [], [], []
    try:
        for t in times:
            cmds.currentTime(t, edit=True)
            trs = [_local_trs(j) for j in joints]
            rows_t.append([x[0] for x in trs])
            rows_r.append([x[1] for x in trs])
            rows_s.append([x[2] for x in trs])
    finally:
        cmds.currentTime(now, edit=True)

    n = len(joints)
    rotating = [i for i in range(n) if rotation_moves([r[i] for r in rows_r])]
    moving_t = [i for i in range(n) if vector_moves([r[i] for r in rows_t])]
    mode = str(opts.get("translate") or "all")
    if mode == "all":
        translating = moving_t
    elif mode == "root":
        roots = set(translation_roots(tokens, [tokens[i] for i in moving_t]))
        translating = [i for i in moving_t if tokens[i] in roots]
    else:
        translating = []
    keep = sorted(set(rotating) | set(translating))
    if not keep:
        raise PresetError(f"aucun joint ne tourne entre {frame_start} et {frame_end} : rien a exporter")
    if any(vector_moves([r[i] for r in rows_s], 1e-4) for i in keep):
        log.warning("anim: echelles de joints animees ignorees (rotations seulement)")
    skipped_t = [tokens[i] for i in moving_t if i not in translating]
    if skipped_t and mode != "all":
        log.info("anim: translations animees non exportees sur %d joint(s) (%s)", len(skipped_t),
                 ", ".join(_short(t) for t in skipped_t[:4]))

    try:
        import maya.mel as mel  # type: ignore[import]
        fps = float(mel.eval("currentTimeUnitToFPS()"))
    except Exception:           # noqa: BLE001
        fps = None
    sampled_t = bool(translating)
    anim = AnimData(
        joints=[tokens[i] for i in keep],
        times=[float(t) for t in times],
        rotations=[[row[i] for i in keep] for row in rows_r],
        translations=([[row[i] for i in keep] for row in rows_t] if sampled_t
                      else [[rows_t[0][i] for i in keep]]),
        scales=[[rows_s[0][i] for i in keep]],
        fps=fps, translations_static=not sampled_t, scales_static=True,
    )
    if str(opts.get("interpolation") or "smooth") == "held":
        anim = hold_keys(anim, [float(frame_start)] + scene_key_times(frame_start, frame_end))
    before = len(anim.times)
    if opts.get("reduce", True):
        anim = reduce_samples(anim)
    log.info("anim: %d joint(s) animes, %d-%d, %s, %d/%d echantillons gardes%s",
             len(anim.joints), frame_start, frame_end, anim.interpolation, len(anim.times), before,
             f", translations sur {len(translating)} joint(s)" if translating else "")
    return LightAsset(asset=asset, skeleton=SkeletonData([], [], []), anim=anim)


def build(preset: str, asset: str, scope: str, opts: dict, frame_start: int | None,
          frame_end: int | None, root: str | None = None):
    """LightAsset for *preset* ("model" | "rig" | "anim"); PresetError says what is wrong."""
    if preset == "model":
        return model_asset(asset, scope, opts, root)
    if preset == "rig":
        return rig_asset(asset, scope, opts, root)
    if preset == "anim":
        fs = int(frame_start if frame_start is not None else cmds.playbackOptions(query=True, minTime=True))
        fe = int(frame_end if frame_end is not None else cmds.playbackOptions(query=True, maxTime=True))
        return anim_asset(asset, scope, opts, fs, fe, root)
    raise PresetError(f"preset inconnu : {preset}")
