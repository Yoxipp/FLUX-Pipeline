"""
FLUX - Houdini Importer HDA for Solaris (/stage).

Same node as the /obj importer (2026-09-18: "dans le stage, un HDA flux importer
comme dans obj"): same name ``flux_importer`` but in the LOP category, same menus
(project, tokens / USD library / free path) and the same PythonModule served by the
backend (flux_importer_hda.PYTHON_MODULE bootstrap -> GET /dcc/houdini/importer/module).

Inside: one Reference LOP wired after the node's input, so importers chain like any
LOP. The file lands on ``prim_path`` (/assets/<NAME> for an asset, /sets/<NAME> for a
decor, set by resolve unless "Auto" is off). Every resolve reloads the reference:
Houdini never re-reads a USD file it already opened, so a republished asset would
otherwise keep showing its old version.

The parameter interface is taken from the SOP importer definition (built just before
by the same installer), minus the SOP-only parms, plus the prim parms.

Component content (ADR 0023): for a component of the USD library, one toggle per file,
grouped GEOMETRIE PROXY (every proxy, on top) / GEO / GROOM / LOOKDEV / RIG / ANIM (preview) / AUTRES. The toggles only live on the
node; the inner Python LOP ``apply_component`` sets the matching variant selections
(one variant set per file, "on" / "off") on ``prim_path``. A file without an active
target is greyed (its toggle is kept); warnings show as text and as a node warning.
"""

from __future__ import annotations

from pathlib import Path

from core.logger import get_logger
from dcc.houdini.client import houdini_client
from dcc.houdini.hda.flux_importer_hda import APPLY_FUNC, PYTHON_MODULE

log = get_logger(__name__)

NODE_NAME = "flux_importer"

# Rows per section: fixed (no + / - : FLUX fills them from the component, an empty row
# is hidden). A component never holds this many files of one kind.
MAX_ROWS = 32
# Department layers of a component FLUX Import can compose itself (ADR 0032).
MAX_DEPTS = 8
DEPT_ARCS = ("reference", "payload", "sublayer", "off")
DEPT_ARC_LABELS = ("Reference", "Payload", "Sublayer", "Off")

# (count parm, parm prefix, label) of the component content (ADR 0023).
COMPONENT_FOLDERS = (("proxy_files", "proxy", "GEOMETRIE PROXY"), ("geo_files", "geo", "GEO"), ("groom_files", "groom", "GROOM"),
                     ("look_files", "look", "LOOKDEV"), ("rig_files", "rig", "RIG"),
                     ("anim_files", "anim", "ANIM (preview)"), ("other_files", "other", "AUTRES"))

# Runs inside the apply_component Python LOP: variant selections from comp_state.
APPLY_COMPONENT = APPLY_FUNC + """
_node = hou.pwd()
try:
    # The version served by FLUX (importer module) when it is there: fixes land without
    # rebuilding the HDA. The copy above runs when FLUX is offline or the module is old.
    _fn = _node.parent().hdaModule().apply_component
except Exception:
    _fn = apply_component
_fn(_node)
"""

# Parameter templates of the component content, inserted into the builder script.
_COMPONENT_PARMS = """
_comp = hou.FolderParmTemplate("comp_folder", "Contenu du component", folder_type=hou.folderType.Simple)
_comp.setConditional(hou.parmCondType.HideWhen, "{ source_mode != library } { lib_kind != asset }")
_warn = hou.StringParmTemplate("comp_warnings", "ATTENTION", 1, default_value=("",),
                               tags={"editor": "1", "editorlines": "2-6"},
                               help="Situations to check. Nothing is unselected automatically.")
_warn.setConditional(hou.parmCondType.HideWhen, "{ comp_has_warn == 0 }")
_comp.addParmTemplate(_warn)
for _hidden in (hou.ToggleParmTemplate("comp_has_warn", "has warnings", default_value=False, is_hidden=True),
                hou.StringParmTemplate("comp_state", "state", 1, default_value=("{}",), is_hidden=True),
                hou.StringParmTemplate("comp_key", "key", 1, default_value=("",), is_hidden=True),
                hou.StringParmTemplate("comp_memory", "memory", 1, default_value=("{}",), is_hidden=True),
                hou.StringParmTemplate("comp_groom_full", "groom full", 1, default_value=("[]",), is_hidden=True)):
    _comp.addParmTemplate(_hidden)
for _multi, _prefix, _label in COMPONENT_FOLDERS:
    # Hidden row count set by FLUX; the section is hidden when the component has none.
    _comp.addParmTemplate(hou.IntParmTemplate(_multi, _multi, 1, default_value=(0,), is_hidden=True))
    _m = hou.FolderParmTemplate(_multi + "_folder", _label, folder_type=hou.folderType.Collapsible)
    _m.setConditional(hou.parmCondType.HideWhen, "{ " + _multi + " == 0 }")
    for _i in range(1, MAX_ROWS + 1):
        _n = str(_i)
        _hide = '{ ' + _prefix + '_id' + _n + ' == "" }'
        _on = hou.ToggleParmTemplate(_prefix + "_on" + _n, "Actif", default_value=True,
                                     script_callback="hou.phm().on_component_toggle(kwargs['node'])",
                                     script_callback_language=_PY,
                                     help="Greyed: none of its targets is active (its state is kept)")
        _on.setConditional(hou.parmCondType.DisableWhen, "{ " + _prefix + "_ok" + _n + " == 0 }")
        _on.setConditional(hou.parmCondType.HideWhen, _hide)
        _on.setJoinWithNext(True)
        _m.addParmTemplate(_on)
        if _prefix == "groom":
            # ADR 0026: the thinned proxy in the viewport (on), or the complete groom.
            _px = hou.ToggleParmTemplate("groom_proxy" + _n, "Proxy", default_value=True,
                                         script_callback="hou.phm().on_component_toggle(kwargs['node'])",
                                         script_callback_language=_PY,
                                         help="On: light proxy (1 curve in 10) in the viewport, full groom "
                                              "at render. Off: the full groom in the viewport too.")
            _px.setConditional(hou.parmCondType.HideWhen, _hide)
            _px.setJoinWithNext(True)
            _m.addParmTemplate(_px)
        _lbl = hou.StringParmTemplate(_prefix + "_label" + _n, "Fichier", 1, default_value=("",))
        _lbl.setConditional(hou.parmCondType.HideWhen, _hide)
        _m.addParmTemplate(_lbl)
        _m.addParmTemplate(hou.StringParmTemplate(_prefix + "_id" + _n, "id", 1, default_value=("",), is_hidden=True))
        _m.addParmTemplate(hou.ToggleParmTemplate(_prefix + "_ok" + _n, "ok", default_value=True, is_hidden=True))
    _comp.addParmTemplate(_m)
# ADR 0032: how each department layer of the component comes in (component = its own arcs).
_arcs = hou.FolderParmTemplate("dept_folder", "Composition", folder_type=hou.folderType.Collapsible)
_arcs.setConditional(hou.parmCondType.HideWhen, "{ dept_count == 0 }")
_arcs.addParmTemplate(hou.IntParmTemplate("dept_count", "dept count", 1, default_value=(0,), is_hidden=True))
_arcs.addParmTemplate(hou.StringParmTemplate("dept_memory", "dept memory", 1, default_value=("{}",), is_hidden=True))
_dmode = hou.MenuParmTemplate("dept_mode", "Mode", ("component", "departments"),
                              menu_labels=("Component FLUX (auto)", "Par departement"), default_value=0,
                              script_callback="hou.phm().on_dept_change(kwargs['node'])",
                              script_callback_language=_PY,
                              help="Component: the component as FLUX composed it. Par departement: each "
                                   "department layer comes in with the arc chosen below.")
_arcs.addParmTemplate(_dmode)
for _i in range(1, MAX_DEPTS + 1):
    _n = str(_i)
    _hide = '{ dept_id' + _n + ' == "" } { dept_mode == component }'
    _arc = hou.MenuParmTemplate("dept_arc" + _n, "Arc", DEPT_ARCS, menu_labels=DEPT_ARC_LABELS,
                                default_value=0,
                                script_callback="hou.phm().on_dept_change(kwargs['node'])",
                                script_callback_language=_PY,
                                help="Reference: under the asset prim. Payload: same, unloadable. "
                                     "Sublayer: the layer joins the stage (its prims keep /<NAME>). "
                                     "Off: the department is left out.")
    _arc.setConditional(hou.parmCondType.HideWhen, _hide)
    _arc.setJoinWithNext(True)
    _arcs.addParmTemplate(_arc)
    _dl = hou.StringParmTemplate("dept_label" + _n, "Departement", 1, default_value=("",))
    _dl.setConditional(hou.parmCondType.HideWhen, _hide)
    _arcs.addParmTemplate(_dl)
    for _h in ("dept_id", "dept_file", "dept_ref", "dept_rtype", "dept_sub"):
        _arcs.addParmTemplate(hou.StringParmTemplate(_h + _n, _h, 1, default_value=("",), is_hidden=True))
_comp.addParmTemplate(_arcs)
"""
LABEL = "FLUX Import"
# SOP-only parms of the /obj importer (KineFX character switch, copy to $HIP).
# geo_display is re-added below with the LOP wiring (configureprimitive, not a purpose filter).
_SOP_ONLY = ("usd_character", "btn_move_local", "geo_display")


def _build_code(hda_path: str, python_module: str) -> str:
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
_PM_CODE = {python_module!r}

_sop_type = hou.nodeType(hou.sopNodeTypeCategory(), _NAME)
if _sop_type is None or _sop_type.definition() is None:
    raise RuntimeError("SOP flux_importer absent : construire d'abord l'importer /obj")
_ptg = _sop_type.definition().parmTemplateGroup()
for _pn in {_SOP_ONLY!r}:
    if _ptg.find(_pn) is not None:
        _ptg.remove(_pn)

# Where the file lands in the stage; resolve fills it while "Auto" is on.
_auto = hou.ToggleParmTemplate("prim_auto", "Auto", default_value=True,
                               help="Prim chosen by FLUX (/assets/NAME, /sets/NAME)")
_auto.setJoinWithNext(True)
_prim = hou.StringParmTemplate("prim_path", "Primitive Path", 1, default_value=("/assets/asset",),
                               help="Prim that receives the reference")
_prim.setConditional(hou.parmCondType.DisableWhen, "{{ prim_auto == 1 }}")
_reload = hou.ButtonParmTemplate("btn_reload", "Reload",
                                 script_callback="hou.phm().resolve_path(kwargs['node'])",
                                 script_callback_language=_PY,
                                 help="Re-read the files from disk (after a republish)")
# Viewport geometry (2026-09-18): the light proxy, or the full render mesh.
_disp = hou.MenuParmTemplate("geo_display", "Geometrie", ("proxy", "render"),
                             menu_labels=("Proxy (leger)", "Geo complete"), default_value=0,
                             help="Proxy: purpose=proxy mesh in the viewport. Geo complete: the "
                                  "render mesh is shown (purpose default) and the proxy hidden.")
# ADR 0031: loading the heavy geometry is the importer's choice (payload loaded or not).
_loadgeo = hou.ToggleParmTemplate("load_geo", "Charger la geo", default_value=True,
                                  help="Decoche : l'asset reste decharge (payload), le viewport et les "
                                       "caches restent legers. Le rendu charge tout.")
# Set by resolve: 1 = a shot stage (sublayered, ADR 0020), 0 = an asset / decor (referenced).
_as_sub = hou.ToggleParmTemplate("as_sublayer", "Shot (sublayer)", default_value=False, is_hidden=True)
COMPONENT_FOLDERS = {COMPONENT_FOLDERS!r}
MAX_DEPTS = {MAX_DEPTS!r}
DEPT_ARCS = {DEPT_ARCS!r}
DEPT_ARC_LABELS = {DEPT_ARC_LABELS!r}
{_COMPONENT_PARMS}
_anchor = _ptg.find("sep_resolved")
if _anchor is not None:
    _ptg.insertBefore(_anchor, _auto)
    _ptg.insertBefore(_anchor, _prim)
    _ptg.insertBefore(_anchor, _disp)
    _ptg.insertBefore(_anchor, _loadgeo)
    _ptg.insertBefore(_anchor, _as_sub)
    _ptg.insertBefore(_anchor, _comp)
else:
    _ptg.append(_auto)
    _ptg.append(_prim)
    _ptg.append(_disp)
    _ptg.append(_loadgeo)
    _ptg.append(_as_sub)
    _ptg.append(_comp)
_btn = _ptg.find("btn_resolve")
if _btn is not None:
    _ptg.insertAfter(_btn, _reload)
else:
    _ptg.append(_reload)

_stage = hou.node("/stage") or hou.node("/").createNode("lopnet", "stage")
_old = _stage.node("__flux_importer_lop_build__")
if _old is not None:
    _old.destroy()
_sub = _stage.createNode("subnet", "__flux_importer_lop_build__")
for _c in _sub.children():
    if _c.type().name() != "output":
        _c.destroy()
_out = next((c for c in _sub.children() if c.type().name() == "output"), None) \\
    or _sub.createNode("output", "output0")
_ref = _sub.createNode("reference", "reference")
_ref.setInput(0, _sub.indirectInputs()[0])
_ref.parm("filepath1").setExpression('chs("../resolved_path")', hou.exprLanguage.Hscript)
_ref.parm("primpath1").setExpression('chs("../prim_path")', hou.exprLanguage.Hscript)
# A shot stage (ADR 0020) is a whole scene: sublayered instead of referenced.
_subl = _sub.createNode("sublayer", "sublayer")
_subl.setInput(0, _sub.indirectInputs()[0])
_subl.parm("filepath1").setExpression('chs("../resolved_path")', hou.exprLanguage.Hscript)
_load = _sub.createNode("switch", "load_mode")
_load.setInput(0, _ref)
_load.setInput(1, _subl)
_load.parm("input").setExpression('ch("../as_sublayer")', hou.exprLanguage.Hscript)
# ADR 0032: "Par departement": each department layer with its own arc (sublayers first,
# then references / payloads under prim_path). An empty entry composes nothing.
_dsub = _sub.createNode("sublayer", "dept_sublayers")
_dsub.setInput(0, _sub.indirectInputs()[0])
_dsub.parm("num_files").set(MAX_DEPTS)
_dref = _sub.createNode("reference", "dept_references")
_dref.setInput(0, _dsub)
_dref.parm("num_files").set(MAX_DEPTS)
for _i in range(1, MAX_DEPTS + 1):
    _dsub.parm("filepath%d" % _i).setExpression('chs("../dept_sub%d")' % _i, hou.exprLanguage.Hscript)
    _dref.parm("filepath%d" % _i).setExpression('chs("../dept_ref%d")' % _i, hou.exprLanguage.Hscript)
    _dref.parm("primpath%d" % _i).setExpression('chs("../prim_path")', hou.exprLanguage.Hscript)
    _dref.parm("reftype%d" % _i).setExpression('chs("../dept_rtype%d")' % _i, hou.exprLanguage.Hscript)
_mode = _sub.createNode("switch", "compose_mode")
_mode.setInput(0, _load)
_mode.setInput(1, _dref)
_mode.parm("input").setExpression('if(ch("../dept_count") > 0, ch("../dept_mode"), 0)',
                                  hou.exprLanguage.Hscript)
# ADR 0023: the importer's own choices (variant selections), never saved in the component.
_apply = _sub.createNode("pythonscript", "apply_component")
_apply.setInput(0, _mode)
_apply.parm("python").set({APPLY_COMPONENT!r})
# "Geo complete": render meshes shown in the viewport (purpose default), proxy hidden.
# Two patterns: the asset itself (prim_path/geo) and every asset below it (a shot: /assets/**).
_full = _sub.createNode("configureprimitive", "show_render_geo")
_full.setInput(0, _apply)
_full.parm("primpattern").set('`chs("../prim_path")`/geo/render/** `chs("../prim_path")`/**/geo/render/**')
_full.parm("setpurpose").set(1)
_full.parm("purpose").set("default")
_hide = _sub.createNode("configureprimitive", "hide_proxy")
_hide.setInput(0, _full)
_hide.parm("primpattern").set('`chs("../prim_path")`/geo/proxy `chs("../prim_path")`/**/geo/proxy')
_hide.parm("setvisibility").set(1)
_hide.parm("visibility").set("invisible")
_sw = _sub.createNode("switch", "geo_display")
_sw.setInput(0, _apply)
_sw.setInput(1, _hide)
_sw.parm("input").setExpression('ch("../geo_display")', hou.exprLanguage.Hscript)
# "Charger la geo" off: the prim's payloads stay unloaded (Configure Stage load rules).
_unload = _sub.createNode("configurestage", "unload_geo")
_unload.setInput(0, _sw)
_unload.parm("editload").set("addremove")
_unload.parm("unloadpaths").set('`chs("../prim_path")`')
_ld = _sub.createNode("switch", "load_geo")
_ld.setInput(0, _unload)
_ld.setInput(1, _sw)
_ld.parm("input").setExpression('ch("../load_geo")', hou.exprLanguage.Hscript)
_out.setInput(0, _ld)
_sub.layoutChildren()

_asset = _sub.createDigitalAsset(name=_NAME, hda_file_name=_HDA_PATH, description={LABEL!r},
                                 min_num_inputs=0, max_num_inputs=1, version="1.0")
{_finalize}
{_restore}
result = {{"ok": True, "path": _HDA_PATH, "node_type": "Lop/" + _NAME}}
'''


def build_hda(hda_path: str) -> dict:
    """Build the /stage FLUX Import HDA in the running Houdini (needs the SOP importer)."""
    log.info("Building FLUX Import LOP HDA -> %s", hda_path)
    resp = houdini_client.run(_build_code(hda_path, PYTHON_MODULE))
    if resp.get("ok"):
        log.info("LOP importer HDA built: %s", hda_path)
    else:
        log.error("LOP importer HDA build failed: %s", resp.get("error"))
    return resp
