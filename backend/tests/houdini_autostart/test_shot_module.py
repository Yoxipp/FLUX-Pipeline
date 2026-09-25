# FLUX Shot served module: FLUX offline keeps the loaded stage, a version of another
# shot falls back to LAST, opening a scene never touches the timeline.

from __future__ import annotations

import unittest

from dcc.houdini.hda import flux_shot_switch_hda
from tests.houdini_autostart.test_importer_component import _Node

SHOT = {"seq": "SEQ001", "shot": "SHOT010", "last": "/p/SEQ001_SHOT010_LAST.usda",
        "versions": ["v001"], "files": {"v001": "/p/v001.usda"}, "range": [1001, 1100], "fps": 24.0}


class _Tuple:
    def __init__(self, node, name):
        self.node, self.name = node, name

    def set(self, values):
        self.node.parm(self.name + "x").set(values[0])
        self.node.parm(self.name + "y").set(values[1])


class _ShotNode(_Node):
    def parmTuple(self, name):  # noqa: N802 - Houdini API name
        return _Tuple(self, name)


class ShotModule(unittest.TestCase):
    def setUp(self) -> None:
        self.ns: dict = {}
        exec(flux_shot_switch_hda.MODULE_FUNCTIONS, self.ns)
        self.answer = {"ok": True, "shots": [SHOT]}
        self.ns["_get"] = lambda path, **kw: self.answer
        self.ns["_reload"] = lambda node: None
        self.applied = []
        self.ns["apply_frame_range"] = lambda node: self.applied.append(node)
        self.node = _ShotNode(project="PROJ", seq="SEQ001", shot="SHOT010", version="v007",
                              resolved_path="/p/old.usda", status_msg="", frame_rangex=1, frame_rangey=1,
                              fps=24, follow_range=1, camera_auto=1, camera="")

    def test_offline_keeps_the_stage(self) -> None:
        self.answer = {"ok": False, "_offline": True}
        self.ns["resolve_path"](self.node)
        self.assertEqual(self.node.evalParm("resolved_path"), "/p/old.usda")
        self.assertIn("FLUX injoignable", self.node.evalParm("status_msg"))

    def test_opening_a_scene_never_moves_the_timeline(self) -> None:
        self.ns["on_loaded"](self.node)
        self.assertEqual(self.applied, [])
        self.assertEqual(self.node.evalParm("version"), "LAST")         # v007 unknown for this shot
        self.assertEqual(self.node.evalParm("resolved_path"), "/p/SEQ001_SHOT010_LAST.usda")
        self.assertEqual((self.node.evalParm("frame_rangex"), self.node.evalParm("frame_rangey")), (1001, 1100))


if __name__ == "__main__":
    unittest.main()
