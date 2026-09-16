# USD_ASSEMBLER_V2 A2: library of existing components (ADR 0018) and assemblies,
# with state, used_by, instance -> component mapping and broken links.

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from features.folder_manager import tokens as tok
from features.usd_assembler.component_auto import refresh_component
from features.usd_assembler.library import build_library, relink_instance
from features.usd_assembler.resolve.flux_resolver import FluxResolver
from features.usd_assembler.usd_assembler_core import assemble
from features.usd_export import LightAsset, MeshData, SkeletonData, publish_light_asset

_ID = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
_NAME_REL = "assets/chara/UTAH"


def _asset() -> LightAsset:
    return LightAsset(
        asset="tmp",
        skeleton=SkeletonData(joints=["Root"], bind_transforms=[_ID], rest_transforms=[_ID]),
        meshes=[MeshData(name="body", points=[(0, 0, 0), (1, 0, 0), (1, 1, 0)],
                         face_vertex_counts=[3], face_vertex_indices=[0, 1, 2])],
    )


class Library(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "PROJ"
        self.project.mkdir()
        tokens = tok.build_default_tokens()
        tokens["NAME"]["UTAH"] = _NAME_REL
        tokens["NAME"]["EMPTY"] = "assets/chara/EMPTY"
        tok.save_tokens(self.project, tokens)
        publish_light_asset(_asset(), self.project, fmt="usd",
                            dest_dir=self.project / _NAME_REL / "model" / "null",
                            base_name="CHAR_GEO_UTAH_null")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _assemble(self) -> None:
        recipe = {"target": {"kind": "assembly", "asset": "ENV_forest"},
                  "components": [{"asset": "UTAH", "instance": "utah_01"},
                                 {"asset": "UTAH", "instance": "utah_02"}]}
        assemble(recipe, resolver=FluxResolver(self.project),
                 dest_dir=self.project / "usd" / "assembly")

    def test_component_listed_ok(self) -> None:
        lib = build_library(self.project)
        self.assertEqual([c["name"] for c in lib["components"]], ["UTAH"])
        comp = lib["components"][0]
        self.assertEqual(comp["state"], "ok")
        self.assertEqual(comp["version"], "v001")
        self.assertEqual(comp["slots"]["model"]["task"], "GEO")

    def test_assembly_instances_and_used_by(self) -> None:
        self._assemble()
        lib = build_library(self.project)
        self.assertEqual(len(lib["assemblies"]), 1)
        asm = lib["assemblies"][0]
        self.assertEqual(asm["name"], "ENV_forest")
        self.assertEqual([i["component"] for i in asm["instances"]], ["UTAH", "UTAH"])
        self.assertTrue(all(i["follows_last"] and not i["broken"] for i in asm["instances"]))
        self.assertEqual(lib["components"][0]["used_by"], ["ENV_forest"])

    def test_broken_link_and_missing_component(self) -> None:
        self._assemble()
        usd_dir = self.project / _NAME_REL / "usd"
        shutil.rmtree(usd_dir)
        lib = build_library(self.project)
        self.assertEqual(lib["components"][0]["state"], "missing")
        self.assertEqual(lib["assemblies"][0]["broken"], 2)

    def _publish_rig(self) -> None:
        publish_light_asset(_asset(), self.project, fmt="usd",
                            dest_dir=self.project / _NAME_REL / "rig" / "null",
                            base_name="CHAR_RIG_UTAH_null")

    def test_pin_survives_publish_and_can_be_cleared(self) -> None:
        self._publish_rig()                               # v002: skel from RIG
        res = refresh_component(self.project, "UTAH",
                                pins={"skel": {"task": "GEO", "instance": "null", "version": "v001"}})
        self.assertEqual(res["version"], "v003")
        self.assertEqual(res["slots"]["skel"]["task"], "GEO")
        self._publish_rig()                               # new RIG publish keeps the pin
        comp = build_library(self.project)["components"][0]
        self.assertEqual(comp["slots"]["skel"]["task"], "GEO")
        self.assertEqual(comp["slots"]["skel"]["pin"]["version"], "v001")
        self.assertEqual(comp["state"], "ok")
        res = refresh_component(self.project, "UTAH", pins={"skel": None})
        self.assertEqual(res["slots"]["skel"]["task"], "RIG")
        self.assertNotIn("pin", res["slots"]["skel"])

    def test_exclude_slot(self) -> None:
        res = refresh_component(self.project, "UTAH", pins={"skel": {"exclude": True}})
        self.assertNotIn("skel", res["slots"])
        comp = build_library(self.project)["components"][0]
        self.assertEqual(comp["slots"]["skel"]["pin"], {"exclude": True})
        with self.assertRaises(ValueError):
            refresh_component(self.project, "UTAH", pins={"model": {"exclude": True}})

    def test_relink_instance_to_frozen_version(self) -> None:
        self._assemble()
        asm = build_library(self.project)["assemblies"][0]
        prim = asm["instances"][0]["prim"]
        res = relink_instance(self.project, asm["file"], prim, "UTAH", "v001")
        self.assertEqual(res["asset_path"], "../../assets/chara/UTAH/usd/UTAH_v001/UTAH.usda")
        inst = build_library(self.project)["assemblies"][0]["instances"]
        self.assertFalse(inst[0]["follows_last"])
        self.assertFalse(inst[0]["broken"])
        self.assertEqual(inst[0]["component"], "UTAH")
        self.assertTrue(inst[1]["follows_last"])
        with self.assertRaises(ValueError):
            relink_instance(self.project, asm["file"], prim, "UTAH", "v099")


if __name__ == "__main__":
    unittest.main()
