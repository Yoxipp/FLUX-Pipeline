# test_publish.py — light-export publish: immutable vNNN/ folder + LAST pointer layer (ADR 0017).

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pxr import Usd

from features.publisher import last_pointer as lp
from features.usd_export import AnimData, LightAsset, MeshData, SkeletonData, publish_light_asset

_ID = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
_LEGACY_USDA = "#usda 1.0\n"


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
    def test_first_publish_creates_version_folder_and_last_layer(self):
        with tempfile.TemporaryDirectory() as proj:
            dest = Path(proj) / "pub"
            base = "CHAR_GEO_DAVID_null"
            res = publish_light_asset(_asset(), proj, fmt="usd", dest_dir=dest, base_name=base, user="adam")
            folder = dest / f"{base}_v001"
            self.assertEqual(res["version"], "v001")
            self.assertEqual(res["folder"], folder)
            self.assertTrue((folder / f"{base}.usd").exists())
            self.assertTrue((folder / f"{base}_model.usd").exists())
            # ADR 0034: a GEO publish is geometry only, the skeleton is the rig's.
            self.assertFalse((folder / f"{base}_skel.usd").exists())
            last = dest / f"{base}_LAST.usd"
            self.assertEqual(res["root"], last)
            self.assertFalse((dest / f"{base}_LAST").exists())
            flux = lp.read_layer_flux(last)
            self.assertEqual((flux["version"], flux["target"]), ("v001", f"{base}_v001/{base}.usd"))

            stage = Usd.Stage.Open(str(last))
            # LAST repeats the root defaultPrim (NAME token, ADR 0019) and composes the version
            self.assertEqual(stage.GetDefaultPrim().GetName(), "DAVID")
            self.assertTrue(stage.GetPrimAtPath("/DAVID/geo/render/body").IsValid())
            self.assertFalse(stage.GetPrimAtPath("/DAVID/skel/Skeleton").IsValid())
            self.assertEqual(stage.GetPrimAtPath("/DAVID").GetTypeName(), "Xform")
            self.assertTrue(any("squelette" in w for w in res["warnings"]))
            del stage  # Windows: a crate .usd stays memory-mapped while its stage lives, blocking cleanup

    def test_second_publish_keeps_versions_and_moves_last(self):
        with tempfile.TemporaryDirectory() as proj:
            dest = Path(proj) / "pub"
            publish_light_asset(_asset(), proj, fmt="usd", dest_dir=dest, base_name="DAVID")
            res2 = publish_light_asset(_asset(), proj, fmt="usd", dest_dir=dest, base_name="DAVID")
            self.assertEqual(res2["version"], "v002")
            self.assertTrue((dest / "DAVID_v001" / "DAVID.usd").exists())
            self.assertEqual(lp.read_layer_flux(dest / "DAVID_LAST.usd")["version"], "v002")
            stage = Usd.Stage.Open(str(dest / "DAVID_v001" / "DAVID.usd"))
            self.assertTrue(stage.GetPrimAtPath("/DAVID/geo/render/body").IsValid())
            del stage  # release the memory-mapped crate before cleanup (Windows)

    def test_department_keeps_only_its_data(self):
        anim = AnimData(joints=["Root"], times=[1.0, 2.0], translations=[[(0, 0, 0)], [(1, 0, 0)]],
                        rotations=[[(0, 0, 0, 1)], [(0, 0, 0, 1)]], scales=[[(1, 1, 1)], [(1, 1, 1)]])
        full = LightAsset(**{**_asset().__dict__, "anim": anim})
        with tempfile.TemporaryDirectory() as proj:
            dest = Path(proj) / "pub"
            geo = publish_light_asset(full, proj, fmt="usda", dest_dir=dest, base_name="CHAR_GEO_DAVID_null")
            self.assertNotIn("anim", geo["layers"])
            self.assertIn("anim", geo["warnings"][0])
            rig = publish_light_asset(full, proj, fmt="usda", dest_dir=dest, base_name="CHAR_RIG_DAVID_null")
            stage = Usd.Stage.Open(str(rig["version_root"]))
            self.assertTrue(stage.GetPrimAtPath("/DAVID/skel/Skeleton").IsValid())
            self.assertFalse(stage.GetPrimAtPath("/DAVID/geo/render/body").IsValid())
            self.assertEqual(len(rig["warnings"]), 2)
            clip = publish_light_asset(full, proj, fmt="usda", dest_dir=dest, base_name="CHAR_ANIM_DAVID_null")
            self.assertIn("anim", clip["layers"])
            with self.assertRaises(ValueError):
                publish_light_asset(full, proj, fmt="usda", dest_dir=dest, base_name="CHAR_MULT_DAVID_null")
            self.assertFalse(any(p.name.startswith("CHAR_MULT") for p in dest.iterdir()))

    def test_legacy_last_folder_is_archived(self):
        with tempfile.TemporaryDirectory() as proj:
            dest = Path(proj) / "pub"
            legacy = dest / "DAVID_LAST"
            legacy.mkdir(parents=True)
            (legacy / "DAVID.usd").write_text(_LEGACY_USDA)
            res = publish_light_asset(_asset(), proj, fmt="usd", dest_dir=dest, base_name="DAVID")
            self.assertEqual(res["version"], "v002")
            self.assertEqual((dest / "DAVID_v001" / "DAVID.usd").read_text(), _LEGACY_USDA)
            self.assertFalse(legacy.exists())

    def test_fallback_layout_without_dest(self):
        with tempfile.TemporaryDirectory() as proj:
            res = publish_light_asset(_asset(), proj, fmt="usd")
            usd_dir = Path(proj) / "CHAR_hero" / "model" / "usd"
            self.assertTrue((usd_dir / "CHAR_hero_v001").is_dir())
            self.assertTrue((usd_dir / "CHAR_hero_LAST.usd").is_file())
            self.assertEqual(res["version"], "v001")


if __name__ == "__main__":
    unittest.main()
