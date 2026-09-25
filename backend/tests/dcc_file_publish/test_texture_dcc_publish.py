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
        self.assertEqual(cfg["exportParameters"][0]["parameters"]["paddingAlgorithm"], "infinite")

    def test_build_export_config_size_padding_sets(self):
        cfg = se.build_export_config("/tmp/out", "P", "exr", "16", ["Body"], 4096, "color", 8)
        params = cfg["exportParameters"][0]["parameters"]
        self.assertEqual((params["sizeLog2"], params["paddingAlgorithm"], params["dilationDistance"]),
                         (12, "color", 8))
        self.assertEqual(cfg["exportList"], [{"rootPath": "Body"}])
        infinite = se.build_export_config("/tmp/out", "P")["exportParameters"][0]["parameters"]
        self.assertNotIn("dilationDistance", infinite)
        self.assertNotIn("sizeLog2", infinite)

    def test_only_the_ticked_maps_with_their_own_bit_depth_and_size(self):
        # 2026-09-25: map by map like Mari, bit depth and size per map.
        cfg = se.build_export_config("/tmp/out", "P", "png", "8", ["Body"], None, maps=[
            "$textureSet_BaseColor", "$textureSet_Height"], map_params={
            "$textureSet_Height": {"bit_depth": "32", "size": 2048},
            "$textureSet_Normal": {"bit_depth": "16"}})       # not ticked: ignored
        self.assertEqual(cfg["exportList"], [{"rootPath": "Body", "filter": {
            "outputMaps": ["$textureSet_BaseColor", "$textureSet_Height"]}}])
        # png cannot hold 32 bits: the closest depth it holds
        self.assertEqual(cfg["exportParameters"][1], {"filter": {"outputMaps": ["$textureSet_Height"]},
                                                      "parameters": {"bitDepth": "16", "sizeLog2": 11}})
        self.assertEqual(len(cfg["exportParameters"]), 2)
        # every set: the bridge applies the filter after listing them
        cfg = se.build_export_config("/tmp/out", "P", maps=["$textureSet_Height"])
        self.assertEqual(cfg["fluxOutputMaps"], ["$textureSet_Height"])
        self.assertNotIn("exportList", cfg)

    def test_every_shader_channel_can_be_exported(self):
        # 2026-09-25: coat, anisotropy, user channels were not listed (preset maps only).
        chans = [{"id": "coatRoughness", "label": "Coat Roughness", "gray": True},
                 {"id": "baseColor", "label": "Base Color", "gray": False}]
        cfg = se.build_export_config("/tmp/out", "PBR Metallic Roughness", "exr", "16", ["Body"],
                                     maps=["$textureSet_CoatRoughness"], channels=chans,
                                     map_params={"$textureSet_CoatRoughness": {"bit_depth": "32f"}})
        self.assertEqual(cfg["defaultExportPreset"], se.CHANNEL_PRESET)
        preset = cfg["exportPresets"][0]
        self.assertEqual(preset["name"], se.CHANNEL_PRESET)
        coat = preset["maps"][0]
        self.assertEqual(coat["fileName"], "$textureSet_CoatRoughness")
        self.assertEqual(coat["channels"], [{"destChannel": "L", "srcChannel": "L",
                                             "srcMapType": "documentMap", "srcMapName": "coatRoughness"}])
        self.assertEqual([c["destChannel"] for c in preset["maps"][1]["channels"]], ["R", "G", "B"])
        self.assertEqual(cfg["exportList"][0]["filter"]["outputMaps"], ["$textureSet_CoatRoughness"])

    def test_bridge_channel_names_and_inline_preset(self):
        from types import SimpleNamespace

        from dcc.substance_painter import substance_painter_bridge as br
        self.assertEqual(br._channel_map_name(SimpleNamespace(name="CoatRoughness")), "coatRoughness")
        self.assertEqual(br._channel_map_name(SimpleNamespace(name="IOR")), "ior")
        self.assertEqual(br._channel_map_name(SimpleNamespace(name="User0")), "user0")

    def test_bridge_map_labels(self):
        from dcc.substance_painter import substance_painter_bridge as br
        self.assertEqual(br._map_label("$textureSet_BaseColor"), "BaseColor")
        self.assertEqual(br._map_label("$mesh_$textureSet_Normal(_$colorSpace)"), "Normal")
        self.assertEqual(br._map_label("$textureSet_Height.$udim"), "Height")

    def test_map_token_from_filename(self):
        self.assertEqual(se.map_token_from_filename("HeroBody_BaseColor.png"), "BCOL")
        self.assertEqual(se.map_token_from_filename("HeroBody_Roughness.1001.exr"), "ROUGH")


class PublishPainter(unittest.TestCase):
    def test_exports_then_ingests_each_map(self):
        def _export(config):
            # The bridge writes the maps in the export dir; FLUX reads the dir.
            out = Path(config["exportPath"])
            for name in ("x_BaseColor.png", "x_Roughness.png"):
                (out / name).write_bytes(b"x")
            return {"ok": True, "files": []}

        with mock.patch("core.paths.get_project_path", return_value=Path(__file__).parent), \
             mock.patch.object(sp_client.substance_client, "export", side_effect=_export), \
             mock.patch("features.publisher.publish_core.publish_file",
                        side_effect=lambda src, *a, **k: Path("/proj/dest") / Path(src).name) as pf:
            out = se.publish_painter("PROJ", "CHAR", "TEX", "HERO", "null")
        self.assertTrue(out["ok"], out)
        self.assertEqual(len(out["published"]), 2)
        # each map ingested with a composed FLUX target name (map token uppercased)
        names = [k.kwargs.get("target_name") or k.args[5] for k in pf.call_args_list]
        self.assertIn("CHAR_TEX_HERO_BCOL", names)
        self.assertIn("CHAR_TEX_HERO_ROUGH", names)

    def test_export_failure(self):
        with mock.patch("core.paths.get_project_path", return_value=Path("/proj")), \
             mock.patch("pathlib.Path.exists", return_value=True), \
             mock.patch.object(sp_client.substance_client, "export",
                               return_value={"ok": False, "error": "Painter closed"}):
            out = se.publish_painter("PROJ", "CHAR", "TEX", "HERO")
        self.assertFalse(out["ok"])


class PublishMari(unittest.TestCase):
    def test_exports_then_ingests(self):
        def _export(export_path, file_format, channels=None):
            # Mari names each file after its channel only ($UDIM filled by Mari).
            import OpenImageIO as oiio
            for name in ("Diffuse.tif", "B_COL.tif"):
                buf = oiio.ImageBuf(oiio.ImageSpec(8, 8, 3, "uint8"))
                buf.write(str(Path(export_path) / name))
            return {"ok": True, "files": [f"{export_path}/Diffuse.$UDIM.tif"]}

        with mock.patch("core.paths.get_project_path", return_value=Path(__file__).parent), \
             mock.patch.object(mari_client_mod.mari_client, "export", side_effect=_export), \
             mock.patch("features.publisher.publish_core.publish_file",
                        side_effect=lambda src, *a, **k: Path("/proj/dest") / Path(src).name) as pf:
            out = me.publish_mari("PROJ", "CHAR", "TEX", "HERO", "null")
        self.assertTrue(out["ok"], out)
        self.assertEqual(len(out["published"]), 2)
        names = [k.args[5] for k in pf.call_args_list]
        self.assertEqual(sorted(names), ["CHAR_TEX_HERO_BCOL", "CHAR_TEX_HERO_DIFFUSE"])


if __name__ == "__main__":
    unittest.main()
