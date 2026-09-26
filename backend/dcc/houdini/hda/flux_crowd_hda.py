"""
FLUX - Houdini "FLUX Crowd" HDA for Solaris (A7, ADR 0022).

Three inputs (2026-09-25): 1 = the assets (e.g. several FLUX Import in a Merge),
2 = the scatter points (any points prim: SOP Import, SOP Create...), 3 = the animations
(FLUX Import of ANIM clips). FLUX lists them in rows with a weight each ("more of this
asset / this animation"); each point gets an asset drawn with those weights and an
animation drawn among those its skeleton plays. Without an input, the older menus /
"Points" SOP below are used. The node outputs the crowd layer only: merge it into the shot.

Draws agents on the points and writes the shot crowd layer:
  * menus: project, sequence, shot, group (one crowd layer per group);
  * assets: the assets with a skeleton (several can be picked; they should share a rig,
    same signature), clips: the animation clips that fit every picked asset;
  * seed, time offset min / max, speed min / max: drawn per agent by FLUX (deterministic);
  * points: P, orient or N (heading), pscale of the SOP given in "Points";
  * "Generer" writes a preview layer in the shot (usd/crowd_work) and sublayers it here,
    "Publier" publishes SEQ_SHOT_CROWD[_GROUP] (vNNN + LAST) and regenerates the stage;
  * Geometrie: proxy or render meshes in the viewport (every FLUX node has it).
Agents are UsdSkel instances that are NOT instanceable (each one has its own animation
source); the layer is authored by the backend (features/usd_assembler/crowd.py).

Same bootstrap pattern as FLUX Shot: the HDA fetches its module from
GET /dcc/houdini/crowd/module, so a fix needs no HDA rebuild.
"""

from __future__ import annotations

from pathlib import Path

from core.logger import get_logger
from dcc.houdini.client import houdini_client

log = get_logger(__name__)

NODE_NAME = "flux_crowd"
LABEL = "FLUX Crowd"

BOOTSTRAP: str = '''
import json, os, urllib.request

def _flux_port():
    try:
        return int(os.environ.get("FLUX_PORT") or
                   open(os.path.join(os.environ.get("APPDATA",""), "FLUX", "backend_port")).read())
    except Exception:
        return 8765

def _load():
    with urllib.request.urlopen(f"http://127.0.0.1:{_flux_port()}/dcc/houdini/crowd/module", timeout=3) as _r:
        exec(json.loads(_r.read())["code"], globals())

try:
    _load()
except Exception:
    def _dead_menu(*a, **kw): return ["", "FLUX offline"]
    for _n in ("menu_project", "menu_seq", "menu_shot", "menu_assets", "menu_clips"):
        globals()[_n] = _dead_menu
    def _offline(node, name):
        try:
            _load()
            globals()[name](node)
        except Exception:
            node.parm("status_msg").set("FLUX offline : demarre FLUX puis recommence")
    def generate(node): _offline(node, "generate")
    def publish(node): _offline(node, "publish")
    def reload(node): _offline(node, "reload")
    def read_inputs(node): _offline(node, "read_inputs")
    def on_created(node): pass
    def on_loaded(node): pass
'''

# Served by GET /dcc/houdini/crowd/module, exec()'d by the bootstrap (runs inside Houdini).
MODULE_FUNCTIONS: str = '''
import json, math, os, threading, time, urllib.parse, urllib.request

def _flux_port():
    try:
        return int(os.environ.get("FLUX_PORT") or
                   open(os.path.join(os.environ.get("APPDATA",""), "FLUX", "backend_port")).read())
    except Exception:
        return 8765

def _get(path, timeout=10, **params):
    url = f"http://127.0.0.1:{_flux_port()}" + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v})
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as exc:
        # "_offline": FLUX not reachable: never cached.
        return {"ok": False, "error": str(exc), "_offline": True}

def _post(path, payload):
    req = urllib.request.Request(f"http://127.0.0.1:{_flux_port()}" + path,
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        try:
            return {"ok": False, "error": json.loads(exc.read()).get("detail", str(exc))}
        except Exception:
            return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

# Assets / clips change rarely and their scan is heavy: a long TTL, prefetched in a
# thread when the node is created or the scene opens, so menus open instantly.
_TTL = 120.0
_cache = {}

def _cached(key, fetch):
    """fetch() -> (data, ok). Only good, non-empty answers are cached: an error or an
    empty list (shots not created yet) is asked again at the next menu opening."""
    now = time.monotonic()
    if key in _cache and now < _cache[key][0]:
        return _cache[key][1]
    data, ok = fetch()
    if ok and data:
        _cache[key] = (now + _TTL, data)
    return data

def _fetch(path, field, empty, **params):
    r = _get(path, **params)
    if r.get("_offline") or r.get("ok") is False:
        return empty, False
    if field is None:
        return (r if not r.get("_offline") else empty), not r.get("_offline")
    return r.get(field, empty), not r.get("_offline")

def _pval(node, name):
    p = node.parm(name)
    return p.evalAsString() if p is not None else ""

def _fval(node, name, default):
    """Float parm, *default* when the HDA predates it (built before that parm)."""
    try:
        return float(node.evalParm(name)) if node.parm(name) is not None else default
    except Exception:
        return default

def _set(node, name, value):
    p = node.parm(name)
    if p is not None:
        p.set(value)

def _status(node, msg):
    _set(node, "status_msg", msg)

def _flat(values):
    out = []
    for v in values:
        out += [v, v]
    return out

def _shots(node):
    project = _pval(node, "project")
    if not project:
        return []
    # Every shot of the project: the crowd publish creates the shot stage if needed.
    return _cached("shots:" + project,
                   lambda: _fetch("/dcc/houdini/crowd/shots", "shots", [], project=project))

def _compat(node, fresh=False):
    project = _pval(node, "project")
    if not project:
        return {"assets": {}, "clips": []}
    key = "compat:" + project
    if fresh:
        _cache.pop(key, None)
    # Opens every asset and clip of the project: far longer than a menu call.
    return _cached(key, lambda: _fetch("/usd/crowd/compat", None, {"assets": {}, "clips": []},
                                       timeout=120, project=project))

def _picked(node, name):
    return [v for v in _pval(node, name).split() if v]

def menu_project(node):
    projects = _cached("projects", lambda: _fetch("/dcc/houdini/importer/tokens", "projects", []))
    return _flat(projects) if projects else ["", "FLUX injoignable ou aucun projet"]

def menu_seq(node):
    return _flat(sorted({s["seq"] for s in _shots(node)})) or ["", "aucun shot (apercu sans shot)"]

def menu_shot(node):
    seq = _pval(node, "seq")
    return _flat(sorted(s["shot"] for s in _shots(node) if s["seq"] == seq)) or ["", "-"]

def menu_assets(node):
    assets = _compat(node).get("assets", {})
    picked = _picked(node, "assets")
    ref = assets.get(picked[0]) if picked else None
    out = []
    for name in sorted(assets):
        info = assets[name]
        label = "%s  (%d joints)" % (name, info.get("joint_count", 0))
        if ref is not None and info.get("signature") != ref.get("signature"):
            label += "  autre rig"
        out += [name, label]
    return out or ["", "aucun asset avec squelette"]

def menu_clips(node):
    compat = _compat(node)
    picked = [compat.get("assets", {}).get(a) for a in _picked(node, "assets")]
    picked = [p for p in picked if p]
    fits = None
    for info in picked:
        fits = set(info.get("clips", [])) if fits is None else fits & set(info.get("clips", []))
    out = []
    for clip in compat.get("clips", []):
        if fits is not None and clip["base"] not in fits:
            continue
        label = "%s %s" % (clip["asset"], clip["clip"])
        if clip.get("range"):
            label += "  %d-%d" % tuple(clip["range"])
        out += [clip["base"], label]
    return out or ["", "aucun clip compatible"]

def _points(node):
    """[{"p", "ry", "scale"}] from the SOP in "Points" (orient or N for the heading)."""
    import hou
    sop = hou.node(_pval(node, "points_sop")) if _pval(node, "points_sop") else None
    if sop is None:
        return None
    geo = sop.geometry()
    if geo is None:
        return []
    has_orient = geo.findPointAttrib("orient") is not None
    has_n = geo.findPointAttrib("N") is not None
    has_scale = geo.findPointAttrib("pscale") is not None
    out = []
    for pt in geo.points():
        p = pt.position()
        ry = 0.0
        if has_orient:
            q = hou.Quaternion(pt.attribValue("orient"))
            z = hou.Vector3(0, 0, 1) * q.extractRotationMatrix3()
            ry = math.degrees(math.atan2(z[0], z[2]))
        elif has_n:
            n = pt.attribValue("N")
            if abs(n[0]) + abs(n[2]) > 1e-9:
                ry = math.degrees(math.atan2(n[0], n[2]))
        item = {"p": [p[0], p[1], p[2]], "ry": ry}
        if has_scale:
            item["scale"] = float(pt.attribValue("pscale"))
        out.append(item)
    return out

# ── inputs (1 assets, 2 points, 3 animations) and weight rows ─────────────────
_MAX_ROWS = 16

def _input_stage(node, i):
    try:
        n = node.input(i)
    except Exception:
        n = None
    if n is None:
        return None
    try:
        return n.stage()
    except Exception:
        return None

def _input_assets(node):
    """FLUX asset names on input 1 (assetInfo name of each component), None if unwired."""
    stage = _input_stage(node, 0)
    if stage is None:
        return None
    from pxr import Usd
    out = []
    it = iter(Usd.PrimRange(stage.GetPseudoRoot()))
    for prim in it:
        if prim.IsPseudoRoot():
            continue
        model = Usd.ModelAPI(prim)
        name = (model.GetAssetInfo() or {}).get("name") or (prim.GetName() if model.GetKind() == "component" else "")
        if name:
            if name not in out:
                out.append(str(name))
            it.PruneChildren()
    return out

def _input_sources(node):
    """{asset: {"file", "prim"}}: the file each asset of input 1 comes from (reference or
    payload on disk), so an asset without a FLUX component still shows as a static mesh."""
    stage = _input_stage(node, 0)
    if stage is None:
        return {}
    from pxr import Pcp, Usd
    out = {}
    it = iter(Usd.PrimRange(stage.GetPseudoRoot()))
    for prim in it:
        if prim.IsPseudoRoot():
            continue
        model = Usd.ModelAPI(prim)
        name = (model.GetAssetInfo() or {}).get("name") or (prim.GetName() if model.GetKind() == "component" else "")
        if not name:
            continue
        it.PruneChildren()
        if name in out:
            continue
        try:
            arcs = Usd.PrimCompositionQuery(prim).GetCompositionArcs()
        except Exception:
            arcs = []
        for arc in arcs:
            if arc.GetArcType() not in (Pcp.ArcTypeReference, Pcp.ArcTypePayload):
                continue
            layer = arc.GetTargetLayer()
            path = layer.realPath if layer is not None else ""
            if path and os.path.isfile(path):
                out[str(name)] = {"file": path.replace(chr(92), "/"),
                                  "prim": arc.GetTargetPrimPath().pathString}
                break
    return out

def _input_looks(node):
    """{asset: {"variants": {set: selection}, "inactive": [relative path]}}: the FLUX
    Import choices of input 1 (an animation unchecked there must not play in the crowd)."""
    stage = _input_stage(node, 0)
    if stage is None:
        return {}
    from pxr import Usd
    out = {}
    it = iter(Usd.PrimRange(stage.GetPseudoRoot()))
    for prim in it:
        if prim.IsPseudoRoot():
            continue
        model = Usd.ModelAPI(prim)
        name = (model.GetAssetInfo() or {}).get("name") or (prim.GetName() if model.GetKind() == "component" else "")
        if not name:
            continue
        it.PruneChildren()
        if name in out:
            continue
        sets = prim.GetVariantSets()
        variants = {}
        for vs in sets.GetNames():
            sel = sets.GetVariantSelection(vs)
            if sel:
                variants[str(vs)] = str(sel)
        inactive = []
        sub = iter(Usd.PrimRange(prim, Usd.PrimAllPrimsPredicate))
        for p in sub:
            if p != prim and not p.IsActive():
                inactive.append(p.GetPath().MakeRelativePath(prim.GetPath()).pathString)
                sub.PruneChildren()
        out[str(name)] = {"variants": variants, "inactive": inactive}
    return out

def _input_points(node):
    """[{"p", "ry", "scale"}] from the first points prim of input 2, None if unwired."""
    stage = _input_stage(node, 1)
    if stage is None:
        return None
    import hou
    from pxr import Gf, Usd, UsdGeom
    t = Usd.TimeCode(hou.frame())
    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.PointBased):
            continue
        pb = UsdGeom.PointBased(prim)
        pts = pb.GetPointsAttr().Get(t) or []
        xf = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(t)
        api = UsdGeom.PrimvarsAPI(prim)
        def _pv(name):
            v = api.GetPrimvar(name)
            return v.ComputeFlattened(t) if v and v.HasValue() else None
        orient = _pv("orient")
        normals = _pv("N")
        if normals is None:
            normals = pb.GetNormalsAttr().Get(t)
        scale = _pv("pscale")
        if scale is None and prim.IsA(UsdGeom.Points):
            widths = UsdGeom.Points(prim).GetWidthsAttr().Get(t)
            scale = [w * 0.5 for w in widths] if widths else None     # width = 2 * pscale
        out = []
        for i, p in enumerate(pts):
            wp = xf.Transform(Gf.Vec3d(p[0], p[1], p[2]))
            ry = 0.0
            if orient is not None and i < len(orient):
                q = orient[i]
                rot = Gf.Rotation(Gf.Quatd(float(q.GetReal()), Gf.Vec3d(q.GetImaginary())))
                z = rot.TransformDir(Gf.Vec3d(0, 0, 1))
                ry = math.degrees(math.atan2(z[0], z[2]))
            elif normals is not None and i < len(normals):
                n = normals[i]
                if abs(n[0]) + abs(n[2]) > 1e-9:
                    ry = math.degrees(math.atan2(n[0], n[2]))
            item = {"p": [wp[0], wp[1], wp[2]], "ry": ry}
            if scale is not None and i < len(scale) and scale[i] > 0:
                item["scale"] = float(scale[i])
            out.append(item)
        return out
    return []

def _input_clips(node, compat):
    """Published clips (bases) animating input 3, None if unwired."""
    stage = _input_stage(node, 2)
    if stage is None:
        return None
    from pxr import UsdSkel
    bases = sorted((c["base"] for c in compat.get("clips", [])), key=len, reverse=True)
    out = []
    for prim in stage.Traverse():
        if not prim.IsA(UsdSkel.Animation):
            continue
        for spec in prim.GetPrimStack():
            ident = os.path.basename(spec.layer.identifier or "")
            hit = next((b for b in bases if ident.startswith(b + "_") or ident.startswith(b + ".")), None)
            if hit:
                if hit not in out:
                    out.append(hit)
                break
    return out

def _json(node, name, default):
    try:
        return json.loads(_pval(node, name) or "null") or default
    except Exception:
        return default

def _fill_rows(node, prefix, names, labels):
    """One row per name with its weight; a weight set earlier on this node comes back."""
    if node.parm(prefix + "_count") is None:
        return
    memory = _json(node, prefix + "_memory", {})
    for i in range(1, int(node.evalParm(prefix + "_count")) + 1):
        old = _pval(node, "%s_id%d" % (prefix, i))
        if old:
            memory[old] = float(node.evalParm("%s_w%d" % (prefix, i)))
    names = list(names)[:_MAX_ROWS]
    _set(node, prefix + "_count", len(names))
    for i in range(1, _MAX_ROWS + 1):
        name = names[i - 1] if i <= len(names) else ""
        _set(node, "%s_id%d" % (prefix, i), name)
        _set(node, "%s_label%d" % (prefix, i), labels.get(name, name) if name else "")
        if name:
            _set(node, "%s_w%d" % (prefix, i), memory.get(name, 1.0))
    _set(node, prefix + "_memory", json.dumps(memory, sort_keys=True))

def _weights(node, prefix):
    out = {}
    if node.parm(prefix + "_count") is None:
        return out
    for i in range(1, int(node.evalParm(prefix + "_count")) + 1):
        name = _pval(node, "%s_id%d" % (prefix, i))
        if name:
            out[name] = float(node.evalParm("%s_w%d" % (prefix, i)))
    return out

def read_inputs(node, quiet=False):
    """Assets of input 1 and clips of input 3 into the weight rows (menus if unwired)."""
    compat = _compat(node)
    known = compat.get("assets", {})
    assets = _input_assets(node)
    if assets is None:
        assets = _picked(node, "assets")
    clips = _input_clips(node, compat)
    if clips is None:
        clips = _picked(node, "clips")
    labels = {}
    for a in assets:
        info = known.get(a)
        labels[a] = ("%s  (%d joints)" % (a, info.get("joint_count", 0))) if info else a + "  (pas de squelette FLUX)"
    _fill_rows(node, "asset", assets, labels)
    clip_labels = {}
    for c in compat.get("clips", []):
        lbl = "%s %s" % (c["asset"], c["clip"])
        if c.get("range"):
            lbl += "  %d-%d" % tuple(c["range"])
        clip_labels[c["base"]] = lbl
    _fill_rows(node, "clip", clips, clip_labels)
    if not quiet:
        _status(node, "%d asset(s), %d anim(s)" % (len(assets), len(clips)))
    return assets, clips

def _refresh_crowd_layers():
    """Houdini keeps every layer it opened: the crowd layer and its _noise sublayer are
    rewritten by FLUX, so they are read again (else the old noise stays on screen)."""
    try:
        from pxr import Sdf
        for layer in Sdf.Layer.GetLoadedLayers():
            ident = (layer.realPath or layer.identifier or "").replace(chr(92), "/")
            if "/crowd_work/" in ident or "_CROWD" in os.path.basename(ident) or \
                    os.path.basename(ident).startswith("CROWD"):
                layer.Reload(True)
    except Exception:
        pass

def _reload(node):
    _refresh_crowd_layers()
    n = node.node("sublayer")
    btn = n.parm("reload") if n is not None else None
    if btn is not None:
        try:
            btn.pressButton()
        except Exception:
            pass

def _build(node, publish):
    project, seq, shot = _pval(node, "project"), _pval(node, "seq"), _pval(node, "shot")
    if not project:
        _status(node, "Choisis un projet"); return
    if not (seq and shot):
        if publish:
            _status(node, "Publier demande une sequence et un shot (l'apercu marche sans)"); return
        seq = shot = ""
    assets, clips = read_inputs(node, quiet=True)
    if not assets:
        _status(node, "Aucun asset : branche des FLUX Import sur l'entree 1 (ou choisis-les dans les menus)"); return
    pts = _input_points(node)
    if pts is None:
        pts = _points(node)
    if pts is None:
        _status(node, "Aucun point : branche des points sur l'entree 2 (ou remplis Points)"); return
    if not pts:
        _status(node, "Les points de l'entree 2 sont vides"); return
    payload = {"project": project, "seq": seq, "shot": shot, "group": _pval(node, "group") or "crowd",
               "points": pts, "components": assets, "clips": clips, "sources": _input_sources(node),
               "looks": _input_looks(node),
               "rot_noise": _fval(node, "rot_noise", 0.0),
               "noise_freq": _fval(node, "noise_freq", 1.0),
               "variations": 0 if _pval(node, "crowd_mode") == "unique" else max(1, int(_fval(node, "variations", 8.0))),
               "component_weights": _weights(node, "asset"), "clip_weights": _weights(node, "clip"),
               "seed": int(node.evalParm("seed")),
               "offset": [node.evalParm("offsetx"), node.evalParm("offsety")],
               "speed": [node.evalParm("speedx"), node.evalParm("speedy")],
               "publish": bool(publish)}
    _status(node, "FLUX ecrit la foule...")
    r = _post("/dcc/houdini/crowd/build", payload)
    if not r.get("ok"):
        _status(node, "Echec : %s" % r.get("error", "?")); return
    msg = "%d agent(s)" % r.get("agents", 0)
    if r.get("variations"):
        msg += " (%d variation(s) instanciees)" % r["variations"]
    if node.parm("rot_noise") is None:
        msg += " (pas de noise : HDA FLUX Crowd a reconstruire)"
    elif _fval(node, "rot_noise", 0.0) > 0:
        msg += ", noise sur %d" % r.get("noised", 0)
    if publish:
        # The shot stage now sublayers the published crowd (LAST): the preview is dropped
        # so the agents are never there twice (FLUX Shot > Resolve shows the publish).
        _set(node, "resolved_path", "")
        _reload(node)
        msg = "Publie %s %s (stage %s) : %s. Visible via FLUX Shot (Resolve)" % (
            r.get("base", ""), r.get("version", ""), r.get("stage") or "inchange", msg)
    else:
        _set(node, "resolved_path", str(r.get("path", "")).replace(chr(92), "/"))
        _reload(node)
        msg = "Apercu : " + msg
    if r.get("info"):
        msg += "  |  " + " ; ".join(r["info"][:5])
    if r.get("warnings"):
        msg += "  |  " + " ; ".join(r["warnings"][:3])
    _status(node, msg)

def generate(node):
    _build(node, False)

def publish(node):
    _build(node, True)

def reload(node):
    """Fresh module from FLUX (a fix applies without restarting Houdini), fresh lists."""
    r = _get("/dcc/houdini/crowd/module")
    if r.get("code"):
        exec(r["code"], globals())
    globals()["_cache"].clear()
    globals()["_reload"](node)
    globals()["read_inputs"](node, quiet=True)
    shots = globals()["_shots"](node)
    compat = globals()["_compat"](node)
    _status(node, "Recharge : %d shot(s), %d asset(s) avec squelette" % (
        len(shots), len(compat.get("assets", {}))))

def on_created(node):
    threading.Thread(target=lambda: (_shots(node), _compat(node)), daemon=True).start()

def on_loaded(node):
    threading.Thread(target=lambda: (_shots(node), _compat(node)), daemon=True).start()
'''


def _build_code(hda_path: str) -> str:
    from dcc.houdini.hda.preserve_instances import RESTORE, snapshot

    _snapshot = snapshot('hou.lopNodeTypeCategory()', NODE_NAME).replace("{{", "{").replace("}}", "}")
    _restore = RESTORE
    from dcc.houdini.hda.hda_common import FINALIZE as _finalize, ICON_PATH as icon_path
    from dcc.houdini.hda.hda_common import INPUT_LABELS as input_labels

    return f'''
import hou
{_snapshot}

_HDA_PATH = {hda_path!r}
_ICON_PATH = {icon_path!r}
_NAME = {NODE_NAME!r}
_PY = hou.scriptLanguage.Python
_PM_CODE = {BOOTSTRAP!r}
MAX_ROWS = 16
_CATEGORY = hou.lopNodeTypeCategory()
_INPUT_LABELS = ("Assets", "Points", "Anims")

def _menu(name, label, default, fn, help_txt, toggle=False):
    t = hou.StringParmTemplate(name, label, 1, default_value=(default,), help=help_txt)
    t.setItemGeneratorScript("hou.phm()." + fn + "(kwargs['node'])")
    t.setItemGeneratorScriptLanguage(_PY)
    if toggle:
        t.setMenuType(hou.menuType.StringToggle)
    return t

_ptg = hou.ParmTemplateGroup()
_ptg.append(_menu("project", "Projet", "", "menu_project", "FLUX project"))
_ptg.append(_menu("seq", "Sequence", "", "menu_seq", "Sequence of the shot"))
_ptg.append(_menu("shot", "Shot", "", "menu_shot", "Shot that receives the crowd layer"))
_ptg.append(hou.StringParmTemplate("group", "Groupe", 1, default_value=("crowd",),
                                   help="One crowd layer per group (SEQ_SHOT_CROWD_<GROUPE>)"))
_ptg.append(hou.SeparatorParmTemplate("sep_agents"))
_ptg.append(hou.ButtonParmTemplate("btn_inputs", "Lire les entrees",
                                   script_callback="hou.phm().read_inputs(kwargs['node'])",
                                   script_callback_language=_PY,
                                   help="Entree 1 : assets, entree 2 : points, entree 3 : anims"))

def _rows(prefix, label, help_txt):
    f = hou.FolderParmTemplate(prefix + "_folder", label, folder_type=hou.folderType.Collapsible)
    f.setConditional(hou.parmCondType.HideWhen, "{{ " + prefix + "_count == 0 }}")
    f.addParmTemplate(hou.IntParmTemplate(prefix + "_count", "count", 1, default_value=(0,), is_hidden=True))
    f.addParmTemplate(hou.StringParmTemplate(prefix + "_memory", "memory", 1, default_value=("{{}}",), is_hidden=True))
    for i in range(1, MAX_ROWS + 1):
        n = str(i)
        hide = "{{ " + prefix + "_id" + n + ' == "" }}'
        w = hou.FloatParmTemplate(prefix + "_w" + n, "Poids", 1, default_value=(1.0,), min=0.0, max=10.0,
                                  min_is_strict=True, help=help_txt)
        w.setConditional(hou.parmCondType.HideWhen, hide)
        w.setJoinWithNext(True)
        f.addParmTemplate(w)
        l = hou.StringParmTemplate(prefix + "_label" + n, "", 1, default_value=("",))
        l.setConditional(hou.parmCondType.HideWhen, hide)
        f.addParmTemplate(l)
        f.addParmTemplate(hou.StringParmTemplate(prefix + "_id" + n, "id", 1, default_value=("",), is_hidden=True))
    return f

_ptg.append(_rows("asset", "Assets (entree 1)", "Plus haut = plus d'agents de cet asset. 0 = jamais."))
_ptg.append(_rows("clip", "Anims (entree 3)", "Plus haut = cette anim plus souvent. 0 = jamais. "
                                              "Chaque agent ne recoit qu'une anim de son rig."))
_menus = hou.FolderParmTemplate("no_inputs", "Sans entrees (menus)", folder_type=hou.folderType.Collapsible)
_menus.addParmTemplate(hou.StringParmTemplate("points_sop", "Points", 1, default_value=("",),
                                            string_type=hou.stringParmType.NodeReference,
                                            help="Used when input 2 is empty: SOP whose points place the agents"))
_menus.addParmTemplate(_menu("assets", "Assets", "", "menu_assets",
                           "Used when input 1 is empty (same rig = same skeleton signature)", toggle=True))
_menus.addParmTemplate(_menu("clips", "Clips", "", "menu_clips",
                           "Used when input 3 is empty (clips that fit every picked asset)", toggle=True))
_ptg.append(_menus)
_ptg.append(hou.IntParmTemplate("seed", "Graine (seed)", 1, default_value=(0,)))
_ptg.append(hou.FloatParmTemplate("offset", "Decalage min / max", 2, default_value=(0.0, 0.0),
                                  help="Time offset of each agent's clip, in frames"))
_ptg.append(hou.FloatParmTemplate("speed", "Vitesse min / max", 2, default_value=(1.0, 1.0),
                                  help="Playback speed of each agent's clip (2 = twice as fast)"))
_ptg.append(hou.FloatParmTemplate("rot_noise", "Noise rotation joints", 1, default_value=(0.0,), min=0.0, max=45.0,
                                  help="Degres : rotation aleatoire par joint et par agent (pas la racine), "
                                       "sur l'anim ou, sans anim, sur la pose de repos. Il faut un squelette."))
_ptg.append(hou.FloatParmTemplate("noise_freq", "Vitesse du noise", 1, default_value=(1.0,), min=0.0, max=5.0,
                                  help="Oscillations par seconde du noise (propre a chaque agent). "
                                       "0 = decalage fixe. Agents sans anim : toujours fixe."))
_ptg.append(hou.MenuParmTemplate("crowd_mode", "Mode", ("instanced", "unique"),
                                 menu_labels=("Instancie (leger)", "Unique (lourd)"), default_value=0,
                                 help="Instancie : quelques variations par asset et par anim, les agents en sont "
                                      "des instances (geo et squelette partages). Unique : chaque agent a sa propre "
                                      "anim, son decalage et son noise (plus lourd)."))
_var = hou.IntParmTemplate("variations", "Variations", 1, default_value=(8,), min=1, max=64,
                           help="Par asset et par anim : nombre de versions differentes (decalage, vitesse, "
                                "noise) que les agents se partagent. La geo et son squelette sont instancies "
                                "ensemble : un skin ne peut pas etre partage entre deux poses.")
_var.setConditional(hou.parmCondType.HideWhen, '{{ crowd_mode == "unique" }}')
_ptg.append(_var)
_ptg.append(hou.MenuParmTemplate("geo_display", "Geometrie", ("proxy", "render"),
                                 menu_labels=("Proxy (leger)", "Geo complete"), default_value=0,
                                 help="Proxy: purpose=proxy meshes in the viewport. Geo complete: render meshes."))
_ptg.append(hou.SeparatorParmTemplate("sep_actions"))
_ptg.append(hou.ButtonParmTemplate("btn_generate", "Generer (apercu)",
                                   script_callback="hou.phm().generate(kwargs['node'])",
                                   script_callback_language=_PY,
                                   help="Writes a preview layer in the shot and shows it here"))
_ptg.append(hou.ButtonParmTemplate("btn_publish", "Publier la foule",
                                   script_callback="hou.phm().publish(kwargs['node'])",
                                   script_callback_language=_PY,
                                   help="Publishes SEQ_SHOT_CROWD[_GROUPE] and regenerates the shot stage"))
_ptg.append(hou.SeparatorParmTemplate("sep_resolved"))
_ptg.append(hou.StringParmTemplate("resolved_path", "Fichier charge", 1, default_value=("",)))
_ptg.append(hou.ButtonParmTemplate("btn_reload", "Recharger",
                                   script_callback="hou.phm().reload(kwargs['node'])",
                                   script_callback_language=_PY,
                                   help="Re-read the crowd layer and the asset / clip lists"))
_ptg.append(hou.StringParmTemplate("status_msg", "Statut", 1, default_value=("",)))

_stage = hou.node("/stage") or hou.node("/").createNode("lopnet", "stage")
_old = _stage.node("__flux_crowd_build__")
if _old is not None:
    _old.destroy()
_sub = _stage.createNode("subnet", "__flux_crowd_build__")
for _c in _sub.children():
    if _c.type().name() != "output":
        _c.destroy()
_out = next((c for c in _sub.children() if c.type().name() == "output"), None) \\
    or _sub.createNode("output", "output0")
# The inputs are sources (assets, points, clips): the node outputs the crowd layer alone.
_subl = _sub.createNode("sublayer", "sublayer")
_subl.parm("filepath1").setExpression('chs("../resolved_path")', hou.exprLanguage.Hscript)
_full = _sub.createNode("configureprimitive", "show_render_geo")
_full.setInput(0, _subl)
_full.parm("primpattern").set("/crowd/**/geo/render/** /crowd_protos/**/geo/render/**")
_full.parm("setpurpose").set(1)
_full.parm("purpose").set("default")
_hide = _sub.createNode("configureprimitive", "hide_proxy")
_hide.setInput(0, _full)
_hide.parm("primpattern").set("/crowd/**/geo/proxy /crowd_protos/**/geo/proxy")
_hide.parm("setvisibility").set(1)
_hide.parm("visibility").set("invisible")
_sw = _sub.createNode("switch", "geo_display")
_sw.setInput(0, _subl)
_sw.setInput(1, _hide)
_sw.parm("input").setExpression('ch("../geo_display")', hou.exprLanguage.Hscript)
_out.setInput(0, _sw)
_sub.layoutChildren()

_asset = _sub.createDigitalAsset(name=_NAME, hda_file_name=_HDA_PATH, description={LABEL!r},
                                 min_num_inputs=0, max_num_inputs=3, version="1.0")
{_finalize}
{input_labels}
{_restore}
result = {{"ok": True, "path": _HDA_PATH, "node_type": "Lop/" + _NAME}}
'''


def build_hda(hda_path: str) -> dict:
    """Build the FLUX Crowd LOP HDA in the running Houdini."""
    log.info("Building FLUX Crowd HDA -> %s", hda_path)
    resp = houdini_client.run(_build_code(hda_path))
    if resp.get("ok"):
        log.info("FLUX Crowd HDA built: %s", hda_path)
    else:
        log.error("FLUX Crowd HDA build failed: %s", resp.get("error"))
    return resp
