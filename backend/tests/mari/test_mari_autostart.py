# test_mari_autostart.py - Mari bridge lands in Mari's real user scripts dir.

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dcc.mari import autostart


class MariScriptsDir(unittest.TestCase):
    def test_default_is_documents_mari_scripts(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FLUX_MARI_SCRIPTS_DIR", None)
            os.environ.pop("MARI_SCRIPT_PATH", None)
            with mock.patch.object(autostart, "_documents_dir", return_value=Path("D:/Docs")):
                self.assertEqual(autostart._scripts_dir(), Path("D:/Docs/Mari/Scripts"))

    def test_mari_script_path_env_wins(self):
        env = {"MARI_SCRIPT_PATH": f"E:/studio/mari{os.pathsep}F:/other"}
        with mock.patch.dict(os.environ, env):
            os.environ.pop("FLUX_MARI_SCRIPTS_DIR", None)
            self.assertEqual(autostart._scripts_dir(), Path("E:/studio/mari"))

    def test_install_removes_legacy_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            legacy = tmp / "legacy"
            legacy.mkdir()
            (legacy / "flux_mari_bridge.py").write_text("old")
            with mock.patch.dict(os.environ, {"FLUX_MARI_SCRIPTS_DIR": str(tmp / "scripts")}), \
                    mock.patch.object(autostart, "_LEGACY_DIR", legacy):
                res = autostart.install()
                self.assertTrue(res["success"], res)
                self.assertTrue(autostart.is_installed())
                self.assertFalse((legacy / "flux_mari_bridge.py").exists())
                self.assertTrue(autostart.uninstall()["success"])
                self.assertFalse(autostart.is_installed())


class PainterPluginsDir(unittest.TestCase):
    def test_follows_redirected_documents(self):
        from dcc.substance_painter import autostart as sp
        os.environ.pop("FLUX_SP_PLUGINS_DIR", None)
        with mock.patch.object(sp, "documents_dir", return_value=Path("D:/Docs")):
            self.assertEqual(
                sp._plugins_dir(),
                Path("D:/Docs/Adobe/Adobe Substance 3D Painter/python/plugins"),
            )


if __name__ == "__main__":
    unittest.main()
