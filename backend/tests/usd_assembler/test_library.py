# USD_ASSEMBLER_V2 A2: library of existing components (created by hand, ADR 0023) and
# assemblies, with state, used_by, instance -> component mapping and broken links.

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from features.folder_manager import tokens as tok
from features.usd_assembler import component_auto as ca
from features.usd_assembler import assembly_v2 as av
from features.usd_assembler.library import _tokens_of, build_library, relink_instance, token_keys
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
        ca.add_proposed(self.project, "UTAH", ["GEO", "RIG"])     # v001 created, v002 filled

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
        self.assertEqual((comp["state"], comp["version"], comp["departments"]), ("ok", "v002", ["GEO", "RIG"]))
        self.assertEqual([(f["department"], f["resolved_version"], f["composed_version"]) for f in comp["files"]],
                         [("GEO", "v001", "v001")])
        self.assertEqual(comp["class"], "CHAR")   # deep link to Production
        self.assertEqual(lib["creatable"], ["EMPTY"])
        self.assertIn("GEO", lib["departments"])
        self.assertNotIn("MULT", lib["departments"])

    def test_published_asset_without_component_is_not_listed(self) -> None:
        publish_light_asset(_asset(), self.project, fmt="usd",
                            dest_dir=self.project / "assets/chara/EMPTY/model/null",
                            base_name="CHAR_GEO_EMPTY_null")
        lib = build_library(self.project)
        self.assertEqual([c["name"] for c in lib["components"]], ["UTAH"])
        self.assertEqual(lib["creatable"], ["EMPTY"])

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
        self.assertEqual(lib["components"], [])
        self.assertEqual(lib["creatable"], ["EMPTY", "UTAH"])
        self.assertEqual(lib["assemblies"][0]["broken"], 2)

    def _publish_rig(self) -> None:
        publish_light_asset(_asset(), self.project, fmt="usd",
                            dest_dir=self.project / _NAME_REL / "rig" / "null",
                            base_name="CHAR_RIG_UTAH_null")

    def test_frozen_file_survives_publish_and_proposals_are_listed(self) -> None:
        self._publish_rig()
        comp = build_library(self.project)["components"][0]
        self.assertEqual([p["base"] for p in comp["proposed"]], ["CHAR_RIG_UTAH_null"])
        recipe = ca.current_recipe(self.project, "UTAH")
        recipe["files"][0]["version"] = "v001"
        ca.save_component(self.project, "UTAH", recipe)
        publish_light_asset(_asset(), self.project, fmt="usd",
                            dest_dir=self.project / _NAME_REL / "model" / "null",
                            base_name="CHAR_GEO_UTAH_null")      # GEO v002
        comp = build_library(self.project)["components"][0]
        self.assertEqual((comp["files"][0]["composed_version"], comp["state"]), ("v001", "ok"))

    def test_removed_file_leaves_the_component(self) -> None:
        recipe = ca.current_recipe(self.project, "UTAH")
        recipe["files"] = []
        res = ca.save_component(self.project, "UTAH", recipe)
        self.assertEqual(res["files"], {})
        comp = build_library(self.project)["components"][0]
        self.assertEqual((comp["state"], [p["base"] for p in comp["proposed"]]), ("empty", ["CHAR_GEO_UTAH_null"]))

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


class TokenSorting(unittest.TestCase):
    """Retake 03: components and assemblies carry their classification tokens (from
    tokens.json, never from a prim name / vNNN / LAST) for sorting and filtering."""

    def _tokens(self) -> dict:
        tokens = tok.build_default_tokens()
        tokens["BIOME"] = {"DESERT": "assets/props", "DUNE": "assets/props/dunes"}
        tokens["NAME"].update({"UTAH": "assets/chara/UTAH", "BOB": "assets/chara/BOB",
                               "ROCK": "assets/props/ROCK", "SAND": "assets/props/dunes/SAND",
                               "GHOST": "misc/GHOST", "TOWN": "assets/sets/TOWN"})
        return tokens

    def test_tokens_of_cases(self) -> None:
        tokens = self._tokens()
        # same value for two assets, several categories, longest match wins
        self.assertEqual(_tokens_of(tokens, "UTAH"), {"CLASS": "CHAR"})
        self.assertEqual(_tokens_of(tokens, "BOB"), {"CLASS": "CHAR"})
        self.assertEqual(_tokens_of(tokens, "ROCK"), {"CLASS": "PROPS", "BIOME": "DESERT"})
        self.assertEqual(_tokens_of(tokens, "SAND"), {"CLASS": "PROPS", "BIOME": "DUNE"})
        # outside every token folder, or unknown to tokens.json: no token
        self.assertEqual(_tokens_of(tokens, "GHOST"), {})
        self.assertEqual(_tokens_of(tokens, "NOPE"), {})
        # shot templates and departments never classify an asset
        self.assertNotIn("TYPE", _tokens_of(tokens, "UTAH"))

    def test_token_keys_class_first(self) -> None:
        entries = [{"tokens": {"BIOME": "DESERT", "CLASS": "PROPS"}}, {"tokens": {}}, {}]
        self.assertEqual(token_keys(entries), ["CLASS", "BIOME"])
        self.assertEqual(token_keys([]), [])

    def test_library_components_assemblies_and_mixed(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        project = Path(tmp.name) / "PROJ"
        project.mkdir()
        tok.save_tokens(project, self._tokens())
        for name, cls in (("UTAH", "CHAR"), ("ROCK", "PROPS"), ("GHOST", "CHAR")):
            rel = self._tokens()["NAME"][name]
            publish_light_asset(_asset(), project, fmt="usd", dest_dir=project / rel / "model" / "null",
                                base_name=f"{cls}_GEO_{name}_null")
            ca.add_proposed(project, name, ["GEO"])
        av.create_assembly(project, "TOWN")
        lib = build_library(project)
        comps = {c["name"]: c["tokens"] for c in lib["components"]}
        self.assertEqual(comps, {"UTAH": {"CLASS": "CHAR"}, "ROCK": {"CLASS": "PROPS", "BIOME": "DESERT"},
                                 "GHOST": {}})
        self.assertEqual({a["name"]: a["tokens"] for a in lib["assemblies"]}, {"TOWN": {"CLASS": "SET"}})
        self.assertEqual(lib["token_keys"], ["CLASS", "BIOME"])
