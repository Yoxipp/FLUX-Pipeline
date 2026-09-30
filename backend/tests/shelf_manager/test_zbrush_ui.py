# test_zbrush_ui.py - the ZBrush FLUX UI installs over the artist's UI and gives it back.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from features.shelf_manager import shelf_core, zbrush_ui


class ZBrushUi(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "Maxon ZBrush 2026_ABCD"
        (self.root / "ZStartup").mkdir(parents=True)
        self.src = Path(tmp.name) / "flux_ui_zbrush.cfg"
        self.src.write_bytes(b"FLUX-UI")
        for p in (mock.patch.object(zbrush_ui, "_roots", return_value=[self.root]),
                  mock.patch.object(zbrush_ui, "UI_SOURCE", self.src),
                  mock.patch("dcc.zbrush.autostart.install", return_value={"success": True})):
            p.start()
            self.addCleanup(p.stop)
        self.cfg = self.root / "ZStartup" / "CustomUserInterface2026.cfg"

    def test_shipped_ui_exists(self):
        self.assertTrue(zbrush_ui.UI_SOURCE.name == "flux_ui_zbrush.cfg")
        self.assertTrue((Path(shelf_core.__file__).resolve().parents[2] / "resources" / "shelves"
                         / "zbrush" / "flux_ui_zbrush.cfg").is_file())

    def test_install_keeps_the_artist_ui_and_remove_restores_it(self):
        self.cfg.write_bytes(b"MY-UI")
        self.assertEqual(shelf_core.get_installed_versions("ZBrush"), ["2026"])
        self.assertFalse(shelf_core.is_shelf_installed("ZBrush", "2026"))
        ok, msg = shelf_core.install_shelf("ZBrush", "2026")
        self.assertTrue(ok, msg)
        self.assertEqual(self.cfg.read_bytes(), b"FLUX-UI")
        self.assertTrue(shelf_core.is_shelf_installed("ZBrush", "2026"))
        shelf_core.install_shelf("ZBrush", "2026")          # reinstall keeps the first backup
        ok, msg = shelf_core.remove_shelf("ZBrush", "2026")
        self.assertTrue(ok, msg)
        self.assertEqual(self.cfg.read_bytes(), b"MY-UI")

    def test_fresh_install_then_remove_leaves_default_ui(self):
        ok, _ = shelf_core.install_shelf("ZBrush", "2026")
        self.assertTrue(ok)
        ok, _ = shelf_core.remove_shelf("ZBrush", "2026")
        self.assertTrue(ok)
        self.assertFalse(self.cfg.exists())


if __name__ == "__main__":
    unittest.main()
