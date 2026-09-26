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
    joint is an influence, else the current world matrix). rest = local matrix of the
    BIND pose (2026-09-26: it was the pose of the current frame, so a rig exported
    mid-animation came out posed); a joint that is not an influence keeps its current
    local matrix.
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
    world_bind: dict[str, "om.MMatrix"] = {}
    for dag in joints_dag:
        if dag in bind_by_dag:
            bind_transforms.append(bind_by_dag[dag])
        else:
            bind_transforms.append(_matrix16(cmds.getAttr(f"{dag}.worldMatrix[0]")))
        world_bind[dag] = om.MMatrix(bind_transforms[-1])
    for dag in joints_dag:
        if dag not in bind_by_dag:
            rest_transforms.append(_matrix16(cmds.getAttr(f"{dag}.matrix")))
            continue
        # Maya row vectors: world = local * parent_world, so local = world * parent_world^-1.
        parent = dag.rsplit("|", 1)[0]
        if parent in world_bind:
            parent_world = world_bind[parent]
        else:
            parent_world = om.MMatrix(_matrix16(cmds.getAttr(f"{dag}.parentMatrix[0]")))
        rest_transforms.append(_matrix16(world_bind[dag] * parent_world.inverse()))

    return SkeletonData(joints=tokens, bind_transforms=bind_transforms, rest_transforms=rest_transforms)


def _unskinned_points(mesh: str, skin: str | None) -> list[tuple]:
    """Object-space points of *mesh*; with *skin*, BEFORE the skinCluster (envelope 0
    while reading). UsdSkel skins the points itself: points read on the deformed mesh
    were skinned twice when the export frame was not the bind pose (2026-09-26)."""
    def _read():
        flat = cmds.xform(f"{mesh}.vtx[*]", q=True, os=True, t=True) or []
        return [tuple(flat[i:i + 3]) for i in range(0, len(flat), 3)]

    if not skin:
        return _read()
    plug = f"{skin}.envelope"
    try:
        envelope = cmds.getAttr(plug)
        cmds.setAttr(plug, 0.0)
    except Exception as exc:        # locked / connected envelope: deformed points, said
        log.warning("%s: skin envelope not settable (%s), points read deformed", _short(mesh), exc)
        return _read()
    try:
        return _read()
    finally:
        cmds.setAttr(plug, envelope)


def _extract_mesh(mesh: str, skin: str | None, joints_dag: list[str],
                  want_weights: bool = True, want_uv: bool = True):
    """Return a MeshData with geometry, optional UVs and optional skin binding.

    *skin* None (or *want_weights* False) skips the skin binding; *want_uv* False
    skips the UV set.
    """
    from features.usd_export.contract import MeshData

    mesh_short = _short(mesh)
    points = _unskinned_points(mesh, skin if (skin and want_weights) else None)

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
        path=mesh,
        points=points,
        face_vertex_counts=vtx_counts,
        face_vertex_indices=vtx_indices,
    )

    # UVs — authored as an indexed faceVarying "st" primvar. getAssignedUVs()
    # returns per-face uv counts (parallel to face_vertex_counts) + flat uv ids.
    if want_uv:
        try:
            uv_sel = om.MSelectionList()
            uv_sel.add(mesh)
            mfn = om.MFnMesh(uv_sel.getDagPath(0))
            us, vs = mfn.getUVs()
            _uv_counts, uv_ids = mfn.getAssignedUVs()
            data.uvs = [(float(us[i]), float(vs[i])) for i in range(len(us))]
            data.uv_indices = [int(x) for x in uv_ids]
        except Exception as exc:
            log.warning("UV extraction failed on %s: %s", mesh_short, exc)

    if not skin or not want_weights:
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
    try:
        import maya.mel as mel
        fps = float(mel.eval("currentTimeUnitToFPS()"))
    except Exception:
        fps = None
    return AnimData(
        joints=animated,
        times=[float(t) for t in times],
        translations=translations,
        rotations=rotations,
        scales=scales,
        fps=fps,
    )


def _extract_cameras(scope: str, sel_set: set[str]):
    """Extract user cameras (skips Maya's startup persp/top/front/side)."""
    from features.usd_export.contract import CameraData

    out = []
    for shp in (cmds.ls(type="camera", long=True) or []):
        try:
            if cmds.camera(shp, q=True, startupCamera=True):
                continue
        except Exception:
            pass
        tr = (cmds.listRelatives(shp, parent=True, fullPath=True) or [None])[0]
        if tr is None:
            continue
        if scope == "selection" and sel_set and tr not in sel_set and shp not in sel_set:
            continue
        def _g(attr, default=None):
            try:
                return cmds.getAttr(f"{shp}.{attr}")
            except Exception:
                return default
        ortho = bool(_g("orthographic", False))
        out.append(CameraData(
            name=_short(tr),
            transform=_matrix16(cmds.getAttr(f"{tr}.worldMatrix[0]")),
            focal_length=float(_g("focalLength", 35.0)),
            horizontal_aperture=float(_g("horizontalFilmAperture", 1.417)) * 25.4,  # inch -> mm
            vertical_aperture=float(_g("verticalFilmAperture", 0.945)) * 25.4,
            clipping_range=(float(_g("nearClipPlane", 0.1)), float(_g("farClipPlane", 10000.0))),
            projection="orthographic" if ortho else "perspective",
            fstop=(float(_g("fStop")) if _g("fStop") is not None else None),
            focus_distance=(float(_g("focusDistance")) if _g("focusDistance") is not None else None),
        ))
    return out


def _extract_lights(scope: str, sel_set: set[str]):
    """Extract Maya lights, mapped to UsdLux types."""
    from features.usd_export.contract import LightData

    type_map = {
        "directionalLight": "distant", "pointLight": "point", "spotLight": "spot",
        "areaLight": "rect", "ambientLight": "dome", "volumeLight": "point",
    }
    out = []
    for maya_type, usd_type in type_map.items():
        for shp in (cmds.ls(type=maya_type, long=True) or []):
            tr = (cmds.listRelatives(shp, parent=True, fullPath=True) or [None])[0]
            if tr is None:
                continue
            if scope == "selection" and sel_set and tr not in sel_set and shp not in sel_set:
                continue
            def _g(attr, default=None):
                try:
                    return cmds.getAttr(f"{shp}.{attr}")
                except Exception:
                    return default
            col = _g("color", (1.0, 1.0, 1.0))
            if isinstance(col, list):          # getAttr color returns [(r,g,b)]
                col = col[0] if col and isinstance(col[0], (list, tuple)) else col
            cone = None
            softness = None
            if maya_type == "spotLight":
                full = _g("coneAngle", 40.0)
                cone = float(full) / 2.0        # Maya full angle -> USD half-angle from axis
                pen = _g("penumbraAngle", 0.0)
                if pen:
                    softness = max(0.0, min(1.0, abs(float(pen)) / max(float(full), 1.0)))
            out.append(LightData(
                name=_short(tr),
                transform=_matrix16(cmds.getAttr(f"{tr}.worldMatrix[0]")),
                light_type=usd_type,
                intensity=float(_g("intensity", 1.0)),
                color=tuple(float(c) for c in col[:3]),
                cone_angle=cone,
                cone_softness=softness,
            ))
    return out


def _scene_skin_pairs() -> list[tuple[str, str]]:
    """Every (mesh_transform, skinCluster) pair in the scene."""
    pairs: list[tuple[str, str]] = []
    for sk in (cmds.ls(type="skinCluster") or []):
        for shp in (cmds.skinCluster(sk, q=True, geometry=True) or []):
            for tr in (cmds.listRelatives(shp, parent=True, fullPath=True) or []):
                pairs.append(((cmds.ls(tr, long=True) or [tr])[0], sk))
    return pairs


def _scene_mesh_pairs() -> list[tuple[str, str | None]]:
    """Every mesh transform in the scene, paired with its skinCluster (or None).

    Used for geo-only exports where an unskinned mesh is still valid output.
    """
    pairs: list[tuple[str, str | None]] = []
    for shp in (cmds.ls(type="mesh", noIntermediate=True, long=True) or []):
        for tr in (cmds.listRelatives(shp, parent=True, fullPath=True) or []):
            tr = (cmds.ls(tr, long=True) or [tr])[0]
            pairs.append((tr, _skin_cluster(tr)))
    return pairs


def _build_light_asset(
    asset: str,
    mesh: str | None,
    root_joint: str | None,
    frame_start: int | None,
    frame_end: int | None,
    include_geo: bool = True,
    include_skel: bool = True,
    include_anim: bool = True,
    include_weights: bool = True,
    include_uv: bool = True,
    include_cam: bool = False,
    include_light: bool = False,
    scope: str = "selection",
    root: str | None = None,
):
    """Extract a LightAsset from the Maya scene, honouring the include flags.

    *root* (U2, multi-instance publish) restricts the export to the meshes under one
    node (one character instance, e.g. the DINGO_02 reference); no scene fallback.

    *scope* "scene" takes the whole scene (every mesh when geo is included, else the
    skinned meshes + rig skeleton); "selection" takes the selected mesh(es), falling
    back to the scene when nothing usable is selected. A geo-only export accepts plain
    unskinned meshes; the skeleton is the joint chain under the root, and the anim layer
    keeps only the joints that actually move.

    Dependency rules: skin weights need geo + skel; anim needs skel. Excluded data is
    simply not extracted, and the authoring core skips the matching layer.
    Returns None (and logs) on error.
    """
    from features.usd_export.contract import LightAsset, SkeletonData

    eff_weights = include_weights and include_geo and include_skel
    eff_anim = include_anim and include_skel
    sel_set = set(cmds.ls(selection=True, long=True) or [])

    # Cameras / lights are independent of any skeleton (a pure light/camera rig needs
    # no skinned mesh).
    cameras = _extract_cameras(scope, sel_set) if include_cam else []
    lights = _extract_lights(scope, sel_set) if include_light else []

    # Collect (mesh, skinCluster) pairs. The skinCluster is optional for a geo-only
    # export: a plain unskinned mesh is still valid output, and only skel/anim/weights
    # actually need one. _scene_fallback picks the matching scene sweep.
    def _scene_fallback():
        return _scene_mesh_pairs() if include_geo else _scene_skin_pairs()

    if root:
        pairs = []
        for shp in (cmds.listRelatives(root, allDescendents=True, type="mesh", fullPath=True) or []):
            if cmds.getAttr(shp + ".intermediateObject"):
                continue
            for m in (cmds.listRelatives(shp, parent=True, fullPath=True) or []):
                sk = _skin_cluster(m)
                if include_geo or sk:
                    pairs.append((m, sk))
        if not pairs:
            log.error("light export: no mesh under %s", root)
    elif scope == "scene":
        pairs = _scene_fallback()
    else:
        cand = [mesh] if mesh is not None else (cmds.ls(selection=True, long=True, type="transform") or [])
        pairs = []
        for m in cand:
            m = (cmds.ls(m, long=True) or [m])[0]
            if not cmds.listRelatives(m, shapes=True, type="mesh"):
                continue
            sk = _skin_cluster(m)
            if include_geo or sk:                 # keep unskinned meshes for geo export
                pairs.append((m, sk))
        if not pairs and (include_geo or include_skel):   # nothing usable selected → whole scene
            pairs = _scene_fallback()

    seen: set[str] = set()
    pairs = [(m, sk) for m, sk in pairs if not (m in seen or seen.add(m))]

    skeleton = SkeletonData(joints=[], bind_transforms=[], rest_transforms=[])
    meshes: list = []
    anim = None

    if pairs:
        # First skinCluster among the pairs (a geo-only selection may have none).
        first_sk = next((sk for _, sk in pairs if sk), None)

        # Skeleton root: provided, else walk up from the first skin's first influence.
        if root_joint is None and first_sk is not None:
            infl = cmds.skinCluster(first_sk, q=True, inf=True) or []
            if infl:
                node = (cmds.ls(infl[0], long=True) or [infl[0]])[0]
                while True:
                    parent = cmds.listRelatives(node, parent=True, type="joint", fullPath=True)
                    if not parent:
                        break
                    node = parent[0]
                root_joint = node

        joints_dag = _joint_chain(root_joint) if root_joint else []
        tokens = _token_paths(joints_dag) if joints_dag else []

        if frame_start is None:
            frame_start = int(cmds.playbackOptions(q=True, min=True))
        if frame_end is None:
            frame_end = int(cmds.playbackOptions(q=True, max=True))

        if include_skel and joints_dag and first_sk is not None:
            skeleton = _extract_skeleton(joints_dag, tokens, first_sk)
        if include_geo:
            for m, sk in pairs:
                meshes.append(_extract_mesh(
                    m, sk if (eff_weights and joints_dag) else None, joints_dag,
                    want_weights=eff_weights, want_uv=include_uv,
                ))
        if eff_anim and joints_dag:
            anim = _extract_anim(joints_dag, tokens, frame_start, frame_end)

    if not meshes and not skeleton.joints and not cameras and not lights:
        log.error("light export: nothing to export (%s). Select a mesh (geo-only needs no "
                  "skinCluster), or enable a camera/light.", scope)
        return None

    log.info("light export: %d mesh(es), %d cam, %d light, scope=%s",
             len(meshes), len(cameras), len(lights), scope)
    return LightAsset(asset=asset, skeleton=skeleton, meshes=meshes, anim=anim,
                      cameras=cameras, lights=lights)


def run_light_export(
    asset: str,
    result_path: str,
    mesh: str | None = None,
    root_joint: str | None = None,
    frame_start: int | None = None,
    frame_end: int | None = None,
    include_geo: bool = True,
    include_skel: bool = True,
    include_anim: bool = True,
    include_weights: bool = True,
    include_uv: bool = True,
    include_cam: bool = False,
    include_light: bool = False,
    scope: str = "selection",
    root: str | None = None,
    options_b64: str = "",
) -> None:
    """Extract a light asset from Maya and write a JSON envelope to *result_path*.

    Writes ``{ok, asset:<LightAsset dict|null>, logs:[{level,msg}]}``. USD authoring
    is NOT done here (Maya has no reliable pxr): the Flux backend reads this envelope,
    rebuilds the LightAsset and publishes it. Called via commandPort by the hub.

    *options_b64* is base64(JSON) of the Publisher preset options; with a "preset"
    key ("model" | "rig" | "anim", ADR 0034) the preset sweep of maya_usd_presets runs
    instead of the include flags.
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

    options: dict = {}
    if options_b64:
        try:
            import base64
            options = json.loads(base64.b64decode(options_b64).decode("utf-8")) or {}
        except Exception as exc:    # noqa: BLE001 - reported, the export goes on
            records.append({"level": "WARNING", "msg": f"options d'export illisibles : {exc!r}"})

    data = None
    try:
        if not _IN_MAYA:
            log.error("run_light_export: not running inside Maya")
        elif options.get("preset"):
            import importlib
            import sys

            sys.modules.pop("dcc.maya.maya_usd_presets", None)   # pick up a new backend
            presets = importlib.import_module("dcc.maya.maya_usd_presets")
            try:
                light = presets.build(str(options["preset"]), asset, scope, options,
                                      frame_start, frame_end, root=root)
                data = dataclasses.asdict(light)
            except presets.PresetError as exc:
                log.error("%s", exc)
        else:
            light = _build_light_asset(
                asset, mesh, root_joint, frame_start, frame_end,
                include_geo=include_geo, include_skel=include_skel,
                include_anim=include_anim, include_weights=include_weights,
                include_uv=include_uv, scope=scope, root=root,
            )
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
