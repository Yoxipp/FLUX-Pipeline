# Read-only composition of a published USD entry (USD page "Composition" view).

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from features.folder_manager import tokens as tok
from features.usd_assembler import assembly_v2 as av
from features.usd_assembler.component_auto import add_proposed
from features.usd_assembler.inspect import composition
from features.usd_export import LightAsset, MeshData, SkeletonData, publish_light_asset

_ID = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)


def _asset() -> LightAsset:
    return LightAsset(
        asset="tmp",
        skeleton=SkeletonData(joints=["Root"], bind_transforms=[_ID], rest_transforms=[_ID]),
        meshes=[MeshData(name="body", points=[(0, 0, 0), (1, 0, 0), (1, 1, 0)],
                         face_vertex_counts=[3], face_vertex_indices=[0, 1, 2])],
    )


class Composition(unittest.TestCase):
    def setUp(self) -> None:
        # deterministic: the proxy hook is an opt-in of the project, not of these tests
        env = mock.patch.dict(os.environ, {"FLUX_PROXY_USD": "0"})
        env.start()
        self.addCleanup(env.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "PROJ"
        self.project.mkdir()
        tokens = tok.build_default_tokens()
        tokens["NAME"]["UTAH"] = "assets/chara/UTAH"
        tok.save_tokens(self.project, tokens)
        for instance in ("null", "B"):
            publish_light_asset(_asset(), self.project, fmt="usda",
                                dest_dir=self.project / "assets/chara/UTAH/model" / instance,
                                base_name=f"CHAR_GEO_UTAH_{instance}")
        add_proposed(self.project, "UTAH", ["GEO"])      # created by hand (ADR 0023)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_component_tree_layers_and_variants(self) -> None:
        comp = composition(self.project / "assets/chara/UTAH/usd/UTAH_LAST.usda")
        self.assertEqual(comp["default_prim"], "UTAH")
        tree = comp["tree"]
        self.assertEqual((tree["path"], tree["kind"], tree["type"]), ("/UTAH", "component", "SkelRoot"))
        self.assertEqual(tree["arcs"][0]["arc"], "payload")
        self.assertEqual(sorted(tree["variant_sets"]), ["geo_B", "geo_null"])      # one per file
        self.assertEqual(sorted(tree["variant_sets"]["geo_B"]["variants"]), ["off", "on"])
        self.assertEqual(tree["variant_sets"]["geo_B"]["selection"], "on")
        names = [c["name"] for c in tree["children"]]
        self.assertIn("geo", names)
        geo = next(c for c in tree["children"] if c["name"] == "geo")
        self.assertEqual([c["name"] for c in geo["children"]], ["render"])
        self.assertTrue(comp["layers"][0]["root"])
        self.assertTrue(any(entry["path"].endswith("UTAH_model.usda") for entry in comp["layers"]))

    def test_assembly_stops_at_instances(self) -> None:
        av.create_assembly(self.project, "TOWN")
        av.edit_assembly(self.project, "TOWN", [{"op": "add", "component": "UTAH"}])
        comp = composition(av.assembly_dir(self.project, "TOWN") / "TOWN_LAST.usda")
        town = comp["tree"]
        self.assertEqual(town["kind"], "assembly")
        inst = town["children"][0]["children"][0]
        self.assertEqual((inst["name"], inst["kind"], inst["instanceable"]), ("UTAH_01", "component", True))
        self.assertEqual(inst["children"], [])          # an instance is not traversed
        self.assertTrue(inst["truncated"])
        self.assertEqual(inst["arcs"][0]["arc"], "reference")

    def test_missing_file(self) -> None:
        with self.assertRaises(ValueError):
            composition(self.project / "nope.usda")


if __name__ == "__main__":
    unittest.main()
