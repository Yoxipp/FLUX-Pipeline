# maya_usd_preview.py — what each USD preset of the Publisher would take from the
# Maya scene, listed before the publish (2026-09-26). Same sweeps as the export
# (maya_usd_presets), read-only: the scene is never modified. Runs INSIDE Maya.
#
#   model : [{"name", "path", "points", "faces", "uv", "color_sets", "skinned"}]
#   rig   : {"tree": outliner-like tree of the groups holding skeletons, "joints",
#           "skinned": [{"name", "joints"}]}
#   anim  : [{"name", "token", "channels"}] joints that move over the range
#   look  : [{"name", "type", "meshes"}] materials of the scene / of the selected geo
#   camera: [{"name", "path", "focal"}] shot cameras
#   light : [{"name", "path", "type"}] shot lights

from __future__ import annotations

import json

try:
    import maya.cmds as cmds                 # type: ignore[import]
except ImportError:                          # pragma: no cover - outside Maya
    cmds = None                              # type: ignore[assignment]

# The anim preview samples at most this many frames (keys always included).
_ANIM_PREVIEW_SAMPLES = 60


def _p():
    import importlib
    import sys

    sys.modules.pop("dcc.maya.maya_usd_presets", None)
    return importlib.import_module("dcc.maya.maya_usd_presets")


def list_model(scope: str) -> dict:
    p = _p()
    items = []
    for mesh in p.mesh_transforms(scope):
        shape = p._shape(mesh)
        items.append({
            "name": p._short(mesh), "path": mesh,
            "points": int(cmds.polyEvaluate(shape, vertex=True) or 0),
            "faces": int(cmds.polyEvaluate(shape, face=True) or 0),
            "uv": bool(cmds.polyUVSet(shape, query=True, allUVSets=True)),
            "color_sets": list(cmds.polyColorSet(shape, query=True, allColorSets=True) or []),
            "skinned": p.skin_cluster(mesh) is not None,
        })
    return {"items": items}


def _tree(roots: list[str]) -> list[dict]:
    """Outliner-like tree: every group above a skeleton root, then the joints."""
    nodes: dict[str, dict] = {}
    top: list[dict] = []

    def _node(path: str, kind: str) -> dict:
        if path not in nodes:
            nodes[path] = {"name": path.rsplit("|", 1)[-1], "path": path, "type": kind, "children": []}
        return nodes[path]

    attached: set[str] = set()

    def _attach(path: str, node: dict) -> None:
        # Walk up until an already attached ancestor (each node is linked once).
        while path not in attached:
            attached.add(path)
            parent = path.rsplit("|", 1)[0]
            if not parent:
                top.append(node)
                return
            pnode = _node(parent, "joint" if cmds.nodeType(parent) == "joint" else "group")
            pnode["children"].append(node)
            path, node = parent, pnode

    p = _p()
    for root in roots:
        for j in p.joint_chain(root):
            _attach(j, _node(j, "joint"))
    return top


def list_rig(scope: str) -> dict:
    p = _p()
    found = p.scoped_joints(scope)
    roots = p.skeleton_roots(found)
    joints = [j for r in roots for j in p.joint_chain(r)]
    skins = []
    for mesh, skin in p.skins_of(joints):
        skins.append({"name": p._short(mesh),
                      "joints": len(cmds.skinCluster(skin, query=True, influence=True) or [])})
    return {"tree": _tree(roots), "joints": len(joints), "roots": [p._short(r) for r in roots],
            "skinned": skins, "controllers": len(p.controllers())}


def list_anim(scope: str, start: int, end: int) -> dict:
    from features.usd_export.contract import rotation_moves, vector_moves

    p = _p()
    found = p.scoped_joints(scope)
    wanted = set(found)
    joints = [j for r in p.skeleton_roots(found) for j in p.joint_chain(r) if j in wanted]
    if not joints or end <= start:
        return {"items": [], "sampled": 0}
    step = max(1, (end - start) // _ANIM_PREVIEW_SAMPLES)
    frames = sorted(set(range(start, end + 1, step)) | {end}
                    | {int(round(t)) for t in p.scene_key_times(start, end)})
    now = cmds.currentTime(query=True)
    rows = []
    try:
        for t in frames:
            cmds.currentTime(t, edit=True)
            rows.append([p._local_trs(j) for j in joints])
    finally:
        cmds.currentTime(now, edit=True)
    tokens = p.joint_tokens(joints)
    items = []
    for i, j in enumerate(joints):
        rot = rotation_moves([r[i][1] for r in rows])
        tr = vector_moves([r[i][0] for r in rows])
        if rot or tr:
            items.append({"name": p._short(j), "token": tokens[i],
                          "channels": (["rotation"] if rot else []) + (["translation"] if tr else [])})
    return {"items": items, "sampled": len(frames), "joints": len(joints)}


def list_look(scope: str) -> dict:
    p = _p()
    meshes = p.mesh_transforms(scope)
    shapes = {p._shape(m) for m in meshes}
    by_mat: dict[str, dict] = {}
    for sg in cmds.ls(type="shadingEngine") or []:
        members = cmds.sets(sg, query=True) or []
        hit = {cmds.ls(m.split(".")[0], long=True)[0] for m in members if cmds.ls(m.split(".")[0], long=True)}
        # A member may be the shape, its transform, or faces of either.
        count = sum(1 for h in hit if h in shapes or p._shape(h) in shapes)
        if not count:
            continue
        shader = (cmds.listConnections(f"{sg}.surfaceShader", source=True) or [sg])[0]
        entry = by_mat.setdefault(shader, {"name": shader, "type": cmds.nodeType(shader), "meshes": 0})
        entry["meshes"] += count
    return {"items": sorted(by_mat.values(), key=lambda m: m["name"]), "geometry": len(meshes)}


def list_cameras(scope: str) -> dict:
    p = _p()
    from dcc.maya import maya_usd_light_export as lx

    items = [{"name": p._short(tr), "path": tr,
              "focal": round(float(cmds.getAttr(f"{shp}.focalLength")), 2)}
             for tr, shp in lx._camera_nodes(scope, p._scope_selection(scope))]
    return {"items": items}


def list_lights(scope: str) -> dict:
    p = _p()
    from dcc.maya import maya_usd_light_export as lx

    items = [{"name": p._short(tr), "path": tr, "type": mt}
             for tr, _shp, mt in lx._light_nodes(scope, p._scope_selection(scope))]
    return {"items": items}


def preview(preset: str, scope: str, start: int | None = None, end: int | None = None) -> dict:
    scope = "selection" if scope == "selection" else "scene"
    if preset == "camera":
        return list_cameras(scope)
    if preset == "light":
        return list_lights(scope)
    if preset == "model":
        return list_model(scope)
    if preset == "rig":
        return list_rig(scope)
    if preset == "anim":
        s = int(start if start is not None else cmds.playbackOptions(query=True, minTime=True))
        e = int(end if end is not None else cmds.playbackOptions(query=True, maxTime=True))
        return list_anim(scope, s, e)
    if preset == "look":
        return list_look(scope)
    raise ValueError(f"preset inconnu : {preset}")


def run_preview(preset: str, scope: str, start: str, end: str, result_path: str) -> None:
    """commandPort entry (string arguments, import_prep.call_maya_update): write
    {"ok", ...preview} to *result_path* (JSON). Empty start / end = the timeline."""
    try:
        s = int(float(start)) if str(start).strip() else None
        e = int(float(end)) if str(end).strip() else None
        res = {"ok": True, "preset": preset, "scope": scope, **preview(preset, scope, s, e)}
    except Exception as exc:  # noqa: BLE001 - reported to the hub
        res = {"ok": False, "error": repr(exc)}
    with open(result_path, "w", encoding="utf-8") as fh:
        json.dump(res, fh)
