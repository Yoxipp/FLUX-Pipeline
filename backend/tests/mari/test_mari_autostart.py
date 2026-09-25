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

    def test_install_writes_every_folder_mari_may_read(self):
        # 2026-09-25: bridge installed, Mari open, still orange. One copy in the
        # OneDrive Documents (or the first MARI_SCRIPT_PATH entry) is not always read.
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            env = {"MARI_SCRIPT_PATH": str(tmp / "studio")}
            with mock.patch.dict(os.environ, env), \
                    mock.patch.object(autostart, "_documents_dir", return_value=tmp / "OneDrive" / "Documents"), \
                    mock.patch.object(Path, "home", return_value=tmp / "home"):
                os.environ.pop("FLUX_MARI_SCRIPTS_DIR", None)
                res = autostart.install()
                self.assertTrue(res["success"], res)
                for d in (tmp / "studio", tmp / "OneDrive" / "Documents" / "Mari" / "Scripts",
                          tmp / "home" / "Documents" / "Mari" / "Scripts", tmp / "home" / "Mari" / "Scripts"):
                    self.assertTrue((d / "flux_mari_bridge.py").is_file(), d)
                self.assertTrue(autostart.is_installed())
                self.assertIn("Bridge installe dans", autostart.diagnose())
                self.assertTrue(autostart.uninstall()["success"])
                self.assertFalse(autostart.is_installed())

    def test_diagnose_quotes_the_bridge_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            logf = Path(tmp) / "flux_mari_bridge.log"
            logf.write_text("a\nMari bridge bind failed on 127.0.0.1:7070: in use\n")
            with mock.patch.object(autostart, "_BRIDGE_LOG", logf), \
                    mock.patch.dict(os.environ, {"FLUX_MARI_SCRIPTS_DIR": str(Path(tmp) / "s")}):
                self.assertIn("bind failed", autostart.diagnose())


class PainterPluginsDir(unittest.TestCase):
    def test_follows_redirected_documents(self):
        from dcc.substance_painter import autostart as sp
        os.environ.pop("FLUX_SP_PLUGINS_DIR", None)
        with mock.patch.object(sp, "documents_dir", return_value=Path("D:/Docs")):
            self.assertEqual(
                sp._plugins_dir(),
                Path("D:/Docs/Adobe/Adobe Substance 3D Painter/python/startup"),
            )

    def test_install_moves_old_plugins_copy_to_startup(self):
        # python/plugins only runs once ticked in Painter: the bridge now lives in startup.
        import tempfile

        from dcc.substance_painter import autostart as sp
        os.environ.pop("FLUX_SP_PLUGINS_DIR", None)
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(sp, "documents_dir", return_value=Path(d)):
            old = Path(d, "Adobe", "Adobe Substance 3D Painter", "python", "plugins", sp._PLUGIN_NAME)
            old.parent.mkdir(parents=True)
            old.write_text("# old", encoding="utf-8")
            self.assertTrue(sp.install()["success"])
            self.assertTrue(sp.is_installed())
            self.assertEqual(sp.get_startup_file().parent.name, "startup")
            self.assertFalse(old.exists())


if __name__ == "__main__":
    unittest.main()
