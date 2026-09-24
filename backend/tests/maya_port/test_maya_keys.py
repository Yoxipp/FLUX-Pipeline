# U1: the animated export range comes from the keys (driven keys ignored), else the
# timeline. maya.cmds is faked: only the range logic is tested here.

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dcc.maya import maya_keys as mk


class FakeCmds:
    """Two rig controls under |rig, a driven key on a third node, a prop elsewhere."""

    types = {"ctl_a_tx": "animCurveTL", "ctl_b_ry": "animCurveTA",
             "sdk_ry": "animCurveUA", "prop_tx": "animCurveTL"}
    keys = {"ctl_a_tx": [1001.0, 1040.0], "ctl_b_ry": [995.5, 1020.0],
            "sdk_ry": [0.0, 5000.0], "prop_tx": [1.0, 2000.0]}
    feeds = {"|rig|ctl_a": ["ctl_a_tx"], "|rig|ctl_b": ["ctl_b_ry", "sdk_ry"], "|prop": ["prop_tx"]}

    def __init__(self, selection: list[str]) -> None:
        self.selection = selection

    def ls(self, nodes=None, selection=False, long=False, type=None):  # noqa: A002
        if selection:
            return list(self.selection)
        if type is not None:
            return [c for c, t in self.types.items() if t in type]
        return list(nodes or [])

    def listRelatives(self, node, allDescendents=False, fullPath=False):  # noqa: N802, N803
        return [n for n in self.feeds if n.startswith(node + "|")]

    def listConnections(self, node, **_kw):  # noqa: N802
        return self.feeds.get(node, [])

    def nodeType(self, node):  # noqa: N802
        return self.types[node]

    def keyframe(self, curves, query=True, timeChange=True):  # noqa: N803
        return [t for c in curves for t in self.keys[c]]

    def playbackOptions(self, query=True, minTime=False, maxTime=False):  # noqa: N803
        return 1.0 if minTime else 120.0


class MayaKeys(unittest.TestCase):
    def test_key_range_rounds_outward(self) -> None:
        self.assertEqual(mk.key_range([995.5, 1040.2]), (995, 1041))
        self.assertIsNone(mk.key_range([]))

    def test_selection_uses_its_hierarchy_without_driven_keys(self) -> None:
        with mock.patch.object(mk, "cmds", FakeCmds(["|rig"])):
            r = mk.anim_range("selection")
        self.assertEqual((r["start"], r["end"], r["source"], r["curves"]), (995, 1040, "keys", 2))

    def test_scene_takes_every_time_curve(self) -> None:
        with mock.patch.object(mk, "cmds", FakeCmds([])):
            r = mk.anim_range("scene")
        self.assertEqual((r["start"], r["end"]), (1, 2000))

    def test_empty_selection_falls_back_to_scene(self) -> None:
        with mock.patch.object(mk, "cmds", FakeCmds([])):
            self.assertEqual(mk.anim_range("selection")["end"], 2000)

    def test_no_key_uses_the_timeline(self) -> None:
        fake = FakeCmds([])
        fake.types = {}
        with mock.patch.object(mk, "cmds", fake):
            r = mk.anim_range("scene")
        self.assertEqual((r["start"], r["end"], r["source"]), (1, 120, "timeline"))

    def test_run_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as d, mock.patch.object(mk, "cmds", FakeCmds(["|rig"])):
            out = Path(d) / "r.json"
            mk.run_anim_range("selection", str(out))
            self.assertEqual(json.loads(out.read_text())["start"], 995)


if __name__ == "__main__":
    unittest.main()
