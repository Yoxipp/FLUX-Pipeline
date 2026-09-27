# test_launch_frame_range.py - an empty Maya / Houdini launched from FLUX starts on 1001-1050.

from __future__ import annotations

import unittest
from unittest import mock

from features.launcher import launcher_core as lc


class LaunchFrameRangeTests(unittest.TestCase):
    def _launch(self, dcc, scene=None):
        with mock.patch.object(lc, "_resolve_exe", return_value=r"C:\DCC\app.exe"), \
             mock.patch.object(lc, "_child_env", return_value={}), \
             mock.patch.object(lc.os, "name", "nt"), \
             mock.patch.object(lc.subprocess, "Popen") as popen:
            self.assertTrue(lc.launch_dcc(dcc, scene))
        return popen.call_args.args[0], popen.call_args.kwargs["env"]

    def test_startup_scripts_are_shipped(self):
        for args in lc._FRAME_RANGE_ARGS.values():
            self.assertTrue(lc.Path(args[-1]).is_file(), args[-1])

    def test_empty_maya_runs_the_mel_script(self):
        cmd, env = self._launch("maya")
        self.assertIn('"-script"', cmd)
        self.assertIn("flux_frame_range.mel", cmd)
        self.assertEqual((env["FLUX_FRAME_START"], env["FLUX_FRAME_END"]), ("1001", "1050"))

    def test_empty_houdini_runs_the_cmd_script(self):
        cmd, env = self._launch("Houdini")
        self.assertIn("flux_frame_range.cmd", cmd)
        self.assertEqual(env["FLUX_FRAME_START"], "1001")

    def test_scene_keeps_its_own_range(self):
        cmd, env = self._launch("maya", r"D:\prod\render.ma")
        self.assertEqual(cmd, r'start "" "C:\DCC\app.exe" "D:\prod\render.ma"')
        self.assertNotIn("FLUX_FRAME_START", env)

    def test_other_dcc_is_untouched(self):
        cmd, env = self._launch("nuke")
        self.assertEqual(cmd, r'start "" "C:\DCC\app.exe"')
        self.assertNotIn("FLUX_FRAME_START", env)


if __name__ == "__main__":
    unittest.main()
