# P6c refactor (2026-10-23): launch_exe extracted from launch_dcc (an extension bridge
# soft starts the same way: detached, cleaned env); launch_dcc behaves as before.

from __future__ import annotations

import os
import unittest
from unittest import mock

from features.launcher import launcher_core as lc


class LaunchExe(unittest.TestCase):
    def test_launch_exe_detached_with_a_clean_env(self) -> None:
        with mock.patch.object(lc.subprocess, "Popen") as popen, \
             mock.patch.dict(os.environ, {"PYTHONPATH": "/leak"}):
            self.assertTrue(lc.launch_exe("/apps/max/3dsmax", "/p/a.max"))
        args, kwargs = popen.call_args
        self.assertNotIn("PYTHONPATH", kwargs["env"])
        if os.name != "nt":
            self.assertEqual(args[0], ["/apps/max/3dsmax", "/p/a.max"])
            self.assertTrue(kwargs["start_new_session"])

    def test_launch_failure_is_false(self) -> None:
        with mock.patch.object(lc.subprocess, "Popen", side_effect=OSError("no")):
            self.assertFalse(lc.launch_exe("/nope"))

    def test_launch_dcc_goes_through_launch_exe(self) -> None:
        with mock.patch.object(lc, "_resolve_exe", return_value="/apps/maya/maya"), \
             mock.patch.object(lc, "launch_exe", return_value=True) as launch:
            self.assertTrue(lc.launch_dcc("maya"))
        kwargs = launch.call_args.kwargs
        self.assertEqual(launch.call_args.args[:2], ("/apps/maya/maya", None))
        self.assertEqual(kwargs["env"]["FLUX_FRAME_START"], str(lc.DEFAULT_FRAME_START))
        self.assertTrue(kwargs["extra"])


if __name__ == "__main__":
    unittest.main()
