"""
FLUX - Houdini "FLUX Unreal Live" HDA for Solaris (ADR 0052, 2026-10-10).

A pass-through LOP put at the end of a /stage tree: what reaches it is shown live in
Unreal (both softs open, a change in Houdini shows in Unreal without saving the .hip).

  * an inner USD ROP writes ONLY the layers Houdini authored to a local live file
    (``live_file``, %LOCALAPPDATA%/FluxPipeline/unreal/live/), files already on disk stay
    references with relative paths and are never rewritten (savefilesfromdisk = 0):
    published versions are never touched. Probe 2026-10-10 (hython 22.0.368): 1 file,
    0.9 s first write then ~0.01 s;
  * FLUX is told (POST /dcc/unreal/live) and the Unreal bridge opens the live file the
    first time, then re-reads only what changed;
  * mode Auto: an inner Python LOP calls on_cook() every time the input stage cooks, the
    push runs ``delay`` seconds after the last cook (event loop, never inside the cook);
    mode Manuel: only the Push button. Push works in both modes (the maintainer's choice).

Same bootstrap as FLUX Render: the HDA fetches its module from
GET /dcc/houdini/flux_unreal_live/module, so a fix needs no HDA rebuild.
"""

from __future__ import annotations

from core.logger import get_logger
from dcc.houdini.client import houdini_client

log = get_logger(__name__)

NODE_NAME = "flux_unreal_live"
LABEL = "FLUX Unreal Live"

BOOTSTRAP: str = '''
import json, os, urllib.request

def _flux_port():
    try:
        return int(os.environ.get("FLUX_PORT") or
                   open(os.path.join(os.environ.get("APPDATA",""), "FLUX", "backend_port")).read())
    except Exception:
        return 8765

def _load():
    with urllib.request.urlopen(f"http://127.0.0.1:{_flux_port()}/dcc/houdini/flux_unreal_live/module", timeout=3) as _r:
        exec(json.loads(_r.read())["code"], globals())

try:
    _load()
except Exception:
    def _offline(node, name):
        try:
            _load()
            globals()[name](node)
        except Exception:
            node.parm("status_msg").set("FLUX offline : demarre FLUX puis reessaie")
    def push(node): _offline(node, "push")
    def on_cook(node): pass
    def on_created(node): pass
    def on_loaded(node): pass
'''

# Inner Python LOP: tells the HDA its input cooked. Never edits the stage (pass-through).
WATCH_CODE: str = '''
node = hou.pwd()
try:
    node.parent().type().hdaModule().on_cook(node.parent())
except Exception:
    pass
'''

# Served by GET /dcc/houdini/flux_unreal_live/module, exec()'d by the bootstrap (inside Houdini).
MODULE_FUNCTIONS: str = '''
import json, os, threading, time, urllib.error, urllib.request
import hou

# Shared across module re-executions (the bootstrap may load the module again).
_STATE = hou.session.__dict__.setdefault("_flux_unreal_live", {})
for _k, _v in (("pending", {}), ("results", {}), ("pushing", set()), ("inflight", set()), ("cb", None)):
    _STATE.setdefault(_k, _v)

def _port():
    try:
        return int(os.environ.get("FLUX_PORT") or
                   open(os.path.join(os.environ.get("APPDATA", ""), "FLUX", "backend_port")).read())
    except Exception:
        return 8765

def _status(node, msg):
    p = node.parm("status_msg")
    if p is not None:
        p.set(msg)

def default_live_file(node):
    base = (os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")).replace("\\\\", "/")
    hip = os.path.splitext(hou.hipFile.basename())[0] or "untitled"
    return "%s/FluxPipeline/unreal/live/%s_%s.usd" % (base, hip, node.name())

def _live_file(node):
    path = node.parm("live_file").evalAsString()
    if not path:
        path = default_live_file(node)
        node.parm("live_file").set(path)
    return path

def on_created(node):
    if not node.parm("live_file").evalAsString():
        node.parm("live_file").set(default_live_file(node))
    _status(node, "Pret : Unreal ouvert depuis FLUX, flag display sur ce node")

def on_loaded(node):
    pass

def on_cook(node):
    """The input stage cooked: in Auto mode, push after the delay (never inside the cook)."""
    try:
        if node.parm("mode").evalAsString() != "auto" or node.path() in _STATE["pushing"]:
            return
        if not hou.isUIAvailable():
            return
        _STATE["pending"][node.path()] = time.time() + max(0.2, float(node.evalParm("delay")))
        _ensure_callback()
    except Exception:
        pass

def _ensure_callback():
    if _STATE["cb"] is None and hou.isUIAvailable():
        _STATE["cb"] = _tick
        hou.ui.addEventLoopCallback(_tick)

def _tick():
    now = time.time()
    for path, due in list(_STATE["pending"].items()):
        if due <= now:
            _STATE["pending"].pop(path, None)
            node = hou.node(path)
            if node is not None:
                push(node)
    for path, msg in list(_STATE["results"].items()):
        _STATE["results"].pop(path, None)
        node = hou.node(path)
        if node is not None:
            _status(node, msg)
    if not (_STATE["pending"] or _STATE["results"] or _STATE["inflight"]):
        cb, _STATE["cb"] = _STATE["cb"], None
        try:
            hou.ui.removeEventLoopCallback(cb)
        except Exception:
            pass

def push(node):
    """Write the live layer and tell Unreal (through FLUX). Button Push + Auto mode."""
    path = node.path()
    if path in _STATE["pushing"]:
        return
    rop = node.node("live_rop")
    out = _live_file(node)
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
    except OSError as exc:
        _status(node, "Dossier live impossible : %s" % exc)
        return
    _STATE["pushing"].add(path)
    start = time.time()
    try:
        rop.render()
    except Exception as exc:
        _status(node, "Ecriture du layer live impossible : %s" % exc)
        return
    finally:
        _STATE["pushing"].discard(path)
    written = time.time() - start
    _status(node, "Layer ecrit en %.2f s, envoi a Unreal..." % written)
    _STATE["inflight"].add(path)
    _ensure_callback()
    threading.Thread(target=_send, args=(path, out, written), daemon=True).start()

def _send(path, out, written):
    """Background thread: no hou call here, the result is shown by _tick."""
    try:
        req = urllib.request.Request("http://127.0.0.1:%d/dcc/unreal/live" % _port(),
                                     data=json.dumps({"path": out}).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=600) as r:
            res = json.loads(r.read())
        if res.get("paused"):
            msg = "Unreal : live en pause (menu FLUX d'Unreal)"
        else:
            msg = "Unreal a jour a %s (ecrit %.2f s, Unreal %.2f s)" % (
                time.strftime("%H:%M:%S"), written, float(res.get("seconds") or 0))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("detail")
        except Exception:
            detail = str(exc)
        msg = "Unreal : %s" % detail
    except Exception as exc:
        msg = "FLUX injoignable : %s" % exc
    _STATE["results"][path] = msg
    _STATE["inflight"].discard(path)
'''


def _build_code(hda_path: str) -> str:
    from dcc.houdini.hda.hda_common import FINALIZE as _finalize, ICON_PATH as icon_path
    from dcc.houdini.hda.preserve_instances import RESTORE, snapshot

    _snapshot = snapshot('hou.lopNodeTypeCategory()', NODE_NAME).replace("{{", "{").replace("}}", "}")
    return f'''
import hou
{_snapshot}

_HDA_PATH = {hda_path!r}
_ICON_PATH = {icon_path!r}
_NAME = {NODE_NAME!r}
_PY = hou.scriptLanguage.Python
_PM_CODE = {BOOTSTRAP!r}

_ptg = hou.ParmTemplateGroup()
_ptg.append(hou.StringParmTemplate("mode", "Mode", 1, default_value=("auto",),
                                   menu_items=("auto", "manual"),
                                   menu_labels=("Auto (apres chaque modif)", "Manuel (bouton Push)"),
                                   help="Auto: Unreal follows every change. Manuel: only the Push button"))
_delay = hou.FloatParmTemplate("delay", "Delai (s)", 1, default_value=(1.0,), min=0.2, max=10.0,
                               help="Auto mode: wait this long after the last change before sending")
_delay.setConditional(hou.parmCondType.HideWhen, '{{ mode != "auto" }}')
_ptg.append(_delay)
_ptg.append(hou.ButtonParmTemplate("push", "Push vers Unreal",
                                   script_callback="hou.phm().push(kwargs['node'])",
                                   script_callback_language=_PY,
                                   help="Send the stage to Unreal now (both modes)"))
_ptg.append(hou.ToggleParmTemplate("anim_range", "Ecrire la plage d'images", default_value=False,
                                   help="Off: current frame only (fast). On: $FSTART-$FEND (animation authored in Houdini)"))
_ptg.append(hou.StringParmTemplate("live_file", "Fichier live", 1, default_value=("",),
                                   string_type=hou.stringParmType.FileReference,
                                   help="Local file Unreal reads (never a published version)"))
_ptg.append(hou.StringParmTemplate("status_msg", "Statut", 1, default_value=("",)))

_stage = hou.node("/stage") or hou.node("/").createNode("lopnet", "stage")
_old = _stage.node("__flux_unreal_live_build__")
if _old is not None:
    _old.destroy()
_sub = _stage.createNode("subnet", "__flux_unreal_live_build__")
for _c in _sub.children():
    if _c.type().name() != "output":
        _c.destroy()
_out = next((c for c in _sub.children() if c.type().name() == "output"), None) \\
    or _sub.createNode("output", "output0")
_watch = _sub.createNode("pythonscript", "watch")
_watch.parm("python").set({WATCH_CODE!r})
_watch.setInput(0, _sub.indirectInputs()[0])
_out.setInput(0, _watch)
_rop = _sub.createNode("usd_rop", "live_rop")
_rop.setInput(0, _watch)
_rop.parm("lopoutput").set('`chs("../live_file")`')
_rop.parm("savefilesfromdisk").set(0)          # never rewrite a file layer (publishes)
_rop.parm("errorsavingimplicitpaths").set(0)
_rop.parm("trange").setExpression('ch("../anim_range")', hou.exprLanguage.Hscript)
_rop.parm("f1").setExpression("$FSTART", hou.exprLanguage.Hscript)
_rop.parm("f2").setExpression("$FEND", hou.exprLanguage.Hscript)
_sub.layoutChildren()

_asset = _sub.createDigitalAsset(name=_NAME, hda_file_name=_HDA_PATH, description={LABEL!r},
                                 min_num_inputs=1, max_num_inputs=1, version="1.0")
{_finalize}
{RESTORE}
result = {{"ok": True, "path": _HDA_PATH, "node_type": "Lop/" + _NAME}}
'''


def build_hda(hda_path: str) -> dict:
    """Build the FLUX Unreal Live LOP HDA in the running Houdini."""
    log.info("Building FLUX Unreal Live HDA -> %s", hda_path)
    resp = houdini_client.run(_build_code(hda_path))
    if resp.get("ok"):
        log.info("FLUX Unreal Live HDA built: %s", hda_path)
    else:
        log.error("FLUX Unreal Live HDA build failed: %s", resp.get("error"))
    return resp
