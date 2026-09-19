"""
FLUX - pieces shared by the Houdini HDA builders (V9-08, L8).

ICON_PATH   the FLUX logo embedded as the IconSVG section (Houdini 22 draws SVG, not PNG).
FINALIZE    end of a LOP builder script run inside Houdini: once ``_asset`` (the new HDA
            node), ``_PM_CODE`` (its PythonModule bootstrap), ``_ptg`` (parm interface),
            ``_ICON_PATH`` and ``_HDA_PATH`` exist, it writes the Python sections, the
            interface and the icon, saves and installs the .hda and deletes the build node.
"""

from __future__ import annotations

from pathlib import Path

ICON_PATH = str(Path(__file__).parents[3] / "resources" / "shelves" / "houdini" / "flux_hda.svg")

FINALIZE = '''
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
'''
