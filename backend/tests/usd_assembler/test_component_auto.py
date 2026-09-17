# USD_ASSEMBLER_V2 A1: a GEO / RIG publish regenerates <NAME_path>/usd/<NAME>_vNNN/
# (entry + payload) and <NAME>_LAST.usda, with relative, prim-remapped slot references.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pxr import Sdf, Usd, UsdGeom

from features.folder_manager import tokens as tok
from features.usd_assembler.component_auto import refresh_component, refresh_from_publish
from features.usd_export import LightAsset, MeshData, SkeletonData, publish_light_asset

_ID = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
_NAME = "UTAH"
_NAME_REL = "assets/chara/UTAH"


def _asset(joints: list[str]) -> LightAsset:
    n = len(joints)
    return LightAsset(
        asset="tmp",
        skeleton=SkeletonData(joints=joints, bind_transforms=[_ID] * n, rest_transforms=[_ID] * n),
        meshes=[MeshData(name="body", points=[(0, 0, 0), (1, 0, 0), (1, 1, 0)],
                         face_vertex_counts=[3], face_vertex_indices=[0, 1, 2])],
    )


class ComponentAuto(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "PROJ"
        self.project.mkdir()
        tokens = tok.build_default_tokens()
        tokens["NAME"][_NAME] = _NAME_REL
        tok.save_tokens(self.project, tokens)
        self.usd_dir = self.project / _NAME_REL / "usd"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _publish(self, task: str, sub: str, joints: list[str]) -> dict:
        dest = self.project / _NAME_REL / sub / "null"
        return publish_light_asset(_asset(joints), self.project, fmt="usd", dest_dir=dest,
                                   base_name=f"CHAR_{task}_{_NAME}_null", user="adam")

    def test_geo_publish_creates_component(self) -> None:
        res = self._publish("GEO", "model", ["Root"])
        self.assertEqual(res["component"], "v001")
        entry = self.usd_dir / "UTAH_v001" / "UTAH.usda"
        self.assertTrue(entry.is_file())
        self.assertTrue((self.usd_dir / "UTAH_v001" / "UTAH_payload.usda").is_file())

        stage = Usd.Stage.Open(str(self.usd_dir / "UTAH_LAST.usda"))
        prim = stage.GetDefaultPrim()
        self.assertEqual(prim.GetPath(), Sdf.Path("/UTAH"))
        self.assertEqual(Usd.ModelAPI(prim).GetKind(), "component")
        self.assertEqual(prim.GetTypeName(), "SkelRoot")
        self.assertTrue(any(p.IsA(UsdGeom.Mesh) for p in Usd.PrimRange(prim)))
        self.assertEqual(prim.GetAssetInfo()["version"], "v001")

        refs = Sdf.Layer.FindOrOpen(str(self.usd_dir / "UTAH_v001" / "UTAH_payload.usda")) \
            .GetPrimAtPath("/UTAH").referenceList.prependedItems
        paths = [r.assetPath for r in refs]
        self.assertTrue(all(p.startswith("../../model/null/") for p in paths), paths)
        self.assertEqual({r.primPath.pathString for r in refs}, {"/UTAH"})

    def test_rig_publish_takes_skel_slot_and_bumps_version(self) -> None:
        self._publish("GEO", "model", ["Root"])
        res = self._publish("RIG", "rig", ["Root", "Root/Hip"])
        self.assertEqual(res["component"], "v002")
        data = Sdf.Layer.FindOrOpen(str(self.usd_dir / "UTAH_v002" / "UTAH.usda")).customLayerData
        slots = data["flux"]["slots"]
        self.assertEqual(slots["model"]["task"], "GEO")
        self.assertEqual(slots["skel"]["task"], "RIG")
        stage = Usd.Stage.Open(str(self.usd_dir / "UTAH_LAST.usda"))
        self.assertTrue(stage.GetPrimAtPath("/UTAH").IsValid())

    def test_unchanged_slots_do_not_create_version(self) -> None:
        self._publish("GEO", "model", ["Root"])
        self.assertIsNone(refresh_component(self.project, _NAME))
        self.assertFalse((self.usd_dir / "UTAH_v002").exists())

    def test_non_component_task_is_ignored(self) -> None:
        res = self._publish("ANIM", "anim", ["Root"])
        self.assertIsNone(res["component"])
        self.assertFalse(self.usd_dir.exists())
        self.assertIsNone(refresh_from_publish(self.project, "SH_SEQ010_SH020_null"))


if __name__ == "__main__":
    unittest.main()
