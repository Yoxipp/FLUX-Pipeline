# test_launcher_quoting.py — S4: a scene path cannot inject shell commands.

from __future__ import annotations

import unittest
from unittest import mock

from features.launcher import launcher_core


class LauncherQuotingTests(unittest.TestCase):
    def _launch(self, scene):
        with mock.patch.object(launcher_core, "_resolve_exe", return_value=r"C:\Program Files\Maya\bin\maya.exe"), \
             mock.patch.object(launcher_core, "_child_env", return_value={}), \
             mock.patch.object(launcher_core.os, "name", "nt"), \
             mock.patch.object(launcher_core.subprocess, "Popen") as popen:
            ok = launcher_core.launch_dcc("Maya", scene)
        return ok, popen

    def test_normal_scene_is_quoted(self):
        ok, popen = self._launch(r"D:\prod\shot & co\scene.ma")
        self.assertTrue(ok)
        self.assertEqual(popen.call_args.args[0],
                         r'start "" "C:\Program Files\Maya\bin\maya.exe" "D:\prod\shot & co\scene.ma"')

    def test_quote_in_scene_is_refused(self):
        ok, popen = self._launch('x" & calc & "')
        self.assertFalse(ok)
        popen.assert_not_called()

    def test_percent_in_scene_is_refused(self):
        ok, popen = self._launch(r"C:\%COMSPEC%\scene.ma")
        self.assertFalse(ok)
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
