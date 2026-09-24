"""
FLUX — Houdini Exporter HDA.

Two responsibilities:
  1. PYTHON_MODULE  — Python code embedded verbatim inside the HDA's PythonModule
                      section. Runs inside Houdini. Only uses stdlib + hou.
                      All logic is delegated to the FLUX FastAPI backend via HTTP.

  2. build_hda()    — Creates the HDA programmatically in a running Houdini instance
                      via houdini_client.run(). Saves it to an .hda file.

Port discovery (no hardcoded paths):
    The HDA Python code reads FLUX_PORT env var first, then falls back to reading
    %APPDATA%/FLUX/backend_port written by the FLUX backend at startup.
"""

from __future__ import annotations

from core.logger import get_logger
from dcc.houdini.client import houdini_client

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Python module embedded in the HDA  (runs inside Houdini — stdlib only)
# ─────────────────────────────────────────────────────────────────────────────

PYTHON_MODULE: str = '''
import json, os, urllib.request

def _flux_port():
    try:
        return int(os.environ.get("FLUX_PORT") or
                   open(os.path.join(os.environ.get("APPDATA",""), "FLUX", "backend_port")).read())
    except Exception:
        return 8765

try:
    _url = f"http://127.0.0.1:{_flux_port()}/dcc/houdini/exporter/module"
    with urllib.request.urlopen(_url, timeout=3) as _r:
        exec(json.loads(_r.read())["code"], globals())
except Exception as _offline_err:
    def _noop(*a, **kw): pass
    def _dead_menu(*a, **kw): return ["", "FLUX offline"]
    for _n in ("menu_project","menu_class","menu_type","menu_name","menu_instance","menu_format"):
        globals()[_n] = _dead_menu
    def export_geo(node):
        p = node.parm("status_msg")
        if p: p.set("FLUX offline : démarre le backend puis réessaie")
    on_created = on_loaded = _noop
'''


# ── Full implementation served by GET /dcc/houdini/exporter/module ────────────
# Lives here, version-controlled with the backend.
# exec()'d by the bootstrap above — functions land directly in hou.phm() globals.

_MODULE_FUNCTIONS: str = '''
import json, os, threading, time, urllib.request


# ── port & HTTP ───────────────────────────────────────────────────────────────

_PORT = None

def _flux_port():
    global _PORT
    if _PORT:
        return _PORT
    try:
        _PORT = int(os.environ.get("FLUX_PORT") or
                    open(os.path.join(os.environ.get("APPDATA",""), "FLUX", "backend_port")).read())
    except Exception:
        _PORT = 8765
    return _PORT

_API_BASE = None

def _api():
    global _API_BASE
    if not _API_BASE:
        _API_BASE = f"http://127.0.0.1:{_flux_port()}"
    return _API_BASE

def _get(path, **params):
    url = _api() + path
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items() if v)
    try:
        with urllib.request.urlopen(url, timeout=1.5) as r:
            return json.loads(r.read())
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def _post(path, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        _api() + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def _set_status(node, msg):
    p = node.parm("status_msg")
    if p is not None: p.set(msg)

def _pval(node, name):
    p = node.parm(name)
    return p.eval() if p is not None else ""


# ── cache ─────────────────────────────────────────────────────────────────────
_TTL: float = 60.0
_cache: dict = {}

def _cached(key, fetch_fn):
    now = time.monotonic()
    if key in _cache:
        exp, data = _cache[key]
        if now < exp:
            return data
    data = fetch_fn()
    _cache[key] = (now + _TTL, data)
    return data

def _flat(items):
    result = []
    for item in items: result += [item, item]
    return result

def _tokens(node):
    project = _pval(node, "project")
    if not project: return {}
    return _cached(
        f"tokens:{project}",
        lambda: _get("/dcc/houdini/exporter/tokens", project=project).get("tokens", {}),
    )


# ── menu helpers ──────────────────────────────────────────────────────────────

def menu_project(node):
    projects = _cached("projects", lambda: _get("/dcc/houdini/exporter/tokens").get("projects", []))
    return _flat(projects) if projects else ["", "no projects"]

def menu_class(node):
    keys = list(_tokens(node).get("CLASS", {}).keys())
    return _flat(keys) if keys else ["", "no project"]

_DEFAULT_TYPES = ["SCULPT","BLOCK","TOPO","TEX","LDEV","FUR","HAIR","FEATHERS","SK","WGHT","RIG","CLOTH","MUSCLE","GBL"]

def menu_type(node):
    project_keys = list(_tokens(node).get("TYPE", {}).keys())
    all_types = sorted(set(project_keys + _DEFAULT_TYPES))
    return _flat(all_types)

def menu_name(node):
    toks  = _tokens(node)
    names = toks.get("NAME", {})
    cls   = _pval(node, "flux_class").upper()
    if cls and cls in toks.get("CLASS", {}):
        prefix = toks["CLASS"][cls].rstrip("/")
        filtered = sorted(k for k, v in names.items() if v.startswith(prefix))
        if filtered: return _flat(filtered)
    keys = sorted(names.keys())
    return _flat(keys) if keys else ["", "no project"]

def menu_instance(node):
    toks = _tokens(node)
    instances = list(toks.get("INSTANCE", {}).keys())
    if "null" not in instances: instances = ["null"] + instances
    return _flat(instances)

def menu_format(node):
    return _flat(["bgeo.sc", "abc", "usd", "obj", "fbx"])


# ── export ────────────────────────────────────────────────────────────────────

def export_geo(node):
    project = _pval(node, "project")
    if not project:
        _set_status(node, "No project selected"); return

    _set_status(node, "Exporting…")
    r = _post("/dcc/houdini/exporter/export", {
        "node_path": node.path(),
        "project":   project,
        "class":     _pval(node, "flux_class"),
        "type":      _pval(node, "flux_type"),
        "name":      _pval(node, "flux_name"),
        "instance":  _pval(node, "flux_instance"),
        "format":    _pval(node, "flux_format"),
    })
    if r.get("ok"):
        _set_status(node, f"Exported → {r.get(\'path\', \'\')}")
    else:
        _set_status(node, f"Export failed: {r.get(\'error\', \'unknown\')}")


# ── lifecycle ─────────────────────────────────────────────────────────────────

def _prefetch(node):
    project = _pval(node, "project")
    def _work():
        _cached("projects", lambda: _get("/dcc/houdini/exporter/tokens").get("projects", []))
        if project:
            _cached(f"tokens:{project}",
                    lambda: _get("/dcc/houdini/exporter/tokens", project=project).get("tokens", {}))
    threading.Thread(target=_work, daemon=True).start()

def on_created(node): _prefetch(node)
def on_loaded(node):  _prefetch(node)
'''


# ─────────────────────────────────────────────────────────────────────────────
# HDA build script  (string executed inside Houdini via houdini_client.run())
# ─────────────────────────────────────────────────────────────────────────────

def _build_code(hda_path: str, python_module: str) -> str:
    pm_escaped = python_module.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')

    from pathlib import Path as _P
    icon_path = str(_P(__file__).parents[3] / "resources" / "shelves" / "houdini" / "flux_hda.svg")

    return f'''
import hou

_HDA_PATH = {hda_path!r}
_ICON_PATH = {icon_path!r}
_NODE_NAME = "flux_exporter"
_LABEL     = "FLUX Export"
_CATEGORY  = hou.sopNodeTypeCategory()
_PY = hou.scriptLanguage.Python

# ── 1. Temporary container ────────────────────────────────────────────────────
_obj = hou.node("/obj") or hou.node("/").createNode("obj")
_geo = _obj.createNode("geo", "__flux_exporter_build__")
_geo.deleteItems(_geo.children())

# ── 2. Subnet SOP → future HDA ───────────────────────────────────────────────
_sub = _geo.createNode("subnet", _NODE_NAME)

# ── 3. Parameters ─────────────────────────────────────────────────────────────
_ptg = hou.ParmTemplateGroup()

def _menu_str(name, label, default, menu_fn, help_txt):
    t = hou.StringParmTemplate(
        name, label, 1,
        default_value=(default,),
        string_type=hou.stringParmType.Regular,
        help=help_txt,
    )
    # Houdini 22 runs the bracketed Python item-generator as an EXPRESSION (it must
    # evaluate to the flat menu list) — a leading `return` is a SyntaxError there.
    t.setItemGeneratorScript(f"hou.phm().{{menu_fn}}(kwargs[\\'node\\'])")
    t.setItemGeneratorScriptLanguage(_PY)
    return t

_ptg.append(hou.SeparatorParmTemplate("sep_pipeline"))
_ptg.append(_menu_str("project",      "Project",  "",     "menu_project",  "FLUX project name"))
_ptg.append(_menu_str("flux_class",   "Class",    "CHAR", "menu_class",    "CLASS token (CHAR, PROPS, ENV…)"))
_ptg.append(_menu_str("flux_type",    "Type",     "RIG",  "menu_type",     "TYPE token (RIG, GEO, SCULPT…)"))
_ptg.append(_menu_str("flux_name",    "Name",     "",     "menu_name",     "Asset NAME token"))
_ptg.append(_menu_str("flux_instance","Instance", "null", "menu_instance", "Instance variant"))
_ptg.append(_menu_str("flux_format",  "Format",   "bgeo.sc", "menu_format", "Output file format"))

_ptg.append(hou.SeparatorParmTemplate("sep_action"))

_ptg.append(hou.ButtonParmTemplate(
    "btn_export", "↑  Export",
    script_callback="hou.phm().export_geo(kwargs[\\'node\\'])",
    script_callback_language=_PY,
    help="Export the input geometry to the pipeline path resolved from tokens",
))

_ptg.append(hou.SeparatorParmTemplate("sep_status"))
_ptg.append(hou.StringParmTemplate(
    "status_msg", "Status", 1,
    default_value=("",),
    string_type=hou.stringParmType.Regular,
    help="Last operation result",
))

_sub.setParmTemplateGroup(_ptg)

# ── 4. Internal passthrough node ──────────────────────────────────────────────
# The subnet's indirect input (input connector) is not a node — it has no
# display/render flag — so wire the null straight to it, no setFlag on the input.
_null = _sub.createNode("null", "OUT")
try:
    _null.setInput(0, _sub.indirectInputs()[0])
except Exception:
    pass
_null.setDisplayFlag(True)
_null.setRenderFlag(True)
_sub.layoutChildren()

# ── 5. Convert subnet → HDA ───────────────────────────────────────────────────
_asset = _sub.createDigitalAsset(
    name=_NODE_NAME,
    hda_file_name=_HDA_PATH,
    description=_LABEL,
    min_num_inputs=1,
    max_num_inputs=1,
    version="1.0",
)

# ── 6. Inject PythonModule ────────────────────────────────────────────────────
_hda_def = hou.hdaDefinition(_CATEGORY, _NODE_NAME, _HDA_PATH)
_pm_code = """{{python_module}}"""
if "PythonModule" in _hda_def.sections():
    _hda_def.sections()["PythonModule"].setContents(_pm_code)
else:
    _hda_def.addSection("PythonModule", _pm_code)

try:
    _extra = dict(_hda_def.extraFileOptions())
    _extra["PythonModule.IsPython"] = True
    _extra["OnCreated.IsPython"]    = True
    _extra["OnLoaded.IsPython"]     = True
    _hda_def.setExtraFileOptions(_extra)
except AttributeError:
    pass

if "OnCreated" in _hda_def.sections():
    _hda_def.sections()["OnCreated"].setContents("hou.phm().on_created(kwargs[\\'node\\'])")
else:
    _hda_def.addSection("OnCreated", "hou.phm().on_created(kwargs[\\'node\\'])")

if "OnLoaded" in _hda_def.sections():
    _hda_def.sections()["OnLoaded"].setContents("hou.phm().on_loaded(kwargs[\\'node\\'])")
else:
    _hda_def.addSection("OnLoaded", "hou.phm().on_loaded(kwargs[\\'node\\'])")

# Persist the parameter interface into the definition — createDigitalAsset does
# not reliably capture the subnet's spare parms (it can emit a default, EMPTY
# DialogScript), which would drop the token/format parms. Save so installFile
# loads the full interface.
_hda_def.setParmTemplateGroup(_ptg)

# Embed the FLUX logo as the node icon (portable: stored in the .hda itself).
try:
    import os as _os
    if _ICON_PATH and _os.path.isfile(_ICON_PATH):
        with open(_ICON_PATH, "rb") as _icf:
            _icon_bytes = _icf.read()
        # Houdini 22's HDASection has no setBinaryContents — setContents accepts the
        # raw PNG bytes and stores them as the section payload.
        if "IconSVG" not in _hda_def.sections():
            _hda_def.addSection("IconSVG", _icon_bytes)
        else:
            _hda_def.sections()["IconSVG"].setContents(_icon_bytes)
        _hda_def.setIcon("opdef:.?IconSVG")
except Exception:
    pass  # icon is cosmetic — never fail the build over it

_hda_def.save(_HDA_PATH)

# ── 7. Install and clean up ───────────────────────────────────────────────────
hou.hda.installFile(_HDA_PATH, oplibraries_file=None, change_oplibraries_file=False)
_geo.destroy()

result = {{"ok": True, "path": _HDA_PATH, "node_type": _NODE_NAME}}
'''.replace("{python_module}", pm_escaped)


def build_hda(hda_path: str) -> dict:
    """Build the FLUX Exporter HDA in the running Houdini instance.

    Returns {"ok": True, "path": hda_path} or {"ok": False, "error": "..."}.
    """
    code = _build_code(hda_path, PYTHON_MODULE)
    log.info("Building FLUX Exporter HDA → %s", hda_path)
    resp = houdini_client.run(code)
    if resp.get("ok"):
        log.info("HDA built successfully: %s", hda_path)
    else:
        log.error("HDA build failed: %s", resp.get("error"))
    return resp
