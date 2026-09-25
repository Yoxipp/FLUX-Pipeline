"""
FLUX - Houdini "FLUX Export" HDA: publish what is wired into it to FLUX (vNNN + LAST).

One node type name, three contexts (2026-09-25: "il doit pouvoir etre pose autant
dans le stage que obj ou autre") :
  * SOP (in a geo network)  : the input geometry, as bgeo.sc / abc / usd / obj / fbx;
  * LOP (in /stage)         : the input stage, as usd / usda / usdc;
  * OBJ (in /obj)           : the geo object picked in "Objet a exporter".
The node itself is a pass-through: it can sit anywhere in a chain.

"Publier" asks FLUX to publish (POST /dcc/houdini/exporter/export) from a background
thread, so Houdini's main thread stays free for the cook FLUX then drives through the
Houdini bridge (same path as the Publisher: dcc/houdini/houdini_export.publish_houdini_rop).
Before 2026-09-25 the backend served none of the /dcc/houdini/exporter/* routes this HDA
calls, so every node showed "FLUX offline" even with the bridge green.

The HDA holds a small bootstrap that fetches the real module from
GET /dcc/houdini/exporter/module, so a fix to MODULE_FUNCTIONS needs no HDA rebuild.
"""

from __future__ import annotations

from core.logger import get_logger
from dcc.houdini.client import houdini_client

log = get_logger(__name__)

NODE_NAME = "flux_exporter"
LABEL = "FLUX Export"

# Formats offered per context (the first one is the default).
FORMATS = {
    "Sop":    ("bgeo.sc", "abc", "usd", "obj", "fbx"),
    "Object": ("bgeo.sc", "abc", "usd", "obj", "fbx"),
    "Lop":    ("usd", "usda", "usdc"),
}

BOOTSTRAP: str = '''
import json, os, urllib.request

def _flux_port():
    try:
        return int(os.environ.get("FLUX_PORT") or
                   open(os.path.join(os.environ.get("APPDATA",""), "FLUX", "backend_port")).read())
    except Exception:
        return 8765

def _load():
    with urllib.request.urlopen(f"http://127.0.0.1:{_flux_port()}/dcc/houdini/exporter/module", timeout=3) as _r:
        exec(json.loads(_r.read())["code"], globals())

try:
    _load()
except Exception:
    def _dead_menu(*a, **kw): return ["", "FLUX injoignable"]
    for _n in ("menu_project", "menu_class", "menu_type", "menu_name", "menu_instance", "menu_format"):
        globals()[_n] = _dead_menu
    def export_geo(node):
        try:
            _load()
            globals()["export_geo"](node)
        except Exception:
            p = node.parm("status_msg")
            if p is not None:
                p.set("FLUX injoignable : demarre FLUX puis reessaie")
    def on_created(node): pass
    def on_loaded(node): pass
    def on_change(node): pass
'''

# Served by GET /dcc/houdini/exporter/module, exec()'d by the bootstrap (runs inside Houdini).
MODULE_FUNCTIONS: str = '''
import json, os, threading, time, urllib.error, urllib.parse, urllib.request

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
        return {"ok": False, "error": str(exc), "_offline": True}

def _post(path, payload, timeout=900):
    req = urllib.request.Request(f"http://127.0.0.1:{_flux_port()}" + path,
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
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

def _status(node, msg):
    p = node.parm("status_msg")
    if p is not None:
        p.set(msg)

def _flat(items):
    out = []
    for i in items:
        out += [i, i]
    return out

def _context(node):
    return node.type().category().name()

def _projects():
    def fetch():
        r = _get("/dcc/houdini/exporter/tokens")
        return r.get("projects", []), not r.get("_offline")
    return _cached("projects", fetch)

def _tokens(node):
    project = _pval(node, "project")
    if not project:
        return {}
    def fetch():
        r = _get("/dcc/houdini/exporter/tokens", project=project)
        return r.get("tokens", {}), not r.get("_offline")
    return _cached("tokens:" + project, fetch)

def menu_project(node):
    p = _projects()
    return _flat(p) if p else ["", "FLUX injoignable ou aucun projet"]

def menu_class(node):
    keys = sorted(_tokens(node).get("CLASS", {}).keys())
    return _flat(keys) if keys else ["", "choisis un projet"]

_DEFAULT_TYPES = ["GEO", "SCULPT", "BLOCK", "TOPO", "TEX", "LDEV", "FUR", "HAIR", "GROOM",
                  "SK", "WGHT", "RIG", "CLOTH", "MUSCLE", "FX", "GBL"]

def menu_type(node):
    keys = list(_tokens(node).get("TYPE", {}).keys())
    return _flat(sorted(set(keys + _DEFAULT_TYPES)))

def menu_name(node):
    toks = _tokens(node)
    names = toks.get("NAME", {})
    cls = _pval(node, "flux_class").upper()
    if cls and cls in toks.get("CLASS", {}):
        prefix = str(toks["CLASS"][cls]).rstrip("/")
        filtered = sorted(k for k, v in names.items() if str(v).startswith(prefix))
        if filtered:
            return _flat(filtered)
    keys = sorted(names.keys())
    return _flat(keys) if keys else ["", "choisis un projet"]

def menu_instance(node):
    inst = sorted(_tokens(node).get("INSTANCE", {}).keys())
    if "null" not in inst:
        inst = ["null"] + inst
    return _flat(inst)

_FORMATS = __FORMATS__

def menu_format(node):
    return _flat(_FORMATS.get(_context(node), _FORMATS["Sop"]))

def _filename(node):
    cls, typ, name = _pval(node, "flux_class"), _pval(node, "flux_type"), _pval(node, "flux_name")
    if not (cls and typ and name):
        return ""
    return "%s_%s_%s_%s" % (cls.upper(), typ.upper(), name.upper(), (_pval(node, "flux_instance") or "null"))

def on_change(node):
    base = _filename(node)
    fmt = _pval(node, "flux_format")
    p = node.parm("preview")
    if p is not None:
        p.set((base + "_vNNN." + fmt) if base else "")

def _source(node):
    """What FLUX exports: this node (SOP / LOP, a pass-through) or the picked object."""
    if _context(node) != "Object":
        return node.path()
    target = node.parm("source_obj").evalAsNode() if node.parm("source_obj") else None
    return target.path() if target is not None else ""

_busy = set()

def export_geo(node):
    project = _pval(node, "project")
    base = _filename(node)
    fmt = _pval(node, "flux_format")
    if not project:
        _status(node, "Choisis un projet"); return
    if not base:
        _status(node, "Choisis Classe, Type et Nom"); return
    src = _source(node)
    if not src:
        _status(node, "Choisis l'objet a exporter"); return
    if node.path() in _busy:
        _status(node, "Publication deja en cours"); return
    payload = {
        "project": project, "filename": base, "format": fmt, "source_path": src,
        "description": _pval(node, "description"),
    }
    try:
        # Several Houdini can run: FLUX must cook in this one.
        import sys
        payload["houdini_port"] = sys.modules["flux_houdini_server"]._httpd.server_address[1]
    except Exception:
        pass
    if node.parm("anim") is not None and node.evalParm("anim"):
        payload["frame_range"] = [int(node.evalParm("frange1")), int(node.evalParm("frange2")), 1]
    _busy.add(node.path())
    _status(node, "Publication en cours...")
    path = node.path()

    def _work():
        r = _post("/dcc/houdini/exporter/export", payload)
        if r.get("ok"):
            msg = "Publie %s -> %s" % (r.get("version_str") or "", r.get("path") or "")
        else:
            msg = "Publication echouee : %s" % (r.get("error") or r.get("detail") or "?")
        def _done():
            _busy.discard(path)
            n = hou.node(path)
            if n is not None:
                _status(n, msg)
        try:
            import hdefereval
            hdefereval.executeDeferred(_done)
        except Exception:
            _done()
    # The cook runs on Houdini's main thread, driven by FLUX through the bridge: this
    # callback must return first, or both sides wait on each other.
    threading.Thread(target=_work, daemon=True).start()

def _prefetch(node):
    project = _pval(node, "project")
    def _work():
        _projects()
        if project:
            _tokens(node)
    threading.Thread(target=_work, daemon=True).start()

def on_created(node):
    fmts = _FORMATS.get(_context(node), _FORMATS["Sop"])
    if _pval(node, "flux_format") not in fmts:
        node.parm("flux_format").set(fmts[0])
    _prefetch(node)

def on_loaded(node):
    _prefetch(node)
'''.replace("__FORMATS__", repr(FORMATS))


# Where the build container lives, per context.
_CONTAINERS = {
    "Sop": ('hou.sopNodeTypeCategory()',
            '_obj = hou.node("/obj")\n'
            '_old = _obj.node("__flux_exporter_build__")\n'
            'if _old is not None:\n'
            '    _old.destroy()\n'
            '_box = _obj.createNode("geo", "__flux_exporter_build__")\n'
            '_box.deleteItems(_box.children())\n'
            '_sub = _box.createNode("subnet", "flux_exporter")\n'
            '_passthrough = _sub.createNode("null", "OUT")\n'
            '_passthrough.setInput(0, _sub.indirectInputs()[0])\n'
            '_passthrough.setDisplayFlag(True)\n'
            '_passthrough.setRenderFlag(True)\n'
            '_n_in = 1\n'),
    "Lop": ('hou.lopNodeTypeCategory()',
            '_stage = hou.node("/stage") or hou.node("/").createNode("lopnet", "stage")\n'
            '_old = _stage.node("__flux_exporter_build__")\n'
            'if _old is not None:\n'
            '    _old.destroy()\n'
            '_sub = _stage.createNode("subnet", "__flux_exporter_build__")\n'
            '_box = _sub\n'
            'for _c in _sub.children():\n'
            '    if _c.type().name() != "output":\n'
            '        _c.destroy()\n'
            '_o = next((c for c in _sub.children() if c.type().name() == "output"), None) \\\n'
            '    or _sub.createNode("output", "output0")\n'
            '_o.setInput(0, _sub.indirectInputs()[0])\n'
            '_n_in = 1\n'),
    "Object": ('hou.objNodeTypeCategory()',
               '_obj = hou.node("/obj")\n'
               '_old = _obj.node("__flux_exporter_build__")\n'
               'if _old is not None:\n'
               '    _old.destroy()\n'
               '_sub = _obj.createNode("subnet", "__flux_exporter_build__")\n'
               '_box = _sub\n'
               '_sub.deleteItems(_sub.children())\n'
               '_n_in = 0\n'),
}


def _build_code(hda_path: str, context: str) -> str:
    from dcc.houdini.hda.hda_common import FINALIZE as _finalize, ICON_PATH as icon_path
    from dcc.houdini.hda.preserve_instances import RESTORE, snapshot

    category, container = _CONTAINERS[context]
    _snapshot = snapshot(category, NODE_NAME).replace("{{", "{").replace("}}", "}")
    formats = FORMATS[context]
    # /obj: nothing is wired in, the node publishes the geo object picked here.
    source_parm = (
        '_src = hou.StringParmTemplate("source_obj", "Objet a exporter", 1, default_value=("",),\n'
        '                              string_type=hou.stringParmType.NodeReference,\n'
        '                              help="Objet geo publie (son node de rendu)")\n'
        '_src.setTags({"opfilter": "!!OBJ!!", "oprelative": "."})\n'
        '_ptg.append(_src)\n'
    ) if context == "Object" else ""
    cleanup = "_box.destroy()\n" if context == "Sop" else ""

    return f'''
import hou
{_snapshot}

_HDA_PATH = {hda_path!r}
_ICON_PATH = {icon_path!r}
_NAME = {NODE_NAME!r}
_PY = hou.scriptLanguage.Python
_PM_CODE = {BOOTSTRAP!r}
_CB = "hou.phm().on_change(kwargs['node'])"

def _menu(name, label, default, fn, help_txt):
    t = hou.StringParmTemplate(name, label, 1, default_value=(default,), help=help_txt)
    t.setItemGeneratorScript("hou.phm()." + fn + "(kwargs['node'])")
    t.setItemGeneratorScriptLanguage(_PY)
    t.setScriptCallback(_CB)
    t.setScriptCallbackLanguage(_PY)
    return t

_ptg = hou.ParmTemplateGroup()
_ptg.append(_menu("project", "Projet", "", "menu_project", "Projet FLUX"))
_ptg.append(_menu("flux_class", "Classe", "CHAR", "menu_class", "Token CLASS (CHAR, PROPS, ENV...)"))
_ptg.append(_menu("flux_type", "Type", "GEO", "menu_type", "Token TYPE : le departement publie"))
_ptg.append(_menu("flux_name", "Nom", "", "menu_name", "Token NAME de l'asset"))
_ptg.append(_menu("flux_instance", "Instance", "null", "menu_instance", "Token INSTANCE"))
_ptg.append(_menu("flux_format", "Format", {formats[0]!r}, "menu_format", "Format du fichier publie"))
{source_parm}_ptg.append(hou.SeparatorParmTemplate("sep_anim"))
_anim = hou.ToggleParmTemplate("anim", "Animation", default_value=False,
                               help="Un seul fichier anime sur la plage (abc, usd)")
_ptg.append(_anim)
_fr = hou.IntParmTemplate("frange", "Plage", 2, default_value=(1001, 1100),
                          default_expression=("$FSTART", "$FEND"),
                          default_expression_language=(hou.scriptLanguage.Hscript,
                                                       hou.scriptLanguage.Hscript))
_fr.setConditional(hou.parmCondType.DisableWhen, "{{ anim == 0 }}")
_ptg.append(_fr)
_ptg.append(hou.StringParmTemplate("description", "Commentaire", 1, default_value=("",)))
_ptg.append(hou.SeparatorParmTemplate("sep_action"))
_prev = hou.StringParmTemplate("preview", "Fichier", 1, default_value=("",),
                               help="Nom du fichier publie (la version est choisie par FLUX)")
_ptg.append(_prev)
_ptg.append(hou.ButtonParmTemplate("btn_export", "Publier dans FLUX",
                                   script_callback="hou.phm().export_geo(kwargs['node'])",
                                   script_callback_language=_PY,
                                   help="Publie une nouvelle version (vNNN) et met a jour LAST"))
_ptg.append(hou.StringParmTemplate("status_msg", "Statut", 1, default_value=("",)))

{container}
_sub.layoutChildren()

_asset = _sub.createDigitalAsset(name=_NAME, hda_file_name=_HDA_PATH, description={LABEL!r},
                                 min_num_inputs=_n_in, max_num_inputs=_n_in, version="1.0")
{_finalize}
{cleanup}{RESTORE}
result = {{"ok": True, "path": _HDA_PATH, "node_type": {context!r} + "/" + _NAME}}
'''


def _build(hda_path: str, context: str) -> dict:
    log.info("Building FLUX Export HDA (%s) -> %s", context, hda_path)
    resp = houdini_client.run(_build_code(hda_path, context))
    if resp.get("ok"):
        log.info("FLUX Export HDA built (%s): %s", context, hda_path)
    else:
        log.error("FLUX Export HDA build failed (%s): %s", context, resp.get("error"))
    return resp


def build_hda(hda_path: str) -> dict:
    """SOP FLUX Export (in a geo network)."""
    return _build(hda_path, "Sop")


def build_hda_lop(hda_path: str) -> dict:
    """LOP FLUX Export (in /stage)."""
    return _build(hda_path, "Lop")


def build_hda_obj(hda_path: str) -> dict:
    """Object-level FLUX Export (in /obj), exports the picked geo object."""
    return _build(hda_path, "Object")
