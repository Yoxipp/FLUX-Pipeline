"""
FLUX - Houdini "FLUX Crowd" HDA for Solaris (A7, ADR 0022).

Draws agents on the points of a SOP and writes the shot crowd layer:
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

def _get(path, **params):
    url = f"http://127.0.0.1:{_flux_port()}" + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v})
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
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
    """fetch() -> (data, ok). Only good answers are cached: an error is retried."""
    now = time.monotonic()
    if key in _cache and now < _cache[key][0]:
        return _cache[key][1]
    data, ok = fetch()
    if ok:
        _cache[key] = (now + _TTL, data)
    return data

def _fetch(path, field, empty, **params):
    r = _get(path, **params)
    if field is None:
        return (r if not r.get("_offline") else empty), not r.get("_offline")
    return r.get(field, empty), not r.get("_offline")

def _pval(node, name):
    p = node.parm(name)
    return p.evalAsString() if p is not None else ""

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
    return _cached("shots:" + project,
                   lambda: _fetch("/dcc/houdini/shot_switch/shots", "shots", [], project=project))

def _compat(node, fresh=False):
    project = _pval(node, "project")
    if not project:
        return {"assets": {}, "clips": []}
    key = "compat:" + project
    if fresh:
        _cache.pop(key, None)
    return _cached(key, lambda: _fetch("/usd/crowd/compat", None, {"assets": {}, "clips": []}, project=project))

def _picked(node, name):
    return [v for v in _pval(node, name).split() if v]

def menu_project(node):
    projects = _cached("projects", lambda: _fetch("/dcc/houdini/importer/tokens", "projects", []))
    return _flat(projects) if projects else ["", "FLUX injoignable ou aucun projet"]

def menu_seq(node):
    return _flat(sorted({s["seq"] for s in _shots(node)})) or ["", "aucun shot"]

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

def _reload(node):
    n = node.node("sublayer")
    btn = n.parm("reload") if n is not None else None
    if btn is not None:
        try:
            btn.pressButton()
        except Exception:
            pass

def _build(node, publish):
    project, seq, shot = _pval(node, "project"), _pval(node, "seq"), _pval(node, "shot")
    if not (project and seq and shot):
        _status(node, "Choisis projet / sequence / shot"); return
    assets = _picked(node, "assets")
    if not assets:
        _status(node, "Choisis au moins un asset"); return
    pts = _points(node)
    if pts is None:
        _status(node, "Remplis Points (un SOP de points)"); return
    if not pts:
        _status(node, "Le SOP de Points n'a aucun point"); return
    payload = {"project": project, "seq": seq, "shot": shot, "group": _pval(node, "group") or "crowd",
               "points": pts, "components": assets, "clips": _picked(node, "clips"),
               "seed": int(node.evalParm("seed")),
               "offset": [node.evalParm("offsetx"), node.evalParm("offsety")],
               "speed": [node.evalParm("speedx"), node.evalParm("speedy")],
               "publish": bool(publish)}
    _status(node, "FLUX ecrit la foule...")
    r = _post("/dcc/houdini/crowd/build", payload)
    if not r.get("ok"):
        _status(node, "Echec : %s" % r.get("error", "?")); return
    msg = "%d agent(s)" % r.get("agents", 0)
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
    if r.get("warnings"):
        msg += "  |  " + " ; ".join(r["warnings"][:3])
    _status(node, msg)

def generate(node):
    _build(node, False)

def publish(node):
    _build(node, True)

def reload(node):
    _compat(node, fresh=True)
    _reload(node)
    _status(node, "Recharge")

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

    return f'''
import hou
{_snapshot}

_HDA_PATH = {hda_path!r}
_ICON_PATH = {icon_path!r}
_NAME = {NODE_NAME!r}
_PY = hou.scriptLanguage.Python
_PM_CODE = {BOOTSTRAP!r}

def _menu(name, label, default, fn, help_txt, toggle=False):
    t = hou.StringParmTemplate(name, label, 1, default_value=(default,), help=help_txt)
    t.setItemGeneratorScript("hou.phm()." + fn + "(kwargs['node'])")
    t.setItemGeneratorScriptLanguage(_PY)
    if toggle:
        t.setMenuType(hou.menuType.StringToggle)
    return t

_ptg = hou.ParmTemplateGroup()
_ptg.append(_menu("project", "Project", "", "menu_project", "FLUX project"))
_ptg.append(_menu("seq", "Sequence", "", "menu_seq", "Sequence of the shot"))
_ptg.append(_menu("shot", "Shot", "", "menu_shot", "Shot that receives the crowd layer"))
_ptg.append(hou.StringParmTemplate("group", "Groupe", 1, default_value=("crowd",),
                                   help="One crowd layer per group (SEQ_SHOT_CROWD_<GROUPE>)"))
_ptg.append(hou.SeparatorParmTemplate("sep_agents"))
_ptg.append(hou.StringParmTemplate("points_sop", "Points", 1, default_value=("",),
                                   string_type=hou.stringParmType.NodeReference,
                                   help="SOP whose points place the agents (P, orient or N, pscale)"))
_ptg.append(_menu("assets", "Assets", "", "menu_assets",
                  "Assets drawn per agent (same rig = same skeleton signature)", toggle=True))
_ptg.append(_menu("clips", "Clips", "", "menu_clips",
                  "Animation clips that fit every picked asset (empty = rest pose)", toggle=True))
_ptg.append(hou.IntParmTemplate("seed", "Seed", 1, default_value=(0,)))
_ptg.append(hou.FloatParmTemplate("offset", "Decalage min / max", 2, default_value=(0.0, 0.0),
                                  help="Time offset of each agent's clip, in frames"))
_ptg.append(hou.FloatParmTemplate("speed", "Vitesse min / max", 2, default_value=(1.0, 1.0),
                                  help="Playback speed of each agent's clip (2 = twice as fast)"))
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
_ptg.append(hou.StringParmTemplate("resolved_path", "Resolved Path", 1, default_value=("",)))
_ptg.append(hou.ButtonParmTemplate("btn_reload", "Reload",
                                   script_callback="hou.phm().reload(kwargs['node'])",
                                   script_callback_language=_PY,
                                   help="Re-read the crowd layer and the asset / clip lists"))
_ptg.append(hou.StringParmTemplate("status_msg", "Status", 1, default_value=("",)))

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
_subl = _sub.createNode("sublayer", "sublayer")
_subl.setInput(0, _sub.indirectInputs()[0])
_subl.parm("filepath1").setExpression('chs("../resolved_path")', hou.exprLanguage.Hscript)
_full = _sub.createNode("configureprimitive", "show_render_geo")
_full.setInput(0, _subl)
_full.parm("primpattern").set("/crowd/**/geo/render/**")
_full.parm("setpurpose").set(1)
_full.parm("purpose").set("default")
_hide = _sub.createNode("configureprimitive", "hide_proxy")
_hide.setInput(0, _full)
_hide.parm("primpattern").set("/crowd/**/geo/proxy")
_hide.parm("setvisibility").set(1)
_hide.parm("visibility").set("invisible")
_sw = _sub.createNode("switch", "geo_display")
_sw.setInput(0, _subl)
_sw.setInput(1, _hide)
_sw.parm("input").setExpression('ch("../geo_display")', hou.exprLanguage.Hscript)
_out.setInput(0, _sw)
_sub.layoutChildren()

_asset = _sub.createDigitalAsset(name=_NAME, hda_file_name=_HDA_PATH, description={LABEL!r},
                                 min_num_inputs=0, max_num_inputs=1, version="1.0")
{_finalize}
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
