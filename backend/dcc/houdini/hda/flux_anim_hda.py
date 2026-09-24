"""
FLUX - Houdini "FLUX Anim" HDA for Solaris (2026-09-18).

Plugged after a FLUX Import (or anything that puts a character on the stage), it
applies the animation of one shot to one character:
  * menus by tokens: project, sequence, shot, task (ANIM), character, version (LAST / vNNN),
    listed by the backend (features/importer/shot_anim.list_shot_anims);
  * target prim: the character's prim in the input stage (auto: /assets/<CHARACTER>, else
    the asset prim of the same NAME), changeable from a menu of the input's assets;
  * inside: a Reference LOP that references the shot animation (motion only: /<NAME>/skel/Anim
    + animation source) onto the target prim. Every resolve reloads it (Houdini never
    re-reads a USD file it already opened).
The status says when the target prim is missing or the animation does not drive its
skeleton (joints unknown to the rig).

Same bootstrap pattern as the importer: the HDA holds a few lines that fetch the real
module from GET /dcc/houdini/anim/module, so fixing the module needs no HDA rebuild.
"""

from __future__ import annotations

from pathlib import Path

from core.logger import get_logger
from dcc.houdini.client import houdini_client

log = get_logger(__name__)

NODE_NAME = "flux_anim"
LABEL = "FLUX Anim"

BOOTSTRAP: str = '''
import json, os, urllib.request

def _flux_port():
    try:
        return int(os.environ.get("FLUX_PORT") or
                   open(os.path.join(os.environ.get("APPDATA",""), "FLUX", "backend_port")).read())
    except Exception:
        return 8765

def _load():
    with urllib.request.urlopen(f"http://127.0.0.1:{_flux_port()}/dcc/houdini/anim/module", timeout=3) as _r:
        exec(json.loads(_r.read())["code"], globals())

try:
    _load()
except Exception:
    def _dead_menu(*a, **kw): return ["", "FLUX offline"]
    for _n in ("menu_project", "menu_seq", "menu_shot", "menu_task", "menu_character",
               "menu_version", "menu_target"):
        globals()[_n] = _dead_menu
    def resolve_path(node):
        try:
            _load()
            globals()["resolve_path"](node)
        except Exception:
            node.parm("status_msg").set("FLUX offline : demarre FLUX puis clique Resolve")
    def apply_frame_range(node):
        try:
            _load()
            globals()["apply_frame_range"](node)
        except Exception:
            node.parm("status_msg").set("FLUX offline : demarre FLUX puis clique Resolve")
    def on_created(node): pass
    def on_loaded(node): pass
'''

# Served by GET /dcc/houdini/anim/module, exec()'d by the bootstrap (runs inside Houdini).
MODULE_FUNCTIONS: str = '''
import json, os, threading, time, urllib.parse, urllib.request

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
        with urllib.request.urlopen(url, timeout=3) as r:
            return json.loads(r.read())
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

def _items(node, fresh=False):
    project = _pval(node, "project")
    if not project:
        return []
    key = "anims:" + project
    if fresh:
        _cache.pop(key, None)
    return _cached(key, lambda: _get("/dcc/houdini/anim/publishes", project=project).get("items", []))

def _filtered(node, *fields):
    items = _items(node)
    for f in fields:
        v = _pval(node, f)
        if v:
            items = [i for i in items if i.get(f) == v]
    return items

def menu_project(node):
    projects = _cached("projects", lambda: _get("/dcc/houdini/importer/tokens").get("projects", []))
    return _flat(projects) if projects else ["", "aucun projet"]

def menu_seq(node):
    return _flat(sorted({i["seq"] for i in _items(node)})) or ["", "aucune anim publiee"]

def menu_shot(node):
    return _flat(sorted({i["shot"] for i in _filtered(node, "seq")})) or ["", "-"]

def menu_task(node):
    return _flat(sorted({i["task"] for i in _filtered(node, "seq", "shot")})) or _flat(["ANIM"])

def menu_character(node):
    return _flat(sorted({i["character"] for i in _filtered(node, "seq", "shot", "task")})) or ["", "-"]

def menu_version(node):
    item = _current(node)
    return _flat(["LAST"] + list((item or {}).get("versions", {}))) if item else _flat(["LAST"])

def _current(node):
    items = _filtered(node, "seq", "shot", "task", "character")
    return items[0] if items else None

def _input_stage(node):
    ins = node.inputs()
    try:
        return ins[0].stage() if ins and ins[0] is not None else None
    except Exception:
        return None

def _asset_prims(stage):
    """Character / asset prims of the input: components and SkelRoots, top-most only."""
    out = []
    if stage is None:
        return out
    from pxr import Usd, UsdSkel
    it = iter(Usd.PrimRange(stage.GetPseudoRoot()))
    for prim in it:
        if prim.IsPseudoRoot():
            continue
        if prim.IsA(UsdSkel.Root) or Usd.ModelAPI(prim).GetKind() == "component":
            out.append(str(prim.GetPath()))
            it.PruneChildren()
    return out

def menu_target(node):
    prims = _asset_prims(_input_stage(node))
    return _flat(prims) if prims else ["", "rien en entree"]

def _auto_target(node, item):
    prims = _asset_prims(_input_stage(node))
    for wanted in (item.get("character"), item.get("name")):
        for p in prims:
            if wanted and p.rsplit("/", 1)[-1] == wanted:
                return p
    return "/assets/" + (item.get("character") or item.get("name") or "asset")

def _reload(node):
    ref = node.node("reference")
    btn = ref.parm("reload") if ref is not None else None
    if btn is not None:
        try:
            btn.pressButton()
        except Exception:
            pass

def _check(node, target):
    """Status: does the animation drive the target's skeleton?"""
    try:
        from pxr import Usd, UsdSkel
        src = _input_stage(node)
        if src is None or not src.GetPrimAtPath(target):
            return "ATTENTION : " + target + " absent de l'entree (branche le FLUX Import du perso)"
        node.cook(force=True)             # the reload only dirties the node
        stage = node.stage()
        prim = stage.GetPrimAtPath(target)
        cache = UsdSkel.Cache()
        # The animation source is bound on the character's root: populate from it so
        # the inherited binding is resolved.
        root = UsdSkel.Root(prim) if prim and prim.IsA(UsdSkel.Root) else None
        if root:
            cache.Populate(root, Usd.PrimDefaultPredicate)
        for p in Usd.PrimRange(prim):
            if p.IsA(UsdSkel.Skeleton):
                q = cache.GetSkelQuery(UsdSkel.Skeleton(p))
                if q and q.GetAnimQuery():
                    order = list(q.GetAnimQuery().GetJointOrder())
                    joints = set(UsdSkel.Skeleton(p).GetJointsAttr().Get() or [])
                    missing = [j for j in order if j not in joints]
                    if missing:
                        return "ATTENTION : %d joint(s) inconnus du rig : %s" % (len(missing), ", ".join(missing[:3]))
                    return "OK  %s  (%d joints animes%s)" % (target, len(order), _frame_range(node))
                return "ATTENTION : le squelette de " + target + " n'est pas anime"
        return "ATTENTION : pas de squelette sous " + target
    except Exception as exc:
        return "verification impossible : %s" % exc

def _frame_range(node):
    """", images 1001-1100 a 24 fps" read from the published animation file."""
    try:
        from pxr import Sdf
        layer = Sdf.Layer.FindOrOpen(_pval(node, "resolved_path"))
        if layer is None or not layer.HasStartTimeCode():
            return ""
        fps = layer.timeCodesPerSecond
        return ", images %d-%d a %g fps" % (int(layer.startTimeCode), int(layer.endTimeCode), fps)
    except Exception:
        return ""

def _layer_range(node):
    """(start, end, fps) of the published animation, or None."""
    from pxr import Sdf
    layer = Sdf.Layer.FindOrOpen(_pval(node, "resolved_path"))
    if layer is None or not layer.HasStartTimeCode():
        return None
    fps = layer.framesPerSecond if layer.HasFramesPerSecond() else layer.timeCodesPerSecond
    return int(layer.startTimeCode), int(layer.endTimeCode), float(fps)

def apply_frame_range(node):
    """Button "Appliquer la plage": playbar range + fps of the scene = the animation's
    (V9-01, 2026-09-18). Never automatic: several FLUX Anim can live in one scene."""
    try:
        rng = _layer_range(node)
    except Exception as exc:
        _status(node, "plage illisible : %s" % exc); return
    if rng is None:
        _status(node, "Pas de plage dans l'anim publiee (Resolve d'abord)"); return
    start, end, fps = rng
    import hou
    if abs(hou.fps() - fps) > 1e-6:
        hou.setFps(fps)
    hou.playbar.setFrameRange(start, end)
    hou.playbar.setPlaybackRange(start, end)
    hou.setFrame(start)
    _status(node, "Plage appliquee : images %d-%d a %g fps" % (start, end, fps))

def resolve_path(node):
    if not _pval(node, "project"):
        _status(node, "Choisis un projet"); return
    _items(node, fresh=True)
    item = _current(node)
    if item is None:
        _set(node, "resolved_path", "")
        _status(node, "Aucune anim publiee pour ces tokens"); return
    version = _pval(node, "version") or "LAST"
    path = item["last"] if version == "LAST" else item.get("versions", {}).get(version, "")
    if not path:
        _set(node, "resolved_path", "")
        _status(node, "Version introuvable : " + version); return
    _set(node, "resolved_path", path.replace(chr(92), "/"))
    auto = node.parm("target_auto")
    if auto is None or auto.eval():
        _set(node, "target_prim", _auto_target(node, item))
    _reload(node)
    _status(node, _check(node, _pval(node, "target_prim")))

def on_created(node):
    threading.Thread(target=lambda: _items(node), daemon=True).start()

def on_loaded(node):
    resolve_path(node)
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
_CB = "hou.phm().resolve_path(kwargs['node'])"

def _menu(name, label, default, fn, help_txt):
    t = hou.StringParmTemplate(name, label, 1, default_value=(default,), help=help_txt)
    t.setItemGeneratorScript("hou.phm()." + fn + "(kwargs['node'])")
    t.setItemGeneratorScriptLanguage(_PY)
    t.setScriptCallback(_CB)
    t.setScriptCallbackLanguage(_PY)
    return t

_ptg = hou.ParmTemplateGroup()
_ptg.append(_menu("project", "Project", "", "menu_project", "FLUX project"))
_ptg.append(_menu("seq", "Sequence", "", "menu_seq", "SEQ token"))
_ptg.append(_menu("shot", "Shot", "", "menu_shot", "SHOT token"))
_ptg.append(_menu("task", "Task", "ANIM", "menu_task", "Shot department (TYPE)"))
_ptg.append(_menu("character", "Perso", "", "menu_character", "Animated character (SEQ_SHOT_ANIM_<NAME>)"))
_ptg.append(_menu("version", "Version", "LAST", "menu_version", "LAST follows new publishes, vNNN is frozen"))
_ptg.append(hou.SeparatorParmTemplate("sep_target"))
_auto = hou.ToggleParmTemplate("target_auto", "Auto", default_value=True,
                               help="Target = the character's prim found in the input")
_auto.setJoinWithNext(True)
_auto.setScriptCallback(_CB)
_auto.setScriptCallbackLanguage(_PY)
_ptg.append(_auto)
_tgt = _menu("target_prim", "Target Prim", "/assets/asset", "menu_target", "Prim that receives the animation")
_tgt.setConditional(hou.parmCondType.DisableWhen, "{{ target_auto == 1 }}")
_ptg.append(_tgt)
_ptg.append(hou.SeparatorParmTemplate("sep_resolved"))
_ptg.append(hou.StringParmTemplate("resolved_path", "Resolved Path", 1, default_value=("",)))
_ptg.append(hou.ButtonParmTemplate("btn_resolve", "Resolve / Reload", script_callback=_CB,
                                   script_callback_language=_PY,
                                   help="Re-read the published animation from disk"))
_ptg.append(hou.ButtonParmTemplate("btn_frame_range", "Appliquer la plage",
                                   script_callback="hou.phm().apply_frame_range(kwargs['node'])",
                                   script_callback_language=_PY,
                                   help="Timeline and fps of the scene = those of the animation"))
_ptg.append(hou.StringParmTemplate("status_msg", "Status", 1, default_value=("",)))

_stage = hou.node("/stage") or hou.node("/").createNode("lopnet", "stage")
_old = _stage.node("__flux_anim_build__")
if _old is not None:
    _old.destroy()
_sub = _stage.createNode("subnet", "__flux_anim_build__")
for _c in _sub.children():
    if _c.type().name() != "output":
        _c.destroy()
_out = next((c for c in _sub.children() if c.type().name() == "output"), None) \\
    or _sub.createNode("output", "output0")
_ref = _sub.createNode("reference", "reference")
_ref.setInput(0, _sub.indirectInputs()[0])
_ref.parm("filepath1").setExpression('chs("../resolved_path")', hou.exprLanguage.Hscript)
_ref.parm("primpath1").setExpression('chs("../target_prim")', hou.exprLanguage.Hscript)
_out.setInput(0, _ref)
_sub.layoutChildren()

_asset = _sub.createDigitalAsset(name=_NAME, hda_file_name=_HDA_PATH, description={LABEL!r},
                                 min_num_inputs=1, max_num_inputs=1, version="1.0")
{_finalize}
{_restore}
result = {{"ok": True, "path": _HDA_PATH, "node_type": "Lop/" + _NAME}}
'''


def build_hda(hda_path: str) -> dict:
    """Build the FLUX Anim LOP HDA in the running Houdini."""
    log.info("Building FLUX Anim HDA -> %s", hda_path)
    resp = houdini_client.run(_build_code(hda_path))
    if resp.get("ok"):
        log.info("FLUX Anim HDA built: %s", hda_path)
    else:
        log.error("FLUX Anim HDA build failed: %s", resp.get("error"))
    return resp
