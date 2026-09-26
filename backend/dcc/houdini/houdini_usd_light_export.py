"""
FLUX — Houdini light USD export glue (KineFX).

Extracts a skinned asset from a running Houdini instance and publishes it as a light
layered UsdSkel asset (model + skel + anim joints only), mirroring the Maya glue.

Design (same as Maya): Houdini EXTRACTS raw data (via houdini_client.run, no pxr in
Houdini); the FLUX backend authors/publishes the USD with pxr. Extraction is best-effort
and defensive — a missing skin binding still yields model + skel layers.

KineFX conventions used:
  - Skeleton geometry: one point per joint, point attrs `name` ("Root/Hip"-style path)
    and `transform` (3x3 world rotation/scale) + P (world position).
  - Skin weights: mesh `boneCapture` point attr + detail `boneCapture_pCaptPath`
    (region -> joint path). Optional; skipped with a warning when absent.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from core.logger import get_logger
from dcc.houdini.client import houdini_client

log = get_logger(__name__)


# The extraction runs entirely inside Houdini and assigns a LightAsset-shaped dict to
# `result` (or {"__error__": msg}). Kept as a single code string for houdini_client.run.
_EXTRACT_CODE = textwrap.dedent(r'''
    import hou

    _SKEL = {skel!r}
    _MESH = {mesh!r}
    _FS   = {fs!r}
    _FE   = {fe!r}
    _INC_GEO  = {inc_geo}
    _INC_SKEL = {inc_skel}
    _INC_ANIM = {inc_anim}
    _INC_W    = {inc_w}
    _INC_UV   = {inc_uv}
    _logs = []

    def _log(level, msg):
        _logs.append({{"level": level, "msg": msg}})

    def _pick_nodes():
        skel = hou.node(_SKEL) if _SKEL else None
        mesh = hou.node(_MESH) if _MESH else None
        if skel and mesh:
            return skel, mesh
        sel = list(hou.selectedNodes())
        # A skeleton geo has a point 'name' attribute; the other selected SOP is the mesh.
        cand_skel, cand_mesh = skel, mesh
        for n in sel:
            try:
                g = n.geometry()
            except Exception:
                continue
            if g is None:
                continue
            has_name = g.findPointAttrib("name") is not None
            if has_name and cand_skel is None:
                cand_skel = n
            elif cand_mesh is None and g.prims():
                cand_mesh = n
        return cand_skel, cand_mesh

    def _world4(pt):
        # Build a row-major 4x4 world matrix from KineFX 'transform' (3x3) + P.
        try:
            x = pt.attribValue("transform")
        except Exception:
            x = None
        m3 = hou.Matrix3(x) if x else hou.Matrix3(1)
        m4 = hou.Matrix4(m3) * hou.hmath.buildTranslate(pt.position())
        return m4

    def _hierarchy(geo):
        # KineFX: joint names are leaves ("joint2"), the hierarchy is the topology
        # (each polyline goes parent -> child). UsdSkel wants path tokens
        # ("joint1/joint2"), parents first. Names that already hold "/" are kept.
        pts = list(geo.points())
        leaf, world, parent = {{}}, {{}}, {{}}
        for pt in pts:
            try:
                nm = pt.attribValue("name")
            except Exception:
                nm = ""
            leaf[pt.number()] = nm or ("joint%d" % pt.number())
            world[pt.number()] = _world4(pt)
        for prim in geo.prims():
            vs = prim.vertices()
            for i in range(1, len(vs)):
                child = vs[i].point().number()
                if child not in parent:
                    parent[child] = vs[i - 1].point().number()
        children = {{}}
        for c, par in parent.items():
            children.setdefault(par, []).append(c)
        order, path = [], {{}}
        def _walk(n, prefix):
            path[n] = leaf[n] if ("/" in leaf[n] or not prefix) else prefix + "/" + leaf[n]
            order.append(n)
            for c in sorted(children.get(n, [])):
                if c not in path:
                    _walk(c, path[n])
        for pt in pts:
            n = pt.number()
            if n not in parent and n not in path:
                _walk(n, "")
        for pt in pts:          # cycles / leftovers: keep them, flat
            n = pt.number()
            if n not in path:
                path[n] = leaf[n]; order.append(n)
        return order, path, world, parent

    def _skeleton(geo):
        order, path, world, parent = _hierarchy(geo)
        joints, bind, rest = [], [], []
        for n in order:
            joints.append(path[n])
            w = world[n]
            bind.append(list(w.asTuple()))
            pw = world.get(parent[n]) if n in parent else None
            local = (w * pw.inverted()) if pw is not None else w
            rest.append(list(local.asTuple()))
        return joints, bind, rest

    def _local_map(geo):
        # joint path -> local 4x4 (for animation sampling / filtering).
        order, path, world, parent = _hierarchy(geo)
        out = {{}}
        for n in order:
            w = world[n]
            pw = world.get(parent[n]) if n in parent else None
            out[path[n]] = (w * pw.inverted()) if pw is not None else w
        return out

    def _mesh_name(node, geo):
        # The mesh's own name, not the SOP's: a Transform SOP at the end of the chain
        # named the published mesh "transform1" (live UTAH 2026-09-26). Prim attribute
        # "path" (FBX / USD / Alembic import) then "name", when the geo holds one value;
        # else the node name. Returns (leaf, full path or "").
        for attr in ("path", "name"):
            a = geo.findPrimAttrib(attr)
            if a is None or a.dataType() != hou.attribData.String:
                continue
            vals = [v for v in a.strings() if v]
            if len(vals) != 1:
                continue
            leaf = vals[0].replace("\\", "/").rstrip("/").split("/")[-1].split(":")[-1]
            if leaf:
                return leaf, (vals[0] if attr == "path" else "")
        return node.name(), ""

    def _mesh_geo(geo):
        pts = [list(p.position()) for p in geo.points()]
        counts, indices, uvs = [], [], []
        _uv_vtx = _INC_UV and geo.findVertexAttrib("uv") is not None
        _uv_pt = _INC_UV and (not _uv_vtx) and geo.findPointAttrib("uv") is not None
        for prim in geo.prims():
            vs = list(prim.vertices())
            # Houdini winds clockwise, USD rightHanded counter-clockwise: keep the first
            # vertex and reverse the rest, like Houdini's own SOP -> USD (UTAH GEO v001
            # was published inside out, 2026-09-26).
            vs = vs[:1] + vs[:0:-1]
            counts.append(len(vs))
            for v in vs:
                indices.append(v.point().number())
                if _uv_vtx or _uv_pt:
                    try:
                        uv = v.attribValue("uv") if _uv_vtx else v.point().attribValue("uv")
                    except Exception:
                        uv = (0.0, 0.0, 0.0)
                    uvs.append([float(uv[0]), float(uv[1])])
        return pts, counts, indices, uvs

    def _weights(geo, joints):
        # Best-effort boneCapture extraction. Returns (indices, weights, elem, geom_bind) or None.
        try:
            import hou
            capt = geo.findPointAttrib("boneCapture")
            paths_attr = geo.findGlobalAttrib("boneCapture_pCaptPath")
            if capt is None or paths_attr is None:
                _log("WARNING", "no boneCapture on mesh; exporting geometry without skin binding")
                return None
            region_paths = list(geo.attribValue("boneCapture_pCaptPath"))
            # region index -> skeleton joint index, matched by joint-name suffix
            region_to_joint = []
            jset = {{j: i for i, j in enumerate(joints)}}
            for rp in region_paths:
                # rp like ".../Root/Hip/cregion0" -> strip trailing /cregionN
                base = rp.rsplit("/cregion", 1)[0]
                # match longest joint token that ends the region path
                idx = None
                for j, ji in jset.items():
                    # joints are paths ("joint1/joint2"): match the full path or the leaf
                    if base.endswith(j) or base.rsplit("/", 1)[-1] == j.rsplit("/", 1)[-1]:
                        if idx is None or len(j) > len(joints[idx]):
                            idx = ji
                region_to_joint.append(idx if idx is not None else 0)
            npts = len(geo.points())
            # boneCapture point values are flat: [idx0,w0, idx1,w1, ...] per point, fixed length
            vals = geo.pointFloatAttribValuesAsString  # not available; fall back per-point
            per = capt.size()  # number of floats per point
            elem = max(1, per // 2)
            flat_idx, flat_w = [], []
            for pt in geo.points():
                pv = pt.attribValue("boneCapture")
                pv = list(pv) if isinstance(pv, (list, tuple)) else [pv]
                for k in range(elem):
                    ridx = int(pv[2 * k]) if 2 * k < len(pv) else -1
                    w = float(pv[2 * k + 1]) if 2 * k + 1 < len(pv) else 0.0
                    flat_idx.append(region_to_joint[ridx] if 0 <= ridx < len(region_to_joint) else 0)
                    flat_w.append(max(0.0, w))
            return flat_idx, flat_w, elem, [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]
        except Exception as exc:
            _log("WARNING", "weight extraction failed: %s" % exc)
            return None

    try:
        skel_node, mesh_node = _pick_nodes()
        if _INC_SKEL and skel_node is None:
            result = {{"__error__": "no KineFX skeleton found (pass skel_node or select it)", "__logs__": _logs}}
        elif _INC_GEO and mesh_node is None:
            # A LOP selected (Solaris lookdev chain): its FBX mesh is triangulated, the
            # model is published from the SOP geometry (quads, name attribute).
            lops = [n.path() for n in hou.selectedNodes() if isinstance(n, hou.LopNode)]
            msg = ("aucun mesh SOP selectionne : %s est un node LOP. L'export GEO lit un SOP "
                   "(la geo dans /obj, ex. le File qui importe le FBX), le preset look lit le LOP"
                   % lops[0]) if lops else "no mesh found (pass mesh_node or select it)"
            result = {{"__error__": msg, "__logs__": _logs}}
        else:
            joints, bind, rest = [], [], []
            if _INC_SKEL and skel_node is not None:
                joints, bind, rest = _skeleton(skel_node.geometry())

            meshes = []
            if _INC_GEO and mesh_node is not None:
                mg = mesh_node.geometry()
                pts, counts, indices, uvs = _mesh_geo(mg)
                mesh_name, mesh_path = _mesh_name(mesh_node, mg)
                mesh_dict = {{
                    "name": mesh_name,
                    "path": mesh_path,
                    "points": pts,
                    "face_vertex_counts": counts,
                    "face_vertex_indices": indices,
                    "uvs": uvs,
                    "uv_indices": [],
                    "joint_indices": [],
                    "joint_weights": [],
                    "influences_per_point": 0,
                    "geom_bind_transform": None,
                }}
                if _INC_W and _INC_SKEL and joints:
                    w = _weights(mg, joints)
                    if w is not None:
                        mesh_dict["joint_indices"] = w[0]
                        mesh_dict["joint_weights"] = w[1]
                        mesh_dict["influences_per_point"] = w[2]
                        mesh_dict["geom_bind_transform"] = w[3]
                meshes = [mesh_dict]

            # Animation: sample local transforms over the frame range, keep moving joints.
            anim = None
            if _INC_ANIM and _INC_SKEL and joints and skel_node is not None:
                fs = int(_FS) if _FS is not None else int(hou.playbar.frameRange()[0])
                fe = int(_FE) if _FE is not None else int(hou.playbar.frameRange()[1])
                if fe > fs:
                    times = list(range(fs, fe + 1))
                    per_time = []
                    for t in times:
                        hou.setFrame(t)
                        lm = _local_map(skel_node.geometry())
                        per_time.append([list(lm.get(j, hou.Matrix4(1)).asTuple()) for j in joints])
                    # filter animated
                    moving = []
                    for jn in range(len(joints)):
                        first = per_time[0][jn]
                        if any(any(abs(a - b) > 1e-4 for a, b in zip(per_time[ti][jn], first)) for ti in range(1, len(times))):
                            moving.append(jn)
                    if moving:
                        def _decomp(m16):
                            m = hou.Matrix4(m16)
                            tr = m.extractTranslates()
                            q = hou.Quaternion(m.extractRotationMatrix3())
                            s = m.extractScales()
                            return list(tr), [q[0], q[1], q[2], q[3]], list(s)
                        a_joints = [joints[j] for j in moving]
                        translations, rotations, scales = [], [], []
                        for ti in range(len(times)):
                            tt, rr, ss = [], [], []
                            for j in moving:
                                T, Q, S = _decomp(per_time[ti][j])
                                tt.append(T); rr.append(Q); ss.append(S)
                            translations.append(tt); rotations.append(rr); scales.append(ss)
                        anim = {{
                            "joints": a_joints,
                            "times": [float(t) for t in times],
                            "translations": translations,
                            "rotations": rotations,
                            "scales": scales,
                            "fps": hou.fps(),
                        }}

            if not meshes and not joints:
                result = {{"__error__": "nothing to export (geo and skel both excluded)", "__logs__": _logs}}
            else:
                result = {{
                    "asset": {{
                        "asset": {asset!r},
                        "skeleton": {{"joints": joints, "bind_transforms": bind, "rest_transforms": rest}},
                        "meshes": meshes,
                        "anim": anim,
                    }},
                    "__logs__": _logs,
                }}
    except Exception as exc:
        result = {{"__error__": "extraction raised: %s" % exc, "__logs__": _logs}}
''')


def run_light_export(
    asset: str,
    project_path: str,
    *,
    skel_node: str | None = None,
    mesh_node: str | None = None,
    frame_start: int | None = None,
    frame_end: int | None = None,
    fmt: str = "usd",
    dest_dir: str | None = None,
    base_name: str | None = None,
    include_geo: bool = True,
    include_skel: bool = True,
    include_anim: bool = True,
    include_weights: bool = True,
    include_uv: bool = True,
) -> dict:
    """Extract a KineFX skinned asset from Houdini and publish a light USD asset.

    The include_* flags choose which USD layers/data to author (same contract as the
    Maya light export): weights need geo+skel, anim needs skel.

    Returns {"ok": True, "version": "vNNN", "root": "..."} or {"ok": False, "error": "..."}.
    """
    code = _EXTRACT_CODE.format(
        skel=skel_node or "", mesh=mesh_node or "",
        fs=frame_start, fe=frame_end, asset=asset,
        inc_geo=bool(include_geo), inc_skel=bool(include_skel),
        inc_anim=bool(include_anim), inc_w=bool(include_weights),
        inc_uv=bool(include_uv),
    )
    resp = houdini_client.run(code)
    if not resp.get("ok"):
        return {"ok": False, "error": resp.get("error", "Houdini run failed")}

    payload = resp.get("result") or {}
    for rec in payload.get("__logs__", []):
        lvl = str(rec.get("level", "INFO")).upper()
        msg = f"[Houdini] {rec.get('msg', '')}"
        (log.warning if lvl == "WARNING" else log.error if lvl in ("ERROR", "CRITICAL") else log.info)(msg)

    if "__error__" in payload:
        log.error("Houdini light export: %s", payload["__error__"])
        return {"ok": False, "error": payload["__error__"]}

    try:
        from features.usd_export import publish_light_asset
        from features.usd_export.contract import light_asset_from_dict

        light = light_asset_from_dict(payload["asset"])
        pub = publish_light_asset(
            light, Path(project_path), fmt=fmt, dest_dir=dest_dir, base_name=base_name
        )
        log.info("Houdini light USD export published: %s (%s)", asset, pub["version"])
        return {"ok": True, "asset": asset, "version": pub["version"], "root": str(pub["root"]),
                "warnings": pub.get("warnings", [])}
    except Exception as exc:
        log.error("Houdini light export publish failed: %s", exc)
        return {"ok": False, "error": str(exc)}
