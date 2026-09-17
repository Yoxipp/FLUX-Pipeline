# USD_ASSEMBLER_V2 A1 + ADR 0019: a GEO / RIG publish regenerates <NAME_path>/usd/<NAME>_vNNN/
# (entry, payload sublayering department layers, one variant per INSTANCE) and <NAME>_LAST.usda.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pxr import Sdf, Usd, UsdGeom, UsdSkel

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

    def _publish(self, task: str, sub: str, joints: list[str], instance: str = "null") -> dict:
        dest = self.project / _NAME_REL / sub / instance
        return publish_light_asset(_asset(joints), self.project, fmt="usd", dest_dir=dest,
                                   base_name=f"CHAR_{task}_{_NAME}_{instance}", user="adam")

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

        payload = Sdf.Layer.FindOrOpen(str(self.usd_dir / "UTAH_v001" / "UTAH_payload.usda"))
        self.assertEqual(list(payload.subLayerPaths), ["./UTAH_model.usda"])
        model = Sdf.Layer.FindOrOpen(str(self.usd_dir / "UTAH_v001" / "UTAH_model.usda"))
        vset = model.GetPrimAtPath("/UTAH").variantSets["model"]
        refs = vset.variants["null"].primSpec.referenceList.prependedItems
        self.assertTrue(refs[0].assetPath.startswith("../../model/null/CHAR_GEO_UTAH_null_v001/"), refs[0].assetPath)
        self.assertEqual(refs[0].primPath.pathString, "/UTAH")
        self.assertTrue(stage.GetPrimAtPath("/UTAH/geo/render/body").IsValid())

    def test_rig_department_is_stronger_than_model(self) -> None:
        self._publish("GEO", "model", ["Root"])
        res = self._publish("RIG", "rig", ["Root", "Root/Hip"])
        self.assertEqual(res["component"], "v002")
        data = Sdf.Layer.FindOrOpen(str(self.usd_dir / "UTAH_v002" / "UTAH.usda")).customLayerData
        slots = data["flux"]["slots"]
        self.assertEqual((slots["model"]["task"], slots["rig"]["task"]), ("GEO", "RIG"))
        payload = Sdf.Layer.FindOrOpen(str(self.usd_dir / "UTAH_v002" / "UTAH_payload.usda"))
        self.assertEqual(list(payload.subLayerPaths), ["./UTAH_rig.usda", "./UTAH_model.usda"])
        stage = Usd.Stage.Open(str(self.usd_dir / "UTAH_LAST.usda"))
        skel = UsdSkel.Skeleton(stage.GetPrimAtPath("/UTAH/skel/Skeleton"))
        self.assertEqual(list(skel.GetJointsAttr().Get()), ["Root", "Root/Hip"])

    def test_instances_become_variants(self) -> None:
        self._publish("GEO", "model", ["Root"])
        res = self._publish("GEO", "model", ["Root"], instance="B")
        self.assertEqual(res["component"], "v002")
        stage = Usd.Stage.Open(str(self.usd_dir / "UTAH_LAST.usda"))
        vset = stage.GetPrimAtPath("/UTAH").GetVariantSet("model")
        self.assertEqual(sorted(vset.GetVariantNames()), ["B", "null"])
        self.assertEqual(vset.GetVariantSelection(), "null")
        vset.SetVariantSelection("B")
        self.assertTrue(stage.GetPrimAtPath("/UTAH/geo/render/body").IsValid())
        res = refresh_component(self.project, _NAME, pins={"model": {"instance": "B", "version": "latest"}})
        self.assertEqual(res["slots"]["model"]["default"], "B")

    def test_unchanged_slots_do_not_create_version(self) -> None:
        self._publish("GEO", "model", ["Root"])
        self.assertIsNone(refresh_component(self.project, _NAME))
        self.assertFalse((self.usd_dir / "UTAH_v002").exists())

    def test_plain_usd_publish_feeds_its_department(self) -> None:
        # A normal USD publish (mayaUSDExport, Houdini ROP...) is a department
        # contribution too, not only the layered light export (ADR 0019).
        from pxr import UsdGeom

        from features.publisher.publish_core import publish_file

        src = self.project / "_src" / "CHAR_GEO_UTAH_null.usda"
        src.parent.mkdir(parents=True, exist_ok=True)
        stage = Usd.Stage.CreateNew(str(src))
        stage.SetDefaultPrim(UsdGeom.Xform.Define(stage, f"/{_NAME}").GetPrim())
        UsdGeom.Mesh.Define(stage, f"/{_NAME}/geo/render/body")
        stage.GetRootLayer().Save()
        self.assertIsNotNone(publish_file(src, self.project, "flat", "adam", "PROJ"))

        entry = self.usd_dir / "UTAH_v001" / "UTAH.usda"
        self.assertTrue(entry.is_file())
        model = Sdf.Layer.FindOrOpen(str(self.usd_dir / "UTAH_v001" / "UTAH_model.usda"))
        ref = model.GetPrimAtPath("/UTAH").variantSets["model"].variants["null"] \
            .primSpec.referenceList.prependedItems[0]
        self.assertTrue(ref.assetPath.endswith("CHAR_GEO_UTAH_null_v001.usda"), ref.assetPath)
        composed = Usd.Stage.Open(str(self.usd_dir / "UTAH_LAST.usda"))
        self.assertTrue(composed.GetPrimAtPath("/UTAH/geo/render/body").IsValid())

    def test_variante_is_its_own_variant(self) -> None:
        # Two publishes of the same instance that differ only by their VARIANTE token
        # are two different things: one variant each, no silent overwrite (ADR 0019).
        self._publish("GEO", "model", ["Root"])
        dest = self.project / _NAME_REL / "model" / "null"
        publish_light_asset(_asset(["Root"]), self.project, fmt="usd", dest_dir=dest,
                            base_name=f"CHAR_GEO_{_NAME}_null_DAMAGED", user="adam")
        from features.usd_assembler.component_auto import collect_slots

        slots = collect_slots(self.project, _NAME)
        self.assertEqual(sorted(slots["model"]["variants"]), ["null", "null_DAMAGED"])
        self.assertEqual(slots["model"]["default"], "null")
        self.assertEqual(slots["model"]["variants"]["null_DAMAGED"]["variante"], "DAMAGED")
        stage = Usd.Stage.Open(str(self.usd_dir / "UTAH_LAST.usda"))
        self.assertEqual(sorted(stage.GetPrimAtPath("/UTAH").GetVariantSet("model").GetVariantNames()),
                         ["null", "null_DAMAGED"])

    def test_non_component_task_is_ignored(self) -> None:
        res = self._publish("ANIM", "anim", ["Root"])
        self.assertIsNone(res["component"])
        self.assertFalse(self.usd_dir.exists())
        self.assertIsNone(refresh_from_publish(self.project, "SH_SEQ010_SH020_null"))


if __name__ == "__main__":
    unittest.main()
