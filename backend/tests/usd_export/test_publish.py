# test_publish.py — light-export publish (per-version folder layout).

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pxr import Usd

from features.usd_export import LightAsset, MeshData, SkeletonData, publish_light_asset

_ID = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)


def _asset() -> LightAsset:
    return LightAsset(
        asset="CHAR_hero",
        skeleton=SkeletonData(joints=["Root"], bind_transforms=[_ID], rest_transforms=[_ID]),
        meshes=[MeshData(
            name="body",
            points=[(0, 0, 0), (1, 0, 0), (1, 1, 0)],
            face_vertex_counts=[3],
            face_vertex_indices=[0, 1, 2],
        )],
    )


class PublishLightAsset(unittest.TestCase):
    def test_first_publish_creates_last_folder(self):
        with tempfile.TemporaryDirectory() as proj:
            dest = Path(proj) / "pub"
            res = publish_light_asset(_asset(), proj, fmt="usd", dest_dir=dest, base_name="CHAR_BLOCK_DAVID_null")
            folder = dest / "CHAR_BLOCK_DAVID_null_LAST"
            self.assertTrue(folder.is_dir())
            self.assertTrue((folder / "CHAR_BLOCK_DAVID_null.usd").exists())
            self.assertTrue((folder / "CHAR_BLOCK_DAVID_null_model.usd").exists())
            self.assertTrue((folder / "CHAR_BLOCK_DAVID_null_skel.usd").exists())
            self.assertEqual(res["version"], "v001")

            stage = Usd.Stage.Open(str(folder / "CHAR_BLOCK_DAVID_null.usd"))
            # file names use the base, but the prim identity is the sanitized base too
            self.assertEqual(stage.GetDefaultPrim().GetName(), "CHAR_BLOCK_DAVID_null")
            self.assertTrue(stage.GetPrimAtPath("/CHAR_BLOCK_DAVID_null/body").IsValid())

    def test_second_publish_archives_folder(self):
        with tempfile.TemporaryDirectory() as proj:
            dest = Path(proj) / "pub"
            publish_light_asset(_asset(), proj, fmt="usd", dest_dir=dest, base_name="DAVID")
            res2 = publish_light_asset(_asset(), proj, fmt="usd", dest_dir=dest, base_name="DAVID")
            self.assertTrue((dest / "DAVID_v001").is_dir())
            self.assertTrue((dest / "DAVID_LAST").is_dir())
            self.assertEqual(res2["version"], "v002")
            # archived root still composes from its own sibling sublayers
            stage = Usd.Stage.Open(str(dest / "DAVID_v001" / "DAVID.usd"))
            self.assertTrue(stage.GetPrimAtPath("/DAVID/body").IsValid())

    def test_fallback_layout_without_dest(self):
        with tempfile.TemporaryDirectory() as proj:
            res = publish_light_asset(_asset(), proj, fmt="usd")
            self.assertTrue((Path(proj) / "CHAR_hero" / "model" / "usd" / "CHAR_hero_LAST").is_dir())
            self.assertEqual(res["version"], "v001")


if __name__ == "__main__":
    unittest.main()
