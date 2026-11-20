"""
FLUX Work: build the work template scenes (ADR 0051, ADR 0090: one work = one .hip).

Run with hython (licence needed, FLUX HDAs installed in the user prefs otls by the
Shelf Manager), never inside the FLUX backend:

    hython backend/dcc/houdini/work_template_build.py [out_dir]

Writes into *out_dir* (default ``backend/resources/scenes/houdini/work``):

* ``RENDER.hip``      the maintainer's sequence render scene (``flux_template_sequence_render.hip``)
                      with a FLUX Work LOP in ``/stage``;
* ``DEFAULT_SOP.hip`` ``/obj/WORK`` geo: FLUX Work SOP, ``IN_ANIM`` -> ``OUT_WORK``;
* ``DEFAULT_LOP.hip`` ``/stage``: FLUX Work LOP and ``OUT_WORK``.

The FLUX Work context stays empty: FLUX copies a template into ``w000`` and the Work
fills it from the task's manifest when the scene opens. The extension of the outputs
is .hip (a Commercial licence); rerun when the render scene or the defaults change.
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCENES = os.path.normpath(os.path.join(HERE, "..", "..", "resources", "scenes", "houdini"))
RENDER_SOURCE = os.path.join(SCENES, "flux_template_sequence_render.hip")
WORK_NODE = "FLUX_WORK"


def _work_node(parent, category: str):
    import hou

    cat = hou.sopNodeTypeCategory() if category == "Sop" else hou.lopNodeTypeCategory()
    if hou.nodeType(cat, "flux_work") is None:
        raise RuntimeError("HDA flux_work (%s) absente : installe les HDA FLUX (Shelf Manager)" % category)
    for node in parent.children():
        if node.type().name() == "flux_work":
            return node
    return parent.createNode("flux_work", WORK_NODE)


def _note(parent, text: str, near) -> None:
    import hou

    note = parent.createStickyNote("flux_template_note")
    note.setText(text)
    note.setPosition(near.position() + hou.Vector2(3, 0))


def build_render(out_dir: str) -> dict:
    import hou

    hou.hipFile.load(RENDER_SOURCE, suppress_save_prompt=True, ignore_load_warnings=True)
    stage = hou.node("/stage")
    if stage is None:
        raise RuntimeError("/stage absent de %s" % RENDER_SOURCE)
    work = _work_node(stage, "Lop")
    top = min((n.position() for n in stage.children() if n != work),
              key=lambda p: (-p[1], p[0]), default=hou.Vector2(0, 0))
    work.setPosition(top + hou.Vector2(-4, 1.5))
    return _save(os.path.join(out_dir, "RENDER.hip"))


def build_default_sop(out_dir: str) -> dict:
    import hou

    hou.hipFile.clear(suppress_save_prompt=True)
    geo = hou.node("/obj").createNode("geo", "WORK")
    for child in geo.children():
        child.destroy()
    work = _work_node(geo, "Sop")
    merge = geo.createNode("object_merge", "IN_ANIM")
    merge.parm("xformtype").set(1)              # into this object
    out = geo.createNode("null", "OUT_WORK")
    out.setInput(0, merge)
    out.setDisplayFlag(True)
    out.setRenderFlag(True)
    geo.layoutChildren()
    _note(geo, "Template FLUX : IN_ANIM = objet de l'anim du shot, travail entre IN et OUT.", work)
    return _save(os.path.join(out_dir, "DEFAULT_SOP.hip"))


def build_default_lop(out_dir: str) -> dict:
    import hou

    hou.hipFile.clear(suppress_save_prompt=True)
    stage = hou.node("/stage")
    work = _work_node(stage, "Lop")
    out = stage.createNode("null", "OUT_WORK")
    out.setDisplayFlag(True)
    stage.layoutChildren()
    _note(stage, "Template FLUX : pose un FLUX Shot Import en tete, travail jusqu'a OUT_WORK.", work)
    return _save(os.path.join(out_dir, "DEFAULT_LOP.hip"))


def _save(path: str) -> dict:
    import hou

    os.makedirs(os.path.dirname(path), exist_ok=True)
    hou.hipFile.save(path)
    works = [n.path() for n in hou.node("/").allSubChildren() if n.type().name() == "flux_work"]
    return {"out": path.replace("\\", "/"), "size": os.path.getsize(path), "flux_work": works}


def build(out_dir: str) -> dict:
    return {"ok": True, "render": build_render(out_dir), "default_sop": build_default_sop(out_dir),
            "default_lop": build_default_lop(out_dir)}


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(SCENES, "work")
    print(json.dumps(build(target), indent=1))
