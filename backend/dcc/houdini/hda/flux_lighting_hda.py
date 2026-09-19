"""
FLUX — Houdini Lighting HDA (LOP).

The lighting network the sequence/shot template scenes are built around, packaged
as a reusable FLUX digital asset so every generated .hip drops the SAME node and
only repoints two paths.

Responsibilities:
  1. build_hda()  — Creates the HDA programmatically in a running Houdini instance
                    via houdini_client.run(), saves it to an .hda file. Installed
                    alongside flux_importer / flux_exporter (autostart + shelf).

  2. The node itself (a LOP subnet) exposes two repointable string parms:
       - usd_input   : the seq/shot root USD to sublayer (base scene to light)
       - usd_output  : the *_light.usda the light rig is written to
     plus a base light rig (dome + key distant) authored into /World/Lighting and a
     USD ROP configured to write usd_output. Paths default to $HIP-relative so a
     generated scene stays portable when the project moves.

No hardcoded user/project path lives in the HDA — the generator (houdini_scene_template)
sets usd_input / usd_output per seq/shot after loading the template.
"""

from __future__ import annotations

from core.logger import get_logger
from dcc.houdini.client import houdini_client

log = get_logger(__name__)

# Node type name — kept stable so houdini_scene_template can find the node by type.
NODE_TYPE_NAME: str = "flux_lighting"


def _build_code(hda_path: str) -> str:
    from pathlib import Path as _P
    icon_path = str(_P(__file__).parents[3] / "resources" / "shelves" / "houdini" / "flux_hda.svg")

    return f'''
import hou

_HDA_PATH  = {hda_path!r}
_ICON_PATH = {icon_path!r}
_NODE_NAME = "flux_lighting"
_LABEL     = "FLUX Lighting"
_CATEGORY  = hou.lopNodeTypeCategory()
_PY = hou.scriptLanguage.Python

# ── 1. Temporary LOP container (/stage) ───────────────────────────────────────
_stage = hou.node("/stage") or hou.node("/").createNode("stage")
_sub = _stage.createNode("subnet", "__flux_lighting_build__")

# ── 2. Build the lighting network INSIDE the subnet ───────────────────────────
# A weak base light rig (dome + key), a sublayer of the scene being lit, and a
# USD ROP writing the light layer. All paths come from the subnet's own parms.
_domelight = _sub.createNode("domelight::3.0", "seq_dome") if _sub.type().category().nodeType("domelight::3.0") else None
if _domelight is None:
    try:
        _domelight = _sub.createNode("domelight", "seq_dome")
    except Exception:
        _domelight = None
try:
    _key = _sub.createNode("distantlight::3.0", "seq_key")
except Exception:
    try:
        _key = _sub.createNode("distantlight", "seq_key")
    except Exception:
        _key = None

# sublayer the scene we light (usd_input) so the rig composes over it
try:
    _sublayer = _sub.createNode("sublayer", "scene_input")
    _sublayer.parm("filepath1").set('`chs("../usd_input")`')
except Exception:
    _sublayer = None

# chain lights after the sublayer (weak base rig)
_prev = _sublayer
for _ln in (_domelight, _key):
    if _ln is None:
        continue
    if _prev is not None:
        try:
            _ln.setInput(0, _prev)
        except Exception:
            pass
    _prev = _ln

# default light intensities (weak base — shots refine)
try:
    if _domelight is not None:
        _domelight.parm("xn__inputsintensity_i0a").set(1.0)
except Exception:
    pass

# USD ROP that writes the light layer (usd_output)
try:
    _rop = _sub.createNode("usd_rop", "export_light")
    _rop.parm("lopoutput").set('`chs("../usd_output")`')
    if _prev is not None:
        _rop.setInput(0, _prev)
    _prev = _rop
except Exception:
    _rop = None

# terminal output node so the subnet has a display flag
try:
    _out = _sub.createNode("null", "OUT")
    if _prev is not None:
        _out.setInput(0, _prev)
    _out.setDisplayFlag(True)
except Exception:
    pass
_sub.layoutChildren()

# ── 3. Repointable parameters on the subnet ───────────────────────────────────
_ptg = hou.ParmTemplateGroup()
_ptg.append(hou.SeparatorParmTemplate("sep_paths"))
_ptg.append(hou.StringParmTemplate(
    "usd_input", "USD Input", 1, default_value=("",),
    string_type=hou.stringParmType.FileReference,
    help="Seq/shot root USD to light (sublayered). Prefer a $HIP-relative path.",
))
_ptg.append(hou.StringParmTemplate(
    "usd_output", "Light USD Output", 1, default_value=("$HIP/lighting/light.usda",),
    string_type=hou.stringParmType.FileReference,
    help="Where the light rig USD layer is written. Prefer a $HIP-relative path.",
))
_ptg.append(hou.SeparatorParmTemplate("sep_action"))
_ptg.append(hou.ButtonParmTemplate(
    "btn_save", "Save Light USD",
    script_callback="hou.node(kwargs['node'].path()+'/export_light').parm('execute').pressButton()",
    script_callback_language=_PY,
    help="Cook the USD ROP and write the light layer to USD Output",
))
_sub.setParmTemplateGroup(_ptg)

# ── 4. Convert subnet → HDA ───────────────────────────────────────────────────
_asset = _sub.createDigitalAsset(
    name=_NODE_NAME,
    hda_file_name=_HDA_PATH,
    description=_LABEL,
    min_num_inputs=0,
    max_num_inputs=1,
    version="1.0",
)

_hda_def = hou.hdaDefinition(_CATEGORY, _NODE_NAME, _HDA_PATH)
_hda_def.setParmTemplateGroup(_ptg)

# Embed the FLUX logo as the node icon (portable — stored in the .hda).
try:
    import os as _os
    if _ICON_PATH and _os.path.isfile(_ICON_PATH):
        with open(_ICON_PATH, "rb") as _icf:
            _icon_bytes = _icf.read()
        if "IconSVG" not in _hda_def.sections():
            _hda_def.addSection("IconSVG", _icon_bytes)
        else:
            _hda_def.sections()["IconSVG"].setContents(_icon_bytes)
        _hda_def.setIcon("opdef:.?IconSVG")
except Exception:
    pass  # icon is cosmetic — never fail the build over it

_hda_def.save(_HDA_PATH)

# ── 5. Install and clean up ───────────────────────────────────────────────────
hou.hda.installFile(_HDA_PATH, oplibraries_file=None, change_oplibraries_file=False)
try:
    _asset.destroy()
except Exception:
    pass

result = {{"ok": True, "path": _HDA_PATH, "node_type": _NODE_NAME}}
'''


def build_hda(hda_path: str) -> dict:
    """Build the FLUX Lighting HDA in the running Houdini instance.

    Returns {"ok": True, "path": hda_path} or {"ok": False, "error": "..."}.
    """
    code = _build_code(hda_path)
    log.info("Building FLUX Lighting HDA → %s", hda_path)
    resp = houdini_client.run(code)
    if resp.get("ok"):
        log.info("HDA built successfully: %s", hda_path)
    else:
        log.error("HDA build failed: %s", resp.get("error"))
    return resp
