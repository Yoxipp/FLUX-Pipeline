# test_photoshop_export.py — Photoshop publish (V6 B6), no Photoshop needed.
#
# The format -> save-options mapping is pure and tested here; the COM save is
# isolated (_save_active_document) and mocked so the orchestration is verified
# without Photoshop or the library installed.

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from dcc.photoshop import photoshop_export as pe


class SaveOptionsMapping(unittest.TestCase):
    def test_known_formats(self):
        self.assertEqual(pe.save_options_for_ext(".psd")[0], "PhotoshopSaveOptions")
        self.assertEqual(pe.save_options_for_ext(".png")[0], "PNGSaveOptions")
        self.assertEqual(pe.save_options_for_ext(".jpg")[0], "JPEGSaveOptions")
        self.assertEqual(pe.save_options_for_ext(".tif")[0], "TiffSaveOptions")

    def test_extension_normalised(self):
        self.assertEqual(pe.save_options_for_ext("PNG")[0], "PNGSaveOptions")

    def test_options_merged(self):
        _, kwargs = pe.save_options_for_ext(".jpg", {"quality": 8})
        self.assertEqual(kwargs["quality"], 8)

    def test_unsupported_raises(self):
        with self.assertRaises(ValueError):
            pe.save_options_for_ext(".exr")

    def test_supported_list(self):
        exts = pe.supported_extensions()
        self.assertIn(".psd", exts)
        self.assertIn(".png", exts)


class PublishPhotoshop(unittest.TestCase):
    def _patches(self, save_result):
        return [
            mock.patch("core.paths.get_project_path", return_value=Path("/proj")),
            mock.patch("pathlib.Path.exists", return_value=True),
            mock.patch("features.publisher.publish_core.resolve_publish_path",
                       return_value=Path("/proj/dest")),
            mock.patch("features.publisher.publish_layout.flat_last_path",
                       return_value=Path("/proj/dest/X_TEX_HERO_null_LAST.png")),
            mock.patch("features.publisher.publish_layout.archive_flat_last", return_value=1),
            mock.patch("features.publisher.version_resolver.get_next_version", return_value=2),
            mock.patch("features.folder_manager.naming_validator.get_base_name",
                       return_value="X_TEX_HERO_null"),
            mock.patch("features.activity.activity_writer.log_publish"),
            mock.patch("features.publisher.modif_log.append_log"),
            mock.patch.object(pe, "_save_active_document", return_value=save_result),
        ]

    def test_publish_ok(self):
        ctx = self._patches({"ok": True, "version": "25.0"})
        for p in ctx:
            p.start()
        try:
            out = pe.publish_photoshop("PROJ", "X_TEX_HERO_null", ".png", {}, "d", "adam")
        finally:
            for p in ctx:
                p.stop()
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["path"], str(Path("/proj/dest/X_TEX_HERO_null_LAST.png")))
        self.assertEqual(out["version"], 2)   # archived 1 -> effective 2

    def test_unsupported_format_fails_fast(self):
        with mock.patch("core.paths.get_project_path", return_value=Path("/proj")):
            out = pe.publish_photoshop("PROJ", "X", ".exr")
        self.assertFalse(out["ok"])

    def test_save_failure_propagates(self):
        ctx = self._patches({"ok": False, "error": "Photoshop not running"})
        for p in ctx:
            p.start()
        try:
            out = pe.publish_photoshop("PROJ", "X_TEX_HERO_null", ".png")
        finally:
            for p in ctx:
                p.stop()
        self.assertFalse(out["ok"])
        self.assertIn("not running", out["error"])


if __name__ == "__main__":
    unittest.main()
