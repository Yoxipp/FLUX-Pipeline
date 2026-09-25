# Texture maps exported by Painter / Mari: map tokens and UDIM tiles published as
# ONE version (a <base>_vNNN/ folder), not one version per tile.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dcc import texture_publish as tp


class MapNames(unittest.TestCase):
    def test_tokens_and_tiles(self) -> None:
        self.assertEqual(tp.split_map_name("HeroBody_BaseColor.png"), ("BASECOLOR", None))
        self.assertEqual(tp.split_map_name("Utah_Skin_BaseColor_ACES - ACEScg.1001.exr"), ("BASECOLOR", 1001))
        self.assertEqual(tp.split_map_name("Body_Roughness.1002.exr"), ("ROUGHNESS", 1002))
        self.assertEqual(tp.split_map_name("Ambient Occlusion.1001.exr", whole_name=True), ("AMBIENTOCCLUSION", 1001))
        self.assertEqual(tp.split_map_name("B_COL.1003.exr", whole_name=True), ("BCOL", 1003))

    def test_one_canonical_token_per_map(self) -> None:
        # 2026-09-25: COL and BCOL, BASECOLOR and BCOL side by side.
        c = tp.canonical_map_token
        self.assertEqual(c("B_COL.1001.tif", whole_name=True), "BCOL")
        self.assertEqual(c("Color.1001.tif", whole_name=True), "BCOL")
        self.assertEqual(c("Ambient Occlusion.1001.tif", whole_name=True), "AO")
        self.assertEqual(c("Displacement.1001.exr", whole_name=True), "DISP")
        self.assertEqual(c("ZDISP.1001.exr", whole_name=True), "ZDISP")
        self.assertEqual(c("Curvature.1001.tif", whole_name=True), "CURV")
        self.assertEqual(c("HeroBody_BaseColor.png"), "BCOL")
        self.assertEqual(c("Body_Height_ACES - ACEScg.1001.exr"), "DISP")
        self.assertEqual(c("Body_Normal_OpenGL.png"), "NORM")
        self.assertEqual(c("Metal_Armor_Emissive.png"), "EMISS")        # not METAL: the set name
        self.assertIsNone(c("Body_OcclusionRoughnessMetallic.png"))       # packed map: its own name

    def test_two_maps_on_one_token_keep_apart(self) -> None:
        # Mari geo with a DISP and a Displacement channel: DISP keeps DISP.
        warnings: list[str] = []
        groups = tp.group_maps([Path("Displacement.1001.exr"), Path("DISP.1001.exr"), Path("ZDISP.1001.exr")],
                               whole_name=True, warnings=warnings)
        self.assertEqual(sorted(groups), ["DISP", "DISPLACEMENT", "ZDISP"])
        self.assertEqual(groups["DISP"][0][1].name, "DISP.1001.exr")
        self.assertEqual(len(warnings), 1)
        self.assertIn("DISPLACEMENT", warnings[0])

    def test_group_maps_sorts_tiles(self) -> None:
        files = [Path("a_BaseColor.1002.exr"), Path("a_BaseColor.1001.exr"), Path("a_Normal.png")]
        groups = tp.group_maps(files)
        self.assertEqual([t for t, _ in groups["BCOL"]], [1001, 1002])
        self.assertEqual(groups["NORM"][0][0], None)


class UdimPublish(unittest.TestCase):
    def test_tiles_become_one_version(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            project = root / "PROJ"
            project.mkdir()
            src = root / "export"
            src.mkdir()
            files = []
            for tile in (1001, 1002, 1003):
                f = src / f"Body_BaseColor_ACES - ACEScg.{tile}.exr"
                f.write_bytes(b"x" * 8)
                files.append(f)
            plain = src / "Body_Normal.exr"
            plain.write_bytes(b"n")
            files.append(plain)

            published, warnings = tp.publish_maps(files, project, "PROJ", ["CHAR", "TEX", "UTAH"], "",
                                                  "test", "adam")
            self.assertEqual(warnings, [])
            self.assertEqual(len(published), 2)
            folder = Path(next(p for p in published if Path(p).is_dir()))
            self.assertEqual(folder.name, "CHAR_TEX_UTAH_BCOL_v001")
            self.assertEqual(sorted(f.name for f in folder.iterdir()), [
                "CHAR_TEX_UTAH_BCOL_v001.1001.exr",
                "CHAR_TEX_UTAH_BCOL_v001.1002.exr",
                "CHAR_TEX_UTAH_BCOL_v001.1003.exr",
            ])
            # A second publish is v002, never one version per tile.
            tp.publish_maps(files[:3], project, "PROJ", ["CHAR", "TEX", "UTAH"], "", "", "adam")
            self.assertTrue((folder.parent / "CHAR_TEX_UTAH_BCOL_v002").is_dir())
            self.assertFalse((folder.parent / "CHAR_TEX_UTAH_BCOL_v003").exists())


if __name__ == "__main__":
    unittest.main()
