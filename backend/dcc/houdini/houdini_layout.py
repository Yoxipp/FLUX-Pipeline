# houdini_layout.py — read assembly placements from a Houdini LOP stage for
# features.usd_assembler.layout_publish (USD_ASSEMBLER_V2 section 10 point 3).
#
# Only local matrices travel back: the layout layer is authored by the backend, so
# Houdini writes nothing to disk. The stage is read with Houdini's own pxr.

from __future__ import annotations

import textwrap

from core.logger import get_logger
from dcc.houdini.client import houdini_client

log = get_logger(__name__)


def collect_layout(name: str) -> dict:
    """Local matrix of every instance ``<root>/<CLASS>/<INSTANCE>`` of assembly *name*.

    Stage = the selected LOP node, else the display node of the LOP network shown in
    the network editor, else of /stage. The assembly root is the prim named *name*
    with kind ``assembly`` (a Reference LOP puts it at ``/sets/<name>``).
    Returns {"ok", "result": {"placements": {"CLASS/INSTANCE": [16 floats]}, "node", "root"}}
    or {"ok": False, "error"}.
    """
    code = textwrap.dedent(f"""\
        import hou
        from pxr import Usd, UsdGeom
        _name = {name!r}
        _lop = [n for n in hou.selectedNodes() if isinstance(n, hou.LopNode)]
        _node = _lop[0] if _lop else None
        if _node is None:
            try:
                _pane = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
                _pwd = _pane.pwd() if _pane else None
            except Exception:
                _pwd = None
            for _net in (_pwd, hou.node("/stage")):
                if _net is not None and _net.childTypeCategory() == hou.lopNodeTypeCategory():
                    _node = _net.displayNode()
                    if _node is not None:
                        break
        if _node is None:
            raise RuntimeError("Aucun node LOP : selectionne le node LOP du layout (ou /stage avec un display flag).")
        _stage = _node.stage()
        _roots = [p for p in _stage.Traverse()
                  if p.GetName() == _name and Usd.ModelAPI(p).GetKind() == "assembly"]
        if not _roots:
            raise RuntimeError("Assembly " + _name + " absente du stage de " + _node.path()
                               + " : ouvre l'assembly dans /stage (Reference LOP) avant de publier le layout.")
        _root = _roots[0]
        _placements = {{}}
        for _group in _root.GetChildren():
            for _inst in _group.GetChildren():
                _m = UsdGeom.Xformable(_inst).GetLocalTransformation(Usd.TimeCode.Default())
                _placements[_group.GetName() + "/" + _inst.GetName()] = [_m[i][j] for i in range(4) for j in range(4)]
        result = {{"placements": _placements, "node": _node.path(), "root": _root.GetPath().pathString}}
    """)
    resp = houdini_client.run(code)
    if resp.get("ok"):
        r = resp.get("result") or {}
        log.info("Houdini layout %s: %d placements from %s (%s)",
                 name, len(r.get("placements") or {}), r.get("node"), r.get("root"))
    else:
        log.error("collect_layout (Houdini) failed: %s", resp.get("error"))
    return resp
