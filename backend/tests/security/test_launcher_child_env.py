# test_launcher_child_env.py — env handed to a launched DCC must not leak FLUX's Python.
#
# Regression 2026-09-17: Houdini 22 launched from a dev FLUX inherited PYTHONUSERBASE
# (Microsoft Store Python), loaded the pip usd-core pxr from that user site and every
# LopNode.stage() raised RuntimeError.

from __future__ import annotations

import os
import unittest
from unittest import mock

from features.launcher import launcher_core


class ChildEnv(unittest.TestCase):
    def test_python_runtime_vars_are_removed(self):
        fake = {
            "PYTHONUSERBASE": r"C:\Users\x\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.13\LocalCache\local-packages",
            "PYTHONHOME": r"C:\py", "PYTHONPATH": r"C:\lib", "_MEIPASS": r"C:\tmp",
            "FLUX_PORT": "8765", "PATH": r"C:\Windows",
        }
        with mock.patch.dict(os.environ, fake, clear=True):
            env = launcher_core._child_env()
        for var in ("PYTHONUSERBASE", "PYTHONHOME", "PYTHONPATH", "_MEIPASS"):
            self.assertNotIn(var, env)
        self.assertEqual(env["FLUX_PORT"], "8765")
        self.assertEqual(env["PATH"], r"C:\Windows")


if __name__ == "__main__":
    unittest.main()
