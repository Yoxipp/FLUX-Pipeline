"""
FLUX - Houdini "FLUX Lighting" HDA for Solaris: the SEQUENCE light rig (2026-09-25).

Replaces the old template node (usd_input / usd_output rewritten in place, input
ignored, output empty). Same pattern as FLUX Shot:
  * menus: project, sequence, version of the published rig (LAST / vNNN);
  * a Layer Break at the input: the lights the lighter adds after this node are new
    layers; "Partir du rig publie" loads the published rig (LAST) after the break so its
    lights can be edited;
  * "Publier le light rig de sequence" writes those layers (USD ROP, layers above the
    break stripped) to a temp file, FLUX flattens them (the published rig + the edits)
    and publishes <SEQ>_LIGHT as vNNN + LAST in <SEQ>/usd/lighting. The sequence root
    <SEQ>.usda sublayers that LAST: every shot of the sequence gets the rig, under its
    own shot lighting (FLUX Shot).

The HDA holds a small bootstrap that fetches the real module from
GET /dcc/houdini/lighting/module, so a fix needs no HDA rebuild.
"""

from __future__ import annotations

from core.logger import get_logger
from dcc.houdini.client import houdini_client

log = get_logger(__name__)

# Node type name, kept stable: houdini_scene_template finds / drops the node by it.
NODE_TYPE_NAME: str = "flux_lighting"
NODE_NAME = NODE_TYPE_NAME
LABEL = "FLUX Lighting"

BOOTSTRAP: str = '''
import json, os, urllib.request

def _flux_port():
    try:
        return int(os.environ.get("FLUX_PORT") or
                   open(os.path.join(os.environ.get("APPDATA",""), "FLUX", "backend_port")).read())
    except Exception:
        return 8765

def _load():
    with urllib.request.urlopen(f"http://127.0.0.1:{_flux_port()}/dcc/houdini/lighting/module", timeout=3) as _r:
        exec(json.loads(_r.read())["code"], globals())

try:
    _load()
except Exception:
    def _dead_menu(*a, **kw): return ["", "FLUX offline"]
    for _n in ("menu_project", "menu_seq", "menu_version"):
        globals()[_n] = _dead_menu
    def _offline(node, name):
        try:
            _load()
            globals()[name](node)
        except Exception:
            node.parm("status_msg").set("FLUX offline : demarre FLUX puis clique Resolve")
    def resolve_path(node): _offline(node, "resolve_path")
    def publish_light(node): _offline(node, "publish_light")
    def on_created(node): pass
    def on_loaded(node): pass
'''

# Served by GET /dcc/houdini/lighting/module, exec()'d by the bootstrap (runs inside Houdini).
MODULE_FUNCTIONS: str = '''
import json, os, shutil, tempfile, threading, time, urllib.parse, urllib.request

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
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.loads(r.read())
    except Exception as exc:
        # "_offline": FLUX not reachable: never cached, never read as "nothing published".
        return {"ok": False, "error": str(exc), "_offline": True}

def _post(path, payload):
    req = urllib.request.Request(f"http://127.0.0.1:{_flux_port()}" + path,
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
    """fetch() -> (data, ok). Only good answers are cached: an error is retried."""
    now = time.monotonic()
    if key in _cache and now < _cache[key][0]:
        return _cache[key][1]
    data, ok = fetch()
    if ok:
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

def _fetch_sequences(project):
    r = _get("/dcc/houdini/lighting/sequences", project=project)
    return r.get("sequences", []), not r.get("_offline")

def _sequences(node):
    project = _pval(node, "project")
    if not project:
        return []
    return _cached("seqs:" + project, lambda: _fetch_sequences(project))

def _current(node):
    seq = _pval(node, "seq")
    return next((s for s in _sequences(node) if s["seq"] == seq), None)

def menu_project(node):
    def _fetch():
        r = _get("/dcc/houdini/importer/tokens")
        return r.get("projects", []), not r.get("_offline")
    projects = _cached("projects", _fetch)
    return _flat(projects) if projects else ["", "FLUX injoignable ou aucun projet"]

def menu_seq(node):
    return _flat([s["seq"] for s in _sequences(node)]) or ["", "aucune sequence"]

def menu_version(node):
    item = _current(node)
    return _flat(["LAST"] + list(reversed((item or {}).get("versions", []))))

def _reload(node):
    n = node.node("published_rig")
    btn = n.parm("reload") if n is not None else None
    if btn is not None:
        try:
            btn.pressButton()
        except Exception:
            pass

def resolve_path(node, opening=False):
    """Find the published rig of the sequence (LAST or a frozen vNNN) and load it when
    "Partir du rig publie" is on."""
    project = _pval(node, "project")
    if not project:
        _status(node, "Choisis un projet"); return
    seqs, ok = _fetch_sequences(project)
    if not ok:
        _status(node, "FLUX injoignable : rig actuel garde. Demarre FLUX puis clique Resolve"); return
    _cache["seqs:" + project] = (time.monotonic() + _TTL, seqs)
    item = _current(node)
    if item is None:
        _set(node, "resolved_path", "")
        _status(node, "Choisis une sequence"); return
    version = _pval(node, "version") or "LAST"
    if version != "LAST" and version not in (item.get("files") or {}):
        version = "LAST"
        _set(node, "version", "LAST")
    path = item.get("last") if version == "LAST" else item["files"][version]
    _set(node, "resolved_path", (path or "").replace(chr(92), "/"))
    _reload(node)
    if not path:
        _status(node, "%s : aucun rig publie. Ajoute les lumieres apres ce node puis Publier" % item["seq"])
        return
    if not item.get("root"):
        _status(node, "%s %s charge. ATTENTION : %s.usda absent, les shots ne le voient pas"
                % (item["seq"], version, item["seq"])); return
    _status(node, "%s %s%s" % (item["seq"], version, "" if opening else "  (rig publie charge)"))

def _branch_end(node):
    """Last node of this branch: follows single outputs, stops before a node that mixes
    several inputs or a ROP."""
    cur = node
    for _ in range(500):
        outs = [o for o in cur.outputs() if "rop" not in o.type().name().lower()]
        if len(outs) != 1 or len(outs[0].inputs()) > 1:
            return cur
        cur = outs[0]
    return cur

def _light_source(node):
    import hou
    path = _pval(node, "light_node")
    if path:
        n = hou.node(path)
        if n is not None:
            return n
    return _branch_end(node)

def publish_light(node):
    """Write the layers after this node (the sequence lights) and publish them."""
    project, seq = _pval(node, "project"), _pval(node, "seq")
    if not (project and seq):
        _status(node, "Choisis projet et sequence d'abord"); return
    src = _light_source(node)
    if src is None or (src.path() == node.path() and not node.evalParm("from_rig")):
        _status(node, "Ajoute les lumieres apres ce node (ou remplis Light Node)"); return
    tmp_dir = tempfile.mkdtemp(prefix="flux_seq_light_")
    out = os.path.join(tmp_dir, "light.usda").replace(chr(92), "/")
    rop = node.parent().createNode("usd_rop", "__flux_seq_light_export__")
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
        shutil.rmtree(tmp_dir, ignore_errors=True)
        _status(node, "Export des lumieres echoue"); return
    r = _post("/dcc/houdini/sequence-light/publish", {"project": project, "seq": seq, "file": out})
    shutil.rmtree(tmp_dir, ignore_errors=True)
    if not r.get("ok"):
        _status(node, "Publish echoue : %s" % r.get("error", "?")); return
    _cache.pop("seqs:" + project, None)
    _set(node, "version", "LAST")
    resolve_path(node, opening=True)
    warns = r.get("warnings") or []
    _status(node, "Light rig publie : %s %s%s" % (r.get("base", ""), r.get("version", ""),
                                                  "  |  " + " ; ".join(warns) if warns else ""))

def on_created(node):
    threading.Thread(target=lambda: _sequences(node), daemon=True).start()

def on_loaded(node):
    resolve_path(node, opening=True)
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

def _menu(name, label, default, fn, help_txt, cb=_CB):
    t = hou.StringParmTemplate(name, label, 1, default_value=(default,), help=help_txt)
    t.setItemGeneratorScript("hou.phm()." + fn + "(kwargs['node'])")
    t.setItemGeneratorScriptLanguage(_PY)
    if cb:
        t.setScriptCallback(cb)
        t.setScriptCallbackLanguage(_PY)
    return t

_ptg = hou.ParmTemplateGroup()
_ptg.append(_menu("project", "Projet", "", "menu_project", "Projet FLUX"))
_ptg.append(_menu("seq", "Sequence", "", "menu_seq", "Sequence dont on eclaire le rig general"))
_ptg.append(_menu("version", "Version du rig", "LAST", "menu_version",
                  "LAST suit les nouveaux publishs, vNNN est fige"))
_ptg.append(hou.ToggleParmTemplate("from_rig", "Partir du rig publie", default_value=True,
                                   script_callback=_CB, script_callback_language=_PY,
                                   help="Charge le rig publie apres ce node : ses lumieres se modifient, "
                                        "le publish les garde. Decoche : un rig neuf, fait de zero."))
_ptg.append(hou.SeparatorParmTemplate("sep_light"))
_ptg.append(hou.StringParmTemplate("light_node", "Light Node", 1, default_value=("",),
                                   string_type=hou.stringParmType.NodeReference,
                                   help="LOP qui porte les lumieres (vide = fin de la branche de ce node)"))
_ptg.append(hou.ButtonParmTemplate("btn_publish_light", "Publier le light rig de sequence",
                                   script_callback="hou.phm().publish_light(kwargs['node'])",
                                   script_callback_language=_PY,
                                   help="Publie les lumieres apres ce node en SEQ_LIGHT (vNNN + LAST) ; "
                                        "tous les shots de la sequence le recoivent"))
_ptg.append(hou.SeparatorParmTemplate("sep_resolved"))
_ptg.append(hou.StringParmTemplate("resolved_path", "Rig publie", 1, default_value=("",)))
_ptg.append(hou.ButtonParmTemplate("btn_resolve", "Resolve / Reload", script_callback=_CB,
                                   script_callback_language=_PY,
                                   help="Relit le rig publie depuis le disque"))
_ptg.append(hou.StringParmTemplate("status_msg", "Statut", 1, default_value=("",)))

_stage = hou.node("/stage") or hou.node("/").createNode("lopnet", "stage")
_old = _stage.node("__flux_lighting_build__")
if _old is not None:
    _old.destroy()
_sub = _stage.createNode("subnet", "__flux_lighting_build__")
for _c in _sub.children():
    if _c.type().name() != "output":
        _c.destroy()
_out = next((c for c in _sub.children() if c.type().name() == "output"), None) \\
    or _sub.createNode("output", "output0")
# Everything after the break is the rig: the published one (optional) + the lighter's edits.
_lb = _sub.createNode("layerbreak", "layerbreak")
_lb.setInput(0, _sub.indirectInputs()[0])
_rig = _sub.createNode("sublayer", "published_rig")
_rig.setInput(0, _lb)
_rig.parm("filepath1").setExpression('chs("../resolved_path")', hou.exprLanguage.Hscript)
_sw = _sub.createNode("switch", "from_rig")
_sw.setInput(0, _lb)
_sw.setInput(1, _rig)
_sw.parm("input").setExpression('if(strlen(chs("../resolved_path")) > 0, ch("../from_rig"), 0)',
                                hou.exprLanguage.Hscript)
_out.setInput(0, _sw)
_sub.layoutChildren()

_asset = _sub.createDigitalAsset(name=_NAME, hda_file_name=_HDA_PATH, description={LABEL!r},
                                 min_num_inputs=0, max_num_inputs=1, version="2.0")
{_finalize}
{_restore}
result = {{"ok": True, "path": _HDA_PATH, "node_type": "Lop/" + _NAME}}
'''


def build_hda(hda_path: str) -> dict:
    """Build the FLUX Lighting LOP HDA in the running Houdini."""
    log.info("Building FLUX Lighting HDA -> %s", hda_path)
    resp = houdini_client.run(_build_code(hda_path))
    if resp.get("ok"):
        log.info("FLUX Lighting HDA built: %s", hda_path)
    else:
        log.error("FLUX Lighting HDA build failed: %s", resp.get("error"))
    return resp
