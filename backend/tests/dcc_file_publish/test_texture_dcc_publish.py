# test_texture_dcc_publish.py — Substance Painter + Mari publish (V6 B2/B7).
#
# No app needed: the export-config + map-token helpers are pure; the bridge export,
# the ingest (publish_file) and the conform are mocked, so the orchestration is
# verified end to end without Painter/Mari.

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from dcc.substance_painter import client as sp_client
from dcc.substance_painter import substance_export as se
from dcc.mari import client as mari_client_mod
from dcc.mari import mari_export as me


class ExportConfigAndTokens(unittest.TestCase):
    def test_build_export_config(self):
        cfg = se.build_export_config("/tmp/out", "PBR Metallic Roughness", "png", "16")
        self.assertEqual(cfg["exportPath"], "/tmp/out")
        self.assertEqual(cfg["defaultExportPreset"], "PBR Metallic Roughness")
        self.assertEqual(cfg["exportParameters"][0]["parameters"]["fileFormat"], "png")
        self.assertEqual(cfg["exportParameters"][0]["parameters"]["bitDepth"], "16")

    def test_map_token_from_filename(self):
        self.assertEqual(se.map_token_from_filename("HeroBody_BaseColor.png"), "BASECOLOR")
        self.assertEqual(se.map_token_from_filename("HeroBody_Roughness.1001.exr"), "ROUGHNESS")


class PublishPainter(unittest.TestCase):
    def test_exports_then_ingests_each_map(self):
        maps = ["/tmp/x_BaseColor.png", "/tmp/x_Roughness.png"]
        with mock.patch("core.paths.get_project_path", return_value=Path("/proj")), \
             mock.patch("pathlib.Path.exists", return_value=True), \
             mock.patch.object(sp_client.substance_client, "export",
                               return_value={"ok": True, "files": maps}), \
             mock.patch("features.publisher.publish_core.publish_file",
                        side_effect=lambda src, *a, **k: Path("/proj/dest") / Path(src).name) as pf:
            out = se.publish_painter("PROJ", "CHAR", "TEX", "HERO", "null")
        self.assertTrue(out["ok"], out)
        self.assertEqual(len(out["published"]), 2)
        # each map ingested with a composed FLUX target name (map token uppercased)
        names = [k.kwargs.get("target_name") or k.args[5] for k in pf.call_args_list]
        self.assertIn("CHAR_TEX_HERO_BASECOLOR", names)
        self.assertIn("CHAR_TEX_HERO_ROUGHNESS", names)

    def test_export_failure(self):
        with mock.patch("core.paths.get_project_path", return_value=Path("/proj")), \
             mock.patch("pathlib.Path.exists", return_value=True), \
             mock.patch.object(sp_client.substance_client, "export",
                               return_value={"ok": False, "error": "Painter closed"}):
            out = se.publish_painter("PROJ", "CHAR", "TEX", "HERO")
        self.assertFalse(out["ok"])


class PublishMari(unittest.TestCase):
    def test_exports_then_ingests(self):
        chans = ["/tmp/g_Diffuse.tif", "/tmp/g_Bump.tif"]
        with mock.patch("core.paths.get_project_path", return_value=Path("/proj")), \
             mock.patch("pathlib.Path.exists", return_value=True), \
             mock.patch.object(mari_client_mod.mari_client, "export",
                               return_value={"ok": True, "files": chans}), \
             mock.patch("features.publisher.publish_core.publish_file",
                        side_effect=lambda src, *a, **k: Path("/proj/dest") / Path(src).name):
            out = me.publish_mari("PROJ", "CHAR", "TEX", "HERO", "null")
        self.assertTrue(out["ok"], out)
        self.assertEqual(len(out["published"]), 2)


if __name__ == "__main__":
    unittest.main()
