# USD_ASSEMBLER_V2 A3: versioned assemblies edited from the Library (decisions section 10).

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pxr import Sdf, Usd, UsdGeom

from features.folder_manager import tokens as tok
from features.usd_assembler import assembly_v2 as av
from features.usd_assembler.component_auto import refresh_component
from features.usd_assembler.library import build_library
from features.usd_assembler.resolve.flux_resolver import FluxResolver
from features.usd_assembler.usd_assembler_core import assemble
from features.usd_export import LightAsset, MeshData, SkeletonData, publish_light_asset

_ID = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)


def _asset() -> LightAsset:
    return LightAsset(
        asset="tmp",
        skeleton=SkeletonData(joints=["Root"], bind_transforms=[_ID], rest_transforms=[_ID]),
        meshes=[MeshData(name="body", points=[(0, 0, 0), (1, 0, 0), (1, 1, 0)],
                         face_vertex_counts=[3], face_vertex_indices=[0, 1, 2])],
    )


class AssemblyV2(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "PROJ"
        self.project.mkdir()
        tokens = tok.build_default_tokens()
        tokens["NAME"]["UTAH"] = "assets/chara/UTAH"
        tokens["NAME"]["BARREL"] = "assets/props/BARREL"
        tok.save_tokens(self.project, tokens)
        for name, cls in (("UTAH", "CHAR"), ("BARREL", "PROPS")):
            publish_light_asset(_asset(), self.project, fmt="usd",
                                dest_dir=self.project / tokens["NAME"][name] / "model" / "null",
                                base_name=f"{cls}_GEO_{name}_null")
        self.assertIsNotNone(refresh_component(self.project, "UTAH") or True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _stage(self, name: str) -> Usd.Stage:
        return Usd.Stage.Open(str(av.assembly_dir(self.project, name) / f"{name}_LAST.usda"))

    def test_create_add_and_compose(self) -> None:
        self.assertEqual(av.create_assembly(self.project, "TOWN")["version"], "v001")
        res = av.edit_assembly(self.project, "TOWN", [
            {"op": "add", "component": "UTAH", "count": 2},
            {"op": "add", "component": "BARREL"},
        ])
        self.assertEqual(res["version"], "v002")
        names = [(i["class"], i["name"]) for i in av.read_instances(self.project, "TOWN")]
        self.assertEqual(names, [("CHAR", "UTAH_01"), ("CHAR", "UTAH_02"), ("PROPS", "BARREL_01")])

        stage = self._stage("TOWN")
        root = stage.GetDefaultPrim()
        self.assertEqual(Usd.ModelAPI(root).GetKind(), "assembly")
        self.assertEqual(Usd.ModelAPI(stage.GetPrimAtPath("/TOWN/CHAR")).GetKind(), "group")
        inst = stage.GetPrimAtPath("/TOWN/CHAR/UTAH_01")
        self.assertTrue(inst.IsInstance())
        self.assertEqual(Usd.ModelAPI(inst).GetKind(), "component")
        comp_stage = Usd.Stage.Open(str(self.project / "assets/chara/UTAH/usd/UTAH_LAST.usda"))
        self.assertEqual(inst.GetTypeName(), comp_stage.GetDefaultPrim().GetTypeName())   # SkelRoot kept
        meshes = [p for p in Usd.PrimRange(inst, Usd.TraverseInstanceProxies()) if p.IsA(UsdGeom.Mesh)]
        self.assertEqual(len(meshes), 1)

        contents = Sdf.Layer.FindOrOpen(str(av.current_entry(self.project, "TOWN").parent / "TOWN_contents.usda"))
        ref = contents.GetPrimAtPath("/TOWN/CHAR/UTAH_01").referenceList.prependedItems[0]
        self.assertTrue(ref.assetPath.startswith("../../../../assets/chara/UTAH/usd/UTAH_LAST"))

        lib = build_library(self.project)
        town = next(a for a in lib["assemblies"] if a["name"] == "TOWN")
        self.assertEqual((town["version"], town["versions"], town["legacy"]), ("v002", ["v001", "v002"], False))
        self.assertEqual(len(town["instances"]), 3)
        utah = next(c for c in lib["components"] if c["name"] == "UTAH")
        self.assertEqual(utah["used_by"], ["TOWN"])

    def test_duplicate_rename_remove_relink_versions(self) -> None:
        av.create_assembly(self.project, "TOWN")
        av.edit_assembly(self.project, "TOWN", [{"op": "add", "component": "UTAH"}])
        res = av.edit_assembly(self.project, "TOWN", [
            {"op": "duplicate", "name": "UTAH_01"},
            {"op": "rename", "name": "UTAH_02", "new_name": "hero"},
            {"op": "relink", "name": "hero", "component": "BARREL"},
            {"op": "set_version", "all": True, "version": "v001"},
        ])
        self.assertTrue(any("hero" in w for w in res["warnings"]))
        insts = av.read_instances(self.project, "TOWN")
        self.assertEqual([(i["name"], i["component"], i["version"]) for i in insts],
                         [("UTAH_01", "UTAH", "v001"), ("hero", "BARREL", "v001")])
        av.edit_assembly(self.project, "TOWN", [{"op": "remove", "name": "hero"}])
        self.assertEqual([i["name"] for i in av.read_instances(self.project, "TOWN")], ["UTAH_01"])

    def test_instance_picks_a_component_variant(self) -> None:
        # A second INSTANCE of UTAH is a variant of its model department (ADR 0019);
        # each assembly instance can pick which one it shows.
        publish_light_asset(_asset(), self.project, fmt="usd",
                            dest_dir=self.project / "assets/chara/UTAH" / "model" / "B",
                            base_name="CHAR_GEO_UTAH_B")
        refresh_component(self.project, "UTAH")
        av.create_assembly(self.project, "TOWN")
        av.edit_assembly(self.project, "TOWN", [{"op": "add", "component": "UTAH", "count": 2}])
        res = av.edit_assembly(self.project, "TOWN", [
            {"op": "set_variant", "name": "UTAH_02", "department": "model", "variant": "B"}])
        self.assertEqual(res["warnings"], [])
        stage = self._stage("TOWN")
        self.assertEqual(stage.GetPrimAtPath("/TOWN/CHAR/UTAH_01").GetVariantSet("model").GetVariantSelection(), "null")
        self.assertEqual(stage.GetPrimAtPath("/TOWN/CHAR/UTAH_02").GetVariantSet("model").GetVariantSelection(), "B")
        inst = next(i for i in av.read_instances(self.project, "TOWN") if i["name"] == "UTAH_02")
        self.assertEqual(inst["variants"], {"model": "B"})
        # back to the component default, and an unknown variant is refused
        av.edit_assembly(self.project, "TOWN", [
            {"op": "set_variant", "name": "UTAH_02", "department": "model", "variant": ""}])
        self.assertEqual(av.read_instances(self.project, "TOWN")[1].get("variants", {}), {})
        with self.assertRaises(ValueError):
            av.edit_assembly(self.project, "TOWN", [
                {"op": "set_variant", "name": "UTAH_01", "department": "model", "variant": "NOPE"}])

    def test_noop_edit_and_errors(self) -> None:
        av.create_assembly(self.project, "TOWN")
        av.edit_assembly(self.project, "TOWN", [{"op": "add", "component": "UTAH"}])
        res = av.edit_assembly(self.project, "TOWN", [{"op": "set_version", "all": True, "version": "LAST"}])
        self.assertTrue(res["unchanged"])
        with self.assertRaises(ValueError):
            av.edit_assembly(self.project, "TOWN", [{"op": "add", "component": "UTAH", "version": "v009"}])
        with self.assertRaises(ValueError):
            av.edit_assembly(self.project, "TOWN", [{"op": "remove", "name": "nope"}])
        with self.assertRaises(ValueError):
            av.create_assembly(self.project, "TOWN")
        with self.assertRaises(ValueError):
            av.create_assembly(self.project, "bad name")

    def test_duplicate_assembly(self) -> None:
        av.create_assembly(self.project, "TOWN")
        av.edit_assembly(self.project, "TOWN", [{"op": "add", "component": "BARREL", "count": 3}])
        self.assertEqual(av.create_assembly(self.project, "TOWN_B", source="TOWN")["version"], "v001")
        self.assertEqual(len(av.read_instances(self.project, "TOWN_B")), 3)

    def test_legacy_flat_assembly_converted_on_edit(self) -> None:
        assemble({"target": {"kind": "assembly", "asset": "ENV_forest"},
                  "components": [{"asset": "UTAH", "instance": "utah_01"}]},
                 resolver=FluxResolver(self.project), dest_dir=self.project / "usd" / "assembly")
        lib = build_library(self.project)
        self.assertTrue(next(a for a in lib["assemblies"] if a["name"] == "ENV_forest")["legacy"])
        res = av.edit_assembly(self.project, "ENV_forest", [{"op": "add", "component": "BARREL"}])
        self.assertEqual(res["version"], "v001")
        comps = [i["component"] for i in av.read_instances(self.project, "ENV_forest")]
        self.assertEqual(comps, ["UTAH", "BARREL"])
        forest = [a for a in build_library(self.project)["assemblies"] if a["name"] == "ENV_forest"]
        self.assertEqual(len(forest), 1)
        self.assertFalse(forest[0]["legacy"])

    def test_layout_is_sublayered_and_orphans_warned(self) -> None:
        av.create_assembly(self.project, "TOWN")
        av.edit_assembly(self.project, "TOWN", [{"op": "add", "component": "UTAH"}])
        layout = Sdf.Layer.CreateNew(str(av.assembly_dir(self.project, "TOWN") / "TOWN_layout_LAST.usda"))
        spec = Sdf.CreatePrimInLayer(layout, "/TOWN/CHAR/UTAH_01")
        spec.specifier = Sdf.SpecifierOver
        layout.Save()
        res = av.edit_assembly(self.project, "TOWN", [{"op": "rename", "name": "UTAH_01", "new_name": "hero"}])
        self.assertTrue(any("orphelin" in w for w in res["warnings"]))
        payload = Sdf.Layer.FindOrOpen(str(av.current_entry(self.project, "TOWN").parent / "TOWN_payload.usda"))
        self.assertEqual(list(payload.subLayerPaths), ["../TOWN_layout_LAST.usda", "./TOWN_contents.usda"])


if __name__ == "__main__":
    unittest.main()
