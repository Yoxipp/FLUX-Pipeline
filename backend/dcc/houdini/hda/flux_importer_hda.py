"""
FLUX — Houdini Importer HDA.

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

# ── Bootstrap baked into the HDA  (15 lines, never needs to change) ──────────
# Fetches the real implementation from the FLUX backend at load time.
# → Update the backend code = update the HDA behaviour. Zero re-injection needed.

PYTHON_MODULE: str = '''
import json, os, urllib.request

def _flux_port():
    try:
        return int(os.environ.get("FLUX_PORT") or
                   open(os.path.join(os.environ.get("APPDATA",""), "FLUX", "backend_port")).read())
    except Exception:
        return 8765

try:
    _url = f"http://localhost:{_flux_port()}/dcc/houdini/importer/module"
    with urllib.request.urlopen(_url, timeout=3) as _r:
        exec(json.loads(_r.read())["code"], globals())
except Exception as _offline_err:
    # Safe stubs so the HDA never hard-errors when FLUX is not running.
    # resolve_path tente une reconnexion à chaque appel (bouton ↺ Resolve).
    def _try_reconnect():
        try:
            with urllib.request.urlopen(
                f"http://localhost:{_flux_port()}/dcc/houdini/importer/module", timeout=3
            ) as _r:
                exec(json.loads(_r.read())["code"], globals())
            return True
        except Exception:
            return False
    def _dead_menu(*a, **kw): return ["", "FLUX offline"]
    def _noop(*a, **kw): pass
    for _n in ("menu_project","menu_class","menu_type","menu_name","menu_instance","menu_iter"):
        globals()[_n] = _dead_menu
    def resolve_path(node):
        if _try_reconnect():
            globals()["resolve_path"](node)
            return
        node.parm("status_msg").set("FLUX offline : démarre le backend puis clique ↺ Resolve")
    move_to_local = use_hub = on_created = on_loaded = _noop
'''


# ── Full implementation served by GET /dcc/houdini/importer/module ────────────
# Lives here, version-controlled with the backend.
# exec()'d by the bootstrap above — functions land directly in hou.phm() globals.

_MODULE_FUNCTIONS: str = '''
import json, os, threading, time, urllib.request


# ── port & HTTP ───────────────────────────────────────────────────────────────

_PORT = None  # cached once per Houdini session

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

_API_BASE = None  # cached alongside port

def _api():
    global _API_BASE
    if not _API_BASE:
        _API_BASE = f"http://localhost:{_flux_port()}"
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
        with urllib.request.urlopen(req, timeout=6) as r:
            return json.loads(r.read())
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def _set_status(node, msg):
    p = node.parm("status_msg")
    if p is not None: p.set(msg)


# ── menu helpers ──────────────────────────────────────────────────────────────
# Called by each parameter\'s Item Generator Script:
#   return hou.phm().menu_xxx(kwargs["node"])
# Houdini expects a flat list: [value1, label1, value2, label2, ...]

def _flat(items):
    result = []
    for item in items: result += [item, item]
    return result

def _pval(node, name):
    """Safe parm read — returns '' if the parm doesn't exist."""
    p = node.parm(name)
    return p.eval() if p is not None else ""

# ── cache ─────────────────────────────────────────────────────────────────────
# Responses cached for _TTL seconds so menu opens never block the UI thread.
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

def _tokens(node):
    project = _pval(node, "project")
    if not project: return {}
    return _cached(
        f"tokens:{project}",
        lambda: _get("/dcc/houdini/importer/tokens", project=project).get("tokens", {}),
    )

def menu_project(node):
    projects = _cached("projects", lambda: _get("/dcc/houdini/importer/tokens").get("projects", []))
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

def menu_iter(node):
    project = _pval(node, "project")
    if not project: return _flat(["LAST"])
    cls  = _pval(node, "flux_class")
    typ  = _pval(node, "flux_type")
    name = _pval(node, "flux_name")
    inst = _pval(node, "flux_instance")
    key  = f"iters:{project}:{cls}:{typ}:{name}:{inst}"
    r = _cached(key, lambda: _get(
        "/dcc/houdini/importer/iters",
        project=project,
        **{"class": cls},
        type=typ, name=name, instance=inst,
    ))
    return _flat(r.get("iters", ["LAST"]))


# ── resolve ───────────────────────────────────────────────────────────────────

def resolve_path(node):
    project = _pval(node, "project")
    if not project:
        _set_status(node, "No project selected"); return
    r = _get(
        "/dcc/houdini/importer/resolve",
        project=project,
        **{"class": _pval(node, "flux_class")},
        type=_pval(node, "flux_type"),
        name=_pval(node, "flux_name"),
        instance=_pval(node, "flux_instance"),
        iter=_pval(node, "flux_iter"),
    )
    if r.get("ok") and r.get("path"):
        p = node.parm("resolved_path")
        if p: p.set(r["path"])
        _set_status(node, f"OK  [{r.get(\'ext\',\'\')}]")
    else:
        p = node.parm("resolved_path")
        if p: p.set("")
        _set_status(node, r.get("error", "File not found"))


# ── move to local ─────────────────────────────────────────────────────────────

def move_to_local(node):
    path = _pval(node, "resolved_path")
    if not path:
        _set_status(node, "Resolve a path first"); return
    r = _post("/dcc/houdini/import/move_to_local", {"file_path": path})
    if r.get("ok"):
        p = node.parm("resolved_path")
        if p: p.set(r["local_path"])
        _set_status(node, "Moved → " + r["local_path"])
    else:
        _set_status(node, "Move failed: " + r.get("error", "unknown"))


# ── use hub ───────────────────────────────────────────────────────────────────

def use_hub(node):
    _set_status(node, "Opening FLUX Hub…")
    _get("/dcc/houdini/importer/open_hub")


# ── lifecycle ─────────────────────────────────────────────────────────────────

def _prefetch(node):
    """Warm the cache in a background thread so menus are instant on first open."""
    project = _pval(node, "project")
    def _work():
        _cached("projects", lambda: _get("/dcc/houdini/importer/tokens").get("projects", []))
        if project:
            _cached(f"tokens:{project}",
                    lambda: _get("/dcc/houdini/importer/tokens", project=project).get("tokens", {}))
    threading.Thread(target=_work, daemon=True).start()

def on_created(node):
    _prefetch(node)

def on_loaded(node):
    _prefetch(node)
    resolve_path(node)
'''


# ─────────────────────────────────────────────────────────────────────────────
# HDA build script  (string executed inside Houdini via houdini_client.run())
# ─────────────────────────────────────────────────────────────────────────────

def _build_code(hda_path: str, python_module: str) -> str:
    """Return the Python code string that creates the HDA inside Houdini."""

    # Escape the python_module so it can be embedded safely in a triple-quoted string
    pm_escaped = python_module.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')

    return f'''
import hou

_HDA_PATH = {hda_path!r}
_NODE_NAME = "flux_importer"
_LABEL     = "FLUX Import"
_CATEGORY  = hou.sopNodeTypeCategory()

# ── 1. Create a temporary geo container ──────────────────────────────────────
_obj = hou.node("/obj") or hou.node("/").createNode("obj")
_geo = _obj.createNode("geo", "__flux_importer_build__")
_geo.deleteItems(_geo.children())  # remove default nodes

# ── 2. Create a subnet SOP to become the HDA ─────────────────────────────────
_sub = _geo.createNode("subnet", _NODE_NAME)

# ── 3. Build parameter interface ──────────────────────────────────────────────
_ptg = hou.ParmTemplateGroup()
_PY = hou.scriptLanguage.Python

def _menu_str(name, label, default, menu_fn, help_txt):
    """StringParmTemplate with a dynamic item generator that calls hou.phm()."""
    t = hou.StringParmTemplate(
        name, label, 1,
        default_value=(default,),
        string_type=hou.stringParmType.Regular,
        help=help_txt,
    )
    t.setItemGeneratorScript(f"return hou.phm().{menu_fn}(kwargs[\\'node\\'])")
    t.setItemGeneratorScriptLanguage(_PY)
    return t

_ptg.append(hou.SeparatorParmTemplate("sep_pipeline"))

# Project — changing it also re-resolves
_ptg.append(_menu_str("project",      "Project",   "",     "menu_project",  "FLUX project name"))
_ptg.append(_menu_str("flux_class",   "Class",     "CHAR", "menu_class",    "CLASS token (CHAR, PROPS, ENV…)"))
_ptg.append(_menu_str("flux_type",    "Type",      "RIG",  "menu_type",     "TYPE token (RIG, GEO, SCULPT…)"))
_ptg.append(_menu_str("flux_name",    "Name",      "",     "menu_name",     "Asset NAME token (e.g. HERO_A)"))
_ptg.append(_menu_str("flux_instance","Instance",  "null", "menu_instance", "Instance variant (null, A, B…)"))
_ptg.append(_menu_str("flux_iter",    "Iteration", "LAST", "menu_iter",     "Version: LAST, v001, v002…"))

_ptg.append(hou.SeparatorParmTemplate("sep_resolved"))

# Resolved path — display only (no callback, no menu)
_rp = hou.StringParmTemplate(
    "resolved_path", "Resolved Path", 1,
    default_value=("",),
    string_type=hou.stringParmType.Regular,
    help="Absolute path resolved from tokens (auto-updated on parm change)",
)
_ptg.append(_rp)

# Resolve button — explicit re-resolve (useful after backend restart)
_btn_resolve = hou.ButtonParmTemplate(
    "btn_resolve", "↺  Resolve",
    script_callback="hou.phm().resolve_path(kwargs[\\'node\\'])",
    script_callback_language=_PY,
    help="Re-resolve the pipeline path from current tokens",
)
_ptg.append(_btn_resolve)

_ptg.append(hou.SeparatorParmTemplate("sep_options"))

# Move to local button
_ptg.append(hou.ButtonParmTemplate(
    "btn_move_local", "Move to Local  ($HIP/sourceimages/)",
    script_callback="hou.phm().move_to_local(kwargs[\\'node\\'])",
    script_callback_language=_PY,
    help="Copy the resolved file into the current Houdini project folder",
))

# Use Hub button
_ptg.append(hou.ButtonParmTemplate(
    "btn_use_hub", "Use the Hub",
    script_callback="hou.phm().use_hub(kwargs[\\'node\\'])",
    script_callback_language=hou.scriptLanguage.Python,
    help="Open or bring the FLUX Hub to the foreground",
))

_ptg.append(hou.SeparatorParmTemplate("sep_status"))

# Status label
_ptg.append(hou.StringParmTemplate(
    "status_msg", "Status", 1,
    default_value=("",),
    string_type=hou.stringParmType.Regular,
    help="Last operation result",
))

_sub.setParmTemplateGroup(_ptg)

# ── 4. Create internal import nodes ──────────────────────────────────────────
_usd  = _sub.createNode("usdimport", "usd_import")
_abc  = _sub.createNode("alembic",   "abc_import")
_file = _sub.createNode("file",      "file_import")
_sw   = _sub.createNode("switch",    "format_switch")

# Wire: 0=USD, 1=ABC, 2=File
_sw.setInput(0, _usd)
_sw.setInput(1, _abc)
_sw.setInput(2, _file)

# Path expressions reference the HDA parameter via ch().
# Parm names drift across Houdini versions (usdimport: filepath vs filepath1),
# so bind the first parm that actually exists instead of hardcoding one.
def _bind_path(_n, _candidates):
    for _pn in _candidates:
        _p = _n.parm(_pn)
        if _p is not None:
            _p.setExpression('ch("../../resolved_path")', hou.exprLanguage.Python)
            return _pn
    raise RuntimeError(
        "No file parm found on " + _n.type().name() + " (tried " + ", ".join(_candidates) + ")"
    )

_bind_path(_usd,  ["filepath1", "filepath", "file"])
_bind_path(_abc,  ["fileName", "filename", "file"])
_bind_path(_file, ["file", "filename"])

# Switch driven by file extension
_sw.parm("input").setExpression("""
_ext = hou.pwd().parent().parm("resolved_path").eval().lower()
if _ext.endswith(".bgeo.sc"):
    _ext = ".bgeo.sc"
else:
    import os
    _ext = os.path.splitext(_ext)[1]
return {{"usd":0,"usda":0,"usdc":0,"usdz":0,".usd":0,".usda":0,".usdc":0,".usdz":0,
         "abc":1,".abc":1,
         "bgeo":2,".bgeo":2,".bgeo.sc":2,"geo":2,".geo":2,"obj":2,".obj":2,"fbx":2,".fbx":2}}.get(_ext, 0)
""".strip(), hou.exprLanguage.Python)

# Output connector — expose the switch output
_out = _sub.createNode("output", "OUT")
_out.setInput(0, _sw)
_sub.layoutChildren()

# ── 5. Convert subnet → HDA ───────────────────────────────────────────────────
_asset = _sub.createDigitalAsset(
    name=_NODE_NAME,
    hda_file_name=_HDA_PATH,
    description=_LABEL,
    min_num_inputs=0,
    max_num_inputs=0,
    version="1.0",
)

# ── 6. Inject PythonModule into the HDA definition ───────────────────────────
_hda_def = hou.hdaDefinition(_CATEGORY, _NODE_NAME, _HDA_PATH)
_pm_code = """{python_module}"""
if "PythonModule" in _hda_def.sections():
    _hda_def.sections()["PythonModule"].setContents(_pm_code)
else:
    _hda_def.addSection("PythonModule", _pm_code)

# Set OnCreated / OnLoaded events
# setExtraFileOptions marks sections as Python for the editor; best-effort only
try:
    _extra = dict(_hda_def.extraFileOptions())
    _extra["PythonModule.IsPython"] = True
    _extra["OnCreated.IsPython"] = True
    _extra["OnLoaded.IsPython"] = True
    _hda_def.setExtraFileOptions(_extra)
except AttributeError:
    pass  # PythonModule / OnCreated / OnLoaded are always executed as Python

if "OnCreated" in _hda_def.sections():
    _hda_def.sections()["OnCreated"].setContents("hou.phm().on_created(kwargs[\\'node\\'])")
else:
    _hda_def.addSection("OnCreated", "hou.phm().on_created(kwargs[\\'node\\'])")

if "OnLoaded" in _hda_def.sections():
    _hda_def.sections()["OnLoaded"].setContents("hou.phm().on_loaded(kwargs[\\'node\\'])")
else:
    _hda_def.addSection("OnLoaded", "hou.phm().on_loaded(kwargs[\\'node\\'])")

# ── 7. Install and clean up ───────────────────────────────────────────────────
hou.hda.installFile(_HDA_PATH, oplibraries_file=None, change_oplibraries_file=False)
_geo.destroy()

result = {{"ok": True, "path": _HDA_PATH, "node_type": _NODE_NAME}}
'''.replace("{python_module}", pm_escaped)


def build_hda(hda_path: str) -> dict:
    """Build the FLUX Importer HDA in the running Houdini instance.

    Creates all parameters, internal nodes, switch logic, and injects the
    Python module. Saves the result to *hda_path* (absolute path, .hda).

    Returns {"ok": True, "path": hda_path} or {"ok": False, "error": "..."}.
    """
    code = _build_code(hda_path, PYTHON_MODULE)
    log.info("Building FLUX Importer HDA → %s", hda_path)
    resp = houdini_client.run(code)
    if resp.get("ok"):
        log.info("HDA built successfully: %s", hda_path)
    else:
        log.error("HDA build failed: %s", resp.get("error"))
    return resp


def inject_module(hda_name: str = "flux_importer") -> dict:
    """Inject PYTHON_MODULE into an already-loaded HDA definition in Houdini.

    Use this when the HDA was created manually and its PythonModule section is
    empty. Works on any Houdini instance with the HDA already installed/loaded.

    Updates all existing node instances in the scene so they pick up the new code.

    Returns {"ok": True, "instances_updated": N} or {"ok": False, "error": "..."}.
    """
    # Embed the module code as a raw string inside the Houdini-side exec.
    # We use repr() to produce a safe Python string literal that survives
    # any quotes or backslashes in PYTHON_MODULE.
    pm_repr = repr(PYTHON_MODULE)

    code = f"""
import hou

_NAME    = {hda_name!r}
_PM_CODE = {pm_repr}

# Locate the HDA definition via its node type (compatible with all Houdini versions)
_node_type = hou.nodeType(hou.sopNodeTypeCategory(), _NAME)
if not _node_type:
    raise RuntimeError(
        f"Node type '{{_NAME}}' not found. "
        "Make sure the HDA is installed and a node exists in the scene."
    )

_hda_def = _node_type.definition()
if not _hda_def:
    raise RuntimeError(
        f"Node type '{{_NAME}}' has no HDA definition, it may be a built-in node."
    )

# Write PythonModule section
if "PythonModule" in _hda_def.sections():
    _hda_def.sections()["PythonModule"].setContents(_PM_CODE)
else:
    _hda_def.addSection("PythonModule", _PM_CODE)

# Mark the section as Python so hou.phm() works (best-effort — PythonModule is implicitly Python)
try:
    _extra = dict(_hda_def.extraFileOptions())
    _extra["PythonModule.IsPython"] = True
    _hda_def.setExtraFileOptions(_extra)
except AttributeError:
    pass  # Older Houdini: PythonModule is always executed as Python by hou.phm()

# Reload all scene instances so they pick up the new code immediately
_instances = _node_type.instances() if _node_type else []
for _n in _instances:
    _n.matchCurrentDefinition()

result = {{
    "ok":               True,
    "node_type":        _NAME,
    "instances_updated": len(_instances),
    "hda_file":         str(_hda_def.libraryFilePath()),
}}
"""

    log.info("Injecting PythonModule into HDA '%s'", hda_name)
    resp = houdini_client.run(code)
    if resp.get("ok"):
        log.info(
            "PythonModule injected — %d instance(s) updated",
            resp.get("result", {}).get("instances_updated", 0),
        )
    else:
        log.error("inject_module failed: %s", resp.get("error"))
    return resp
