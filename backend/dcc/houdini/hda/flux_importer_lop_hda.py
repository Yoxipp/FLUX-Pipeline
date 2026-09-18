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
"""

from __future__ import annotations

from pathlib import Path

from core.logger import get_logger
from dcc.houdini.client import houdini_client
from dcc.houdini.hda.flux_importer_hda import PYTHON_MODULE

log = get_logger(__name__)

NODE_NAME = "flux_importer"
LABEL = "FLUX Import"
# SOP-only parms of the /obj importer (KineFX character switch, copy to $HIP).
_SOP_ONLY = ("usd_character", "btn_move_local")


def _build_code(hda_path: str, python_module: str) -> str:
    icon_path = str(Path(__file__).parents[3] / "resources" / "shelves" / "houdini" / "flux_hda.png")
    return f'''
import hou

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
_anchor = _ptg.find("sep_resolved")
if _anchor is not None:
    _ptg.insertBefore(_anchor, _auto)
    _ptg.insertBefore(_anchor, _prim)
else:
    _ptg.append(_auto)
    _ptg.append(_prim)
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
_out.setInput(0, _ref)
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
# createDigitalAsset does not always keep spare parms: persist the interface.
_def.setParmTemplateGroup(_ptg)
try:
    import os as _os
    if _os.path.isfile(_ICON_PATH):
        with open(_ICON_PATH, "rb") as _f:
            _bytes = _f.read()
        if "IconImage" in _def.sections():
            _def.sections()["IconImage"].setContents(_bytes)
        else:
            _def.addSection("IconImage", _bytes)
        _def.setIcon("opdef:.?IconImage")
except Exception:
    pass
_def.save(_HDA_PATH)
hou.hda.installFile(_HDA_PATH, oplibraries_file=None, change_oplibraries_file=False)
_asset.destroy()
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
