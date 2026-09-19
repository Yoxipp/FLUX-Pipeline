"""
FLUX - Houdini "FLUX Shot" HDA for Solaris (A5, 2026-09-18).

The shot selector of the sequence scene: one node that loads the stage of the chosen
shot (ADR 0020: casting, animation per character, layout, sequence light rig...) and
drives the scene from it:
  * menus: project, sequence, shot, version (LAST / vNNN);
  * the shot stage is sublayered; "Geometrie" shows the proxy or the render meshes;
  * frame range + fps of the shot applied to the timeline when the shot changes
    ("Suivre la plage du shot"), camera found in the stage (menu, auto = first one);
  * a Layer Break at the output: everything authored downstream (the shot lights) is
    a new layer. "Publier le light rig du shot" writes those layers (USD ROP, strip
    layers above layer breaks) to a temp file inside Houdini, then FLUX publishes it
    as SEQ_SHOT_LIGHT (vNNN + LAST) and regenerates the shot stage.
The render ROP of the sequence scene follows this node (frame range, camera, output).

Same bootstrap pattern as FLUX Anim: the HDA holds a few lines that fetch the real
module from GET /dcc/houdini/shot_switch/module, so a fix needs no HDA rebuild.
"""

from __future__ import annotations

from pathlib import Path

from core.logger import get_logger
from dcc.houdini.client import houdini_client

log = get_logger(__name__)

NODE_NAME = "flux_shot"
LABEL = "FLUX Shot"

BOOTSTRAP: str = '''
import json, os, urllib.request

def _flux_port():
    try:
        return int(os.environ.get("FLUX_PORT") or
                   open(os.path.join(os.environ.get("APPDATA",""), "FLUX", "backend_port")).read())
    except Exception:
        return 8765

def _load():
    with urllib.request.urlopen(f"http://localhost:{_flux_port()}/dcc/houdini/shot_switch/module", timeout=3) as _r:
        exec(json.loads(_r.read())["code"], globals())

try:
    _load()
except Exception:
    def _dead_menu(*a, **kw): return ["", "FLUX offline"]
    for _n in ("menu_project", "menu_seq", "menu_shot", "menu_version", "menu_camera"):
        globals()[_n] = _dead_menu
    def _offline(node, name):
        try:
            _load()
            globals()[name](node)
        except Exception:
            node.parm("status_msg").set("FLUX offline : demarre FLUX puis clique Resolve")
    def resolve_path(node): _offline(node, "resolve_path")
    def apply_frame_range(node): _offline(node, "apply_frame_range")
    def publish_light(node): _offline(node, "publish_light")
    def on_created(node): pass
    def on_loaded(node): pass
'''

# Served by GET /dcc/houdini/shot_switch/module, exec()'d by the bootstrap (runs inside Houdini).
MODULE_FUNCTIONS: str = '''
import json, os, tempfile, threading, time, urllib.parse, urllib.request

def _flux_port():
    try:
        return int(os.environ.get("FLUX_PORT") or
                   open(os.path.join(os.environ.get("APPDATA",""), "FLUX", "backend_port")).read())
    except Exception:
        return 8765

def _get(path, **params):
    url = f"http://localhost:{_flux_port()}" + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v})
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.loads(r.read())
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def _post(path, payload):
    req = urllib.request.Request(f"http://localhost:{_flux_port()}" + path,
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        try:
            return {"ok": False, "error": json.loads(exc.read()).get("detail", str(exc))}
        except Exception:
            return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

_TTL = 30.0
_cache = {}

def _cached(key, fetch):
    now = time.monotonic()
    if key in _cache and now < _cache[key][0]:
        return _cache[key][1]
    data = fetch()
    _cache[key] = (now + _TTL, data)
    return data

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

def _shots(node, fresh=False):
    project = _pval(node, "project")
    if not project:
        return []
    key = "shots:" + project
    if fresh:
        _cache.pop(key, None)
    return _cached(key, lambda: _get("/dcc/houdini/shot_switch/shots", project=project).get("shots", []))

def _current(node):
    seq, shot = _pval(node, "seq"), _pval(node, "shot")
    return next((s for s in _shots(node) if s["seq"] == seq and s["shot"] == shot), None)

def menu_project(node):
    projects = _cached("projects", lambda: _get("/dcc/houdini/importer/tokens").get("projects", []))
    return _flat(projects) if projects else ["", "aucun projet"]

def menu_seq(node):
    return _flat(sorted({s["seq"] for s in _shots(node)})) or ["", "aucun shot genere"]

def menu_shot(node):
    seq = _pval(node, "seq")
    return _flat(sorted(s["shot"] for s in _shots(node) if s["seq"] == seq)) or ["", "-"]

def menu_version(node):
    item = _current(node)
    return _flat(["LAST"] + list(reversed((item or {}).get("versions", []))))

def _stage_cameras(node):
    try:
        from pxr import UsdGeom
        stage = node.node("sublayer").stage()
        return [str(p.GetPath()) for p in stage.Traverse() if p.IsA(UsdGeom.Camera)]
    except Exception:
        return []

def menu_camera(node):
    cams = _stage_cameras(node)
    return _flat(cams) if cams else ["", "pas de camera (layout non publie)"]

def _reload(node):
    for inner in ("sublayer",):
        n = node.node(inner)
        btn = n.parm("reload") if n is not None else None
        if btn is not None:
            try:
                btn.pressButton()
            except Exception:
                pass

def apply_frame_range(node):
    """Timeline and fps of the scene = the shot's (frame range written on its stage)."""
    import hou
    try:
        start, end = int(node.evalParm("frame_rangex")), int(node.evalParm("frame_rangey"))
        fps = float(node.evalParm("fps"))
    except Exception:
        _status(node, "Plage illisible"); return
    if end < start:
        _status(node, "Pas de plage pour ce shot (Production)"); return
    if fps > 0 and abs(hou.fps() - fps) > 1e-6:
        hou.setFps(fps)
    hou.playbar.setFrameRange(start, end)
    hou.playbar.setPlaybackRange(start, end)
    hou.setFrame(start)

def resolve_path(node):
    if not _pval(node, "project"):
        _status(node, "Choisis un projet"); return
    _shots(node, fresh=True)
    item = _current(node)
    if item is None:
        _set(node, "resolved_path", "")
        _status(node, "Shot sans stage : genere-le depuis la page USD de FLUX"); return
    version = _pval(node, "version") or "LAST"
    path = item["last"] if version == "LAST" else item.get("files", {}).get(version, "")
    if not path:
        _set(node, "resolved_path", "")
        _status(node, "Version introuvable : " + version); return
    _set(node, "resolved_path", path.replace(chr(92), "/"))
    rng = item.get("range") or [1, 0]
    node.parmTuple("frame_range").set((int(rng[0]), int(rng[1])))
    _set(node, "fps", float(item.get("fps") or 24))
    _reload(node)
    try:
        node.cook(force=True)
    except Exception:
        pass
    cams = _stage_cameras(node)
    auto = node.parm("camera_auto")
    if auto is None or auto.eval():
        _set(node, "camera", cams[0] if cams else "")
    follow = node.parm("follow_range")
    if follow is None or follow.eval():
        apply_frame_range(node)
    msg = "OK  %s %s %s" % (item["seq"], item["shot"], version)
    if item.get("range"):
        msg += "  images %d-%d" % (int(rng[0]), int(rng[1]))
    msg += "  camera " + (_pval(node, "camera") or "aucune")
    _status(node, msg)

def _light_source(node):
    import hou
    path = _pval(node, "light_node")
    if path:
        n = hou.node(path)
        if n is not None:
            return n
    parent = node.parent()
    return parent.displayNode() if parent is not None else None

def publish_light(node):
    """Write the layers authored after this node (the shot lights) and publish them."""
    import hou
    project, seq, shot = _pval(node, "project"), _pval(node, "seq"), _pval(node, "shot")
    if not (project and seq and shot):
        _status(node, "Choisis projet / sequence / shot d'abord"); return
    src = _light_source(node)
    if src is None or src.path() == node.path():
        _status(node, "Branche les lumieres apres ce node (ou remplis Light Node)"); return
    out = os.path.join(tempfile.mkdtemp(prefix="flux_shot_light_"), "light.usda").replace(chr(92), "/")
    rop = node.parent().createNode("usd_rop", "__flux_light_export__")
    try:
        rop.parm("loppath").set(src.path())
        rop.parm("lopoutput").set(out)
        if rop.parm("striplayerbreaks") is not None:
            rop.parm("striplayerbreaks").set(1)
        if rop.parm("savestyle") is not None:
            rop.parm("savestyle").set("flattenimplicitlayers")
        rop.parm("execute").pressButton()
    finally:
        rop.destroy()
    if not os.path.isfile(out):
        _status(node, "Export des lumieres echoue"); return
    r = _post("/dcc/houdini/shot-light/publish", {"project": project, "seq": seq, "shot": shot, "file": out})
    if r.get("ok"):
        _status(node, "Light rig publie : %s %s (stage %s)" % (r.get("base", ""), r.get("version", ""),
                                                               r.get("stage") or "inchange"))
    else:
        _status(node, "Publish echoue : %s" % r.get("error", "?"))

def on_created(node):
    threading.Thread(target=lambda: _shots(node), daemon=True).start()

def on_loaded(node):
    resolve_path(node)
'''


def _build_code(hda_path: str) -> str:
    from dcc.houdini.hda.preserve_instances import RESTORE, snapshot

    _snapshot = snapshot('hou.lopNodeTypeCategory()', NODE_NAME).replace("{{", "{").replace("}}", "}")
    _restore = RESTORE
    icon_path = str(Path(__file__).parents[3] / "resources" / "shelves" / "houdini" / "flux_hda.svg")
    return f'''
import hou
{_snapshot}

_HDA_PATH = {hda_path!r}
_ICON_PATH = {icon_path!r}
_NAME = {NODE_NAME!r}
_PY = hou.scriptLanguage.Python
_PM_CODE = {BOOTSTRAP!r}
_CB = "hou.phm().resolve_path(kwargs['node'])"

def _menu(name, label, default, fn, help_txt, cb=_CB):
    t = hou.StringParmTemplate(name, label, 1, default_value=(default,), help=help_txt)
    t.setItemGeneratorScript("hou.phm()." + fn + "(kwargs['node'])")
    t.setItemGeneratorScriptLanguage(_PY)
    if cb:
        t.setScriptCallback(cb)
        t.setScriptCallbackLanguage(_PY)
    return t

_ptg = hou.ParmTemplateGroup()
_ptg.append(_menu("project", "Project", "", "menu_project", "FLUX project"))
_ptg.append(_menu("seq", "Sequence", "", "menu_seq", "Sequence of the scene"))
_ptg.append(_menu("shot", "Shot", "", "menu_shot", "Shot loaded in the scene"))
_ptg.append(_menu("version", "Version", "LAST", "menu_version", "LAST follows new publishes, vNNN is frozen"))
_ptg.append(hou.MenuParmTemplate("geo_display", "Geometrie", ("proxy", "render"),
                                 menu_labels=("Proxy (leger)", "Geo complete"), default_value=0,
                                 help="Proxy: purpose=proxy meshes in the viewport. Geo complete: render meshes."))
_ptg.append(hou.SeparatorParmTemplate("sep_time"))
_follow = hou.ToggleParmTemplate("follow_range", "Suivre la plage du shot", default_value=True,
                                 help="Changing the shot sets the timeline and fps of the scene")
_ptg.append(_follow)
_ptg.append(hou.IntParmTemplate("frame_range", "Plage", 2, default_value=(1, 0),
                                help="Frame range of the shot (Production), read from its stage"))
_ptg.append(hou.FloatParmTemplate("fps", "FPS", 1, default_value=(24.0,)))
_ptg.append(hou.ButtonParmTemplate("btn_frame_range", "Appliquer la plage",
                                   script_callback="hou.phm().apply_frame_range(kwargs['node'])",
                                   script_callback_language=_PY))
_cauto = hou.ToggleParmTemplate("camera_auto", "Auto", default_value=True,
                                help="Camera = the first camera of the shot stage (layout)")
_cauto.setJoinWithNext(True)
_ptg.append(_cauto)
_cam = _menu("camera", "Camera", "", "menu_camera", "Render camera of the shot", cb=None)
_cam.setConditional(hou.parmCondType.DisableWhen, "{{ camera_auto == 1 }}")
_ptg.append(_cam)
_ptg.append(hou.SeparatorParmTemplate("sep_light"))
_ptg.append(hou.StringParmTemplate("light_node", "Light Node", 1, default_value=("",),
                                   string_type=hou.stringParmType.NodeReference,
                                   help="LOP holding the shot lights (empty = display node of the network)"))
_ptg.append(hou.ButtonParmTemplate("btn_publish_light", "Publier le light rig du shot",
                                   script_callback="hou.phm().publish_light(kwargs['node'])",
                                   script_callback_language=_PY,
                                   help="Publishes the layers authored after this node as SEQ_SHOT_LIGHT"))
_ptg.append(hou.SeparatorParmTemplate("sep_resolved"))
_ptg.append(hou.StringParmTemplate("resolved_path", "Resolved Path", 1, default_value=("",)))
_ptg.append(hou.ButtonParmTemplate("btn_resolve", "Resolve / Reload", script_callback=_CB,
                                   script_callback_language=_PY,
                                   help="Re-read the shot stage from disk"))
_ptg.append(hou.StringParmTemplate("status_msg", "Status", 1, default_value=("",)))

_stage = hou.node("/stage") or hou.node("/").createNode("lopnet", "stage")
_old = _stage.node("__flux_shot_build__")
if _old is not None:
    _old.destroy()
_sub = _stage.createNode("subnet", "__flux_shot_build__")
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
_full.parm("primpattern").set("/assets/**/geo/render/** /sets/**/geo/render/**")
_full.parm("setpurpose").set(1)
_full.parm("purpose").set("default")
_hide = _sub.createNode("configureprimitive", "hide_proxy")
_hide.setInput(0, _full)
_hide.parm("primpattern").set("/assets/**/geo/proxy /sets/**/geo/proxy")
_hide.parm("setvisibility").set(1)
_hide.parm("visibility").set("invisible")
_sw = _sub.createNode("switch", "geo_display")
_sw.setInput(0, _subl)
_sw.setInput(1, _hide)
_sw.parm("input").setExpression('ch("../geo_display")', hou.exprLanguage.Hscript)
# Everything authored after this node is a new layer: the shot light rig publish.
_lb = _sub.createNode("layerbreak", "layerbreak")
_lb.setInput(0, _sw)
_out.setInput(0, _lb)
_sub.layoutChildren()

_asset = _sub.createDigitalAsset(name=_NAME, hda_file_name=_HDA_PATH, description={LABEL!r},
                                 min_num_inputs=0, max_num_inputs=1, version="1.0")
_def = _asset.type().definition()
for _sec, _code in (("PythonModule", _PM_CODE),
                    ("OnCreated", "hou.phm().on_created(kwargs['node'])"),
                    ("OnLoaded", "hou.phm().on_loaded(kwargs['node'])")):
    if _sec in _def.sections():
        _def.sections()[_sec].setContents(_code)
    else:
        _def.addSection(_sec, _code)
try:
    _extra = dict(_def.extraFileOptions())
    for _sec in ("PythonModule", "OnCreated", "OnLoaded"):
        _extra[_sec + ".IsPython"] = True
    _def.setExtraFileOptions(_extra)
except AttributeError:
    pass
_def.setParmTemplateGroup(_ptg)
try:
    import os as _os
    if _os.path.isfile(_ICON_PATH):
        with open(_ICON_PATH, "rb") as _f:
            _bytes = _f.read()
        if "IconSVG" in _def.sections():
            _def.sections()["IconSVG"].setContents(_bytes)
        else:
            _def.addSection("IconSVG", _bytes)
        _def.setIcon("opdef:.?IconSVG")
except Exception:
    pass
_def.save(_HDA_PATH)
hou.hda.installFile(_HDA_PATH, oplibraries_file=None, change_oplibraries_file=False)
_asset.destroy()
{_restore}
result = {{"ok": True, "path": _HDA_PATH, "node_type": "Lop/" + _NAME}}
'''


def build_hda(hda_path: str) -> dict:
    """Build the FLUX Shot LOP HDA in the running Houdini."""
    log.info("Building FLUX Shot HDA -> %s", hda_path)
    resp = houdini_client.run(_build_code(hda_path))
    if resp.get("ok"):
        log.info("FLUX Shot HDA built: %s", hda_path)
    else:
        log.error("FLUX Shot HDA build failed: %s", resp.get("error"))
    return resp
