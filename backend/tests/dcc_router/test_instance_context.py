# test_instance_context.py - scene + selection of each open Maya / Houdini (2026-09-26).

from __future__ import annotations

import unittest
from unittest import mock

from routers import dcc as dcc_router


class InstanceContext(unittest.TestCase):
    def test_maya_scene_then_selection(self):
        with mock.patch("dcc.maya.maya_connection.send_command_direct",
                        return_value="C:/p/scene_v001.ma\n|DINGO_01\npCube1\n\x00") as send:
            ctx = dcc_router.instance_context("Maya", 7002)
        self.assertEqual(ctx, {"scene": "C:/p/scene_v001.ma", "selection": ["|DINGO_01", "pCube1"]})
        self.assertEqual(send.call_args.kwargs["port"], 7002)

    def test_maya_untitled_nothing_selected(self):
        with mock.patch("dcc.maya.maya_connection.send_command_direct", return_value=""):
            self.assertEqual(dcc_router.instance_context("Maya", 7001), {"scene": "", "selection": []})

    def test_houdini_selected_nodes(self):
        with mock.patch("dcc.houdini.client.HoudiniClient._get",
                        return_value={"hip_file": "D:/a.hip", "selected_nodes": ["/out/rop1", "/obj/geo1"]}):
            self.assertEqual(dcc_router.instance_context("Houdini", 48885),
                             {"scene": "D:/a.hip", "selection": ["/out/rop1", "/obj/geo1"]})

    def test_unreachable_instance_is_empty(self):
        with mock.patch("dcc.houdini.client.HoudiniClient._get", side_effect=OSError("refused")):
            self.assertEqual(dcc_router.instance_context("Houdini", 48886), {"scene": "", "selection": []})


if __name__ == "__main__":
    unittest.main()
