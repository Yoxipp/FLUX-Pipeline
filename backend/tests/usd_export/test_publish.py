# test_publish.py — light-export publish layout + versioning, resolver compatibility.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pxr import Sdf, Usd

from features.usd_assembler.resolve.flux_resolver import FluxResolver
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
    def test_first_publish_writes_last_set(self):
        with tempfile.TemporaryDirectory() as proj:
            res = publish_light_asset(_asset(), proj, fmt="usd")
            dest = Path(proj) / "CHAR_hero" / "model" / "usd"
            self.assertTrue((dest / "CHAR_hero_LAST.usd").exists())
            self.assertTrue((dest / "CHAR_hero_model_LAST.usd").exists())
            self.assertTrue((dest / "CHAR_hero_skel_LAST.usd").exists())
            self.assertEqual(res["version"], "v001")

    def test_resolver_picks_last(self):
        with tempfile.TemporaryDirectory() as proj:
            publish_light_asset(_asset(), proj, fmt="usd")
            resolved = FluxResolver(proj).resolve("CHAR_hero", "latest")
            self.assertEqual(resolved.path.name, "CHAR_hero_LAST.usd")
            self.assertEqual(resolved.default_prim, "CHAR_hero")
            # the resolved root composes to a valid asset root
            stage = Usd.Stage.Open(str(resolved.path))
            self.assertEqual(stage.GetDefaultPrim().GetName(), "CHAR_hero")
            self.assertTrue(stage.GetPrimAtPath("/CHAR_hero/body").IsValid())

    def test_second_publish_archives_previous(self):
        with tempfile.TemporaryDirectory() as proj:
            publish_light_asset(_asset(), proj, fmt="usd")
            res2 = publish_light_asset(_asset(), proj, fmt="usd")
            dest = Path(proj) / "CHAR_hero" / "model" / "usd"
            # previous LAST archived to v001, new active still LAST
            self.assertTrue((dest / "CHAR_hero_v001.usd").exists())
            self.assertTrue((dest / "CHAR_hero_model_v001.usd").exists())
            self.assertTrue((dest / "CHAR_hero_LAST.usd").exists())
            self.assertEqual(res2["version"], "v002")
            # archived root points at its OWN versioned sublayers, not _LAST
            layer = Sdf.Layer.FindOrOpen(str(dest / "CHAR_hero_v001.usd"))
            self.assertTrue(any("_v001." in p for p in layer.subLayerPaths))
            self.assertFalse(any("_LAST." in p for p in layer.subLayerPaths))


if __name__ == "__main__":
    unittest.main()
