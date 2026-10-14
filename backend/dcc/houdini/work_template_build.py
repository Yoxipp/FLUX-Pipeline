"""
FLUX Work: turn a template scene (.hip) into a work template cpio (ADR 0051, E5).

Run with hython (licence needed), never inside the FLUX backend:

    hython backend/dcc/houdini/work_template_build.py <in.hip> <out.cpio> [network]

Everything in *network* (default ``/stage``: nodes, network boxes, sticky notes, dots)
is packed into a subnet the way a FLUX Work holds its content, absolute references to
``<network>/<node>`` are made relative (``../<node>``, the content lives one level
deeper in the Work subnet), then saved with flux_work_io (no embedded HDA definitions:
the FLUX HDAs come from the Shelf Manager). Rerun it when the template scene changes:

    hython backend/dcc/houdini/work_template_build.py \\
        backend/resources/scenes/houdini/flux_template_sequence_render.hip \\
        backend/resources/scenes/houdini/work/RENDER.cpio
"""

from __future__ import annotations

import json
import os
import sys


def _relative_refs(sub, network_path: str) -> int:
    """``/stage/NODE`` -> ``../NODE`` in string parms and expressions of the content."""
    import hou

    prefix = network_path.rstrip("/") + "/"
    changed = 0
    for node in sub.allSubChildren():
        for parm in node.parms():
            try:
                expr = parm.expression()
            except hou.OperationFailed:
                expr = None
            if expr is not None:
                if prefix in expr:
                    parm.setExpression(expr.replace(prefix, "../"), parm.expressionLanguage())
                    changed += 1
                continue
            if parm.parmTemplate().type() != hou.parmTemplateType.String:
                continue
            raw = parm.rawValue()
            if prefix in raw:
                parm.set(raw.replace(prefix, "../"))
                changed += 1
    return changed


def build(hip: str, out: str, network: str = "/stage") -> dict:
    import hou

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    from dcc.houdini.hda import flux_work_io as wio

    hou.hipFile.load(hip, suppress_save_prompt=True, ignore_load_warnings=True)
    net = hou.node(network)
    if net is None:
        raise RuntimeError("Reseau absent : %s" % network)
    items = wio.work_items(net)
    nodes = len(net.children())
    sub = net.createNode("subnet", "__flux_work_template__")
    wio.clear_work(sub)
    sub.copyItems(items, channel_reference_originals=False, relative_references=True)
    for item in items:
        try:
            item.destroy()
        except hou.ObjectWasDeleted:
            pass
    refs = _relative_refs(sub, network)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    saved = wio.save_work(sub, out, embed_hdas=False)
    return {"ok": True, "out": out, "nodes": nodes, "packed": len(sub.children()),
            "boxes": len(sub.networkBoxes()), "relative_refs": refs, "size": saved["size"],
            "node_types": [t["type"] for t in saved["node_types"]]}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    print(json.dumps(build(sys.argv[1], sys.argv[2], *(sys.argv[3:4] or [])), indent=1))
