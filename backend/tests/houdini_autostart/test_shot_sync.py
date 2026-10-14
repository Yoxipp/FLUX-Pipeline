# P0 Houdini Work (2026-10-09): a Production edit that regenerates a shot stage is pushed
# to the open Houdini; FLUX Shot Import follows the new range and reloads its layer, a
# pinned version is left alone, the timeline only moves when it showed this shot.

from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

from dcc.houdini import shot_sync
from dcc.houdini.hda import flux_shot_switch_hda


class _Parm:
    def __init__(self, value):
        self.value = value

    def eval(self):
        return self.value

    def evalAsString(self):
        return str(self.value)

    def set(self, value):
        self.value = value


class _Tuple:
    def __init__(self, node, name):
        self.node, self.name = node, name

    def set(self, values):
        self.node.parm(self.name + "x").set(values[0])
        self.node.parm(self.name + "y").set(values[1])


class _Node:
    def __init__(self, **values):
        self.parms = {k: _Parm(v) for k, v in values.items()}

    def parm(self, name):
        return self.parms.setdefault(name, _Parm(""))

    def parmTuple(self, name):
        return _Tuple(self, name)

    def evalParm(self, name):
        return self.parm(name).eval()


def _fake_hou(shown):
    hou = types.ModuleType("hou")
    state = {"range": shown, "frame": None}
    hou.fps = lambda: 24.0
    hou.setFps = lambda v: None
    hou.setFrame = lambda f: state.__setitem__("frame", f)
    hou.playbar = types.SimpleNamespace(
        frameRange=lambda: tuple(float(v) for v in state["range"]),
        setFrameRange=lambda a, b: state.__setitem__("range", (a, b)),
        setPlaybackRange=lambda a, b: None)
    return hou, state


SHOT = {"seq": "SEQ010", "shot": "SH020", "last": "C:\\p\\SEQ010_SH020_LAST.usda",
        "files": {}, "range": [1001, 1080], "fps": 24.0}


class RefreshFromFlux(unittest.TestCase):
    def setUp(self) -> None:
        self.ns: dict = {}
        exec(flux_shot_switch_hda.MODULE_FUNCTIONS, self.ns)
        self.reloaded: list = []
        self.ns["_get"] = lambda path, **kw: {"shots": [SHOT]}
        self.ns["_reload"] = lambda node: self.reloaded.append(node)
        self.node = _Node(project="PROJ", seq="SEQ010", shot="SH020", version="LAST",
                          frame_rangex=1001, frame_rangey=1050, fps=24.0, follow_range=1,
                          resolved_path="old", status_msg="")

    def _run(self, shown, changed=(("SEQ010", "SH020"),), project="PROJ"):
        hou, state = _fake_hou(shown)
        with mock.patch.dict(sys.modules, {"hou": hou}):
            res = self.ns["refresh_from_flux"](self.node, project, [list(c) for c in changed])
        return res, state

    def test_new_range_layer_reload_and_timeline_that_showed_the_shot(self) -> None:
        res, state = self._run(shown=(1001, 1050))
        self.assertEqual(res, "timeline")
        self.assertEqual((self.node.evalParm("frame_rangex"), self.node.evalParm("frame_rangey")), (1001, 1080))
        self.assertEqual(self.node.evalParm("resolved_path"), "C:/p/SEQ010_SH020_LAST.usda")
        self.assertEqual(self.reloaded, [self.node])
        self.assertEqual(state["range"], (1001, 1080))
        self.assertIn("1001-1080", self.node.evalParm("status_msg"))

    def test_timeline_of_another_shot_is_not_moved(self) -> None:
        res, state = self._run(shown=(1, 240))
        self.assertEqual(res, "updated")
        self.assertEqual(state["range"], (1, 240))
        self.assertEqual(self.node.evalParm("frame_rangey"), 1080)

    def test_pinned_version_is_left_alone(self) -> None:
        self.node.parm("version").set("v003")
        res, _ = self._run(shown=(1001, 1050))
        self.assertEqual(res, "pinned")
        self.assertEqual(self.reloaded, [])
        self.assertEqual(self.node.evalParm("frame_rangey"), 1050)

    def test_other_shot_or_project_is_not_concerned(self) -> None:
        self.assertIsNone(self._run(shown=(1001, 1050), changed=(("SEQ010", "SH030"),))[0])
        self.assertIsNone(self._run(shown=(1001, 1050), project="OTHER")[0])
        self.assertEqual(self.reloaded, [])

    def test_case_of_the_shot_name_does_not_matter(self) -> None:
        self.assertEqual(self._run(shown=(1, 2), changed=(("seq010", "sh020"),))[0], "updated")

    def test_flux_offline_keeps_the_stage(self) -> None:
        self.ns["_get"] = lambda path, **kw: {"ok": False, "_offline": True}
        res, _ = self._run(shown=(1001, 1050))
        self.assertEqual(res, "offline")
        self.assertEqual(self.reloaded, [])


class Notifier(unittest.TestCase):
    def test_code_compiles_and_carries_the_shots(self) -> None:
        code = shot_sync.build_refresh_code("PROJ", [("SEQ010", "SH020")])
        compile(code, "<refresh>", "exec")
        self.assertIn("[['SEQ010', 'SH020']]", code)
        self.assertIn("refresh_from_flux", code)
        # A render Work loaded on the sequence follows too (new shots -> blocks).
        self.assertIn("follow_timeline_from_flux", code)
        self.assertIn('nodeTypes().get("flux_work")', code)

    def test_work_and_sequence_modules_define_the_hooks(self) -> None:
        from dcc.houdini.hda import flux_sequence_hda, flux_work_hda
        self.assertIn("def follow_timeline_from_flux(node, project, changed):", flux_work_hda.MODULE_FUNCTIONS)
        self.assertIn("def name_new_blocks(stage, added", flux_sequence_hda.MODULE_FUNCTIONS)
        compile(flux_sequence_hda.MODULE_FUNCTIONS, "<flux_sequence>", "exec")
        compile(flux_work_hda.MODULE_FUNCTIONS, "<flux_work>", "exec")

    def test_every_connected_houdini_is_asked_and_errors_do_not_stop(self) -> None:
        calls = []

        class _Client:
            def __init__(self, port):
                self.port = port

            def run(self, code, timeout):
                calls.append((self.port, timeout))
                if self.port == 48885:
                    raise OSError("refused")
                return {"ok": True, "result": [["/stage/flux_shot1", "updated"]]}

        out = shot_sync.notify_shot_stages("PROJ", [("SEQ010", "SH020")],
                                           ports=lambda: [48884, 48885], client_factory=_Client)
        self.assertEqual([c[0] for c in calls], [48884, 48885])
        self.assertTrue(out[48884]["ok"])
        self.assertFalse(out[48885]["ok"])
        self.assertLessEqual(calls[0][1], 60)

    def test_no_changed_shot_scans_nothing(self) -> None:
        scanned = []
        out = shot_sync.notify_shot_stages("PROJ", [], ports=lambda: scanned.append(1) or [])
        self.assertEqual((out, scanned), ({}, []))
        self.assertIsNone(shot_sync.notify_shot_stages_async("PROJ", []))


if __name__ == "__main__":
    unittest.main()
