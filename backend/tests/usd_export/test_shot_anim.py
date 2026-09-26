# 2026-09-18: a skeleton animation is published per shot as SEQ_SHOT_ANIM_<NAME>,
# motion only (moving joints + frame range + fps), and animates the asset it is
# referenced onto.

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pxr import Sdf, Usd, UsdSkel

from features.usd_assembler.component_auto import add_proposed
from features.folder_manager import tokens as tok
from features.usd_export import AnimData, LightAsset, MeshData, SkeletonData, publish_light_asset
from features.usd_export.departments import character_name, contribution, is_motion_only

_ID = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
_JOINTS = ["Root", "Root/Hip"]
_REL = "assets/chara/DINGO"


def _rig(anim: AnimData | None = None) -> LightAsset:
    return LightAsset(
        asset="tmp",
        skeleton=SkeletonData(joints=_JOINTS, bind_transforms=[_ID] * 2, rest_transforms=[_ID] * 2),
        meshes=[MeshData(name="body", points=[(0, 0, 0), (1, 0, 0), (1, 1, 0)],
                         face_vertex_counts=[3], face_vertex_indices=[0, 1, 2])],
        anim=anim,
    )


def _skinned_rig() -> LightAsset:
    rig = _rig()
    body = rig.meshes[0]
    body.joint_indices, body.joint_weights, body.influences_per_point = [1, 1, 0], [1.0, 1.0, 1.0], 1
    return rig


def _anim(joints=("Root/Hip",)) -> AnimData:
    n = len(joints)
    return AnimData(joints=list(joints), times=[1001.0, 1002.0, 1003.0],
                    translations=[[(0, 0, 0)] * n] * 3,
                    rotations=[[(0, 0, 0, 1)] * n, [(0, 0.3826834, 0, 0.9238795)] * n,
                               [(0, 0.7071068, 0, 0.7071068)] * n],
                    scales=[[(1, 1, 1)] * n] * 3, fps=25.0)


class Naming(unittest.TestCase):
    def test_the_character_is_everything_after_the_type(self) -> None:
        c = contribution("SEQ001_SHOT010_ANIM_DINGO_02")
        self.assertEqual((c["kind"], c["type"], c["name"]), ("shot", "ANIM", "DINGO_02"))
        self.assertTrue(is_motion_only(c))
        self.assertFalse(is_motion_only(contribution("SEQ001_SHOT010_FX_null")))
        self.assertTrue(is_motion_only(contribution("CHAR_ANIM_DINGO_null")))
        self.assertIsNone(contribution("SEQ001_SHOT010_ANIM_null")["name"])

    def test_the_character_name_is_the_longest_known_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tokens = tok.build_default_tokens()
            tokens["NAME"].update({"DINGO": _REL, "HERO_A": "assets/chara/HERO_A"})
            tok.save_tokens(Path(tmp), tokens)
            for base, name in (("SEQ001_SHOT010_ANIM_DINGO_02", "DINGO"),
                               ("SEQ001_SHOT010_ANIM_HERO_A", "HERO_A")):
                self.assertEqual(character_name(contribution(base), Path(tmp)), name)


class ShotAnimPublish(unittest.TestCase):
    def setUp(self) -> None:
        env = mock.patch.dict(os.environ, {"FLUX_PROXY_USD": "1"})
        env.start()
        self.addCleanup(env.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name) / "PROJ"
        self.project.mkdir()
        tokens = tok.build_default_tokens()
        tokens["NAME"]["DINGO"] = _REL
        tok.save_tokens(self.project, tokens)
        # The asset: geometry (GEO), then skeleton + skin weights (RIG, ADR 0034).
        publish_light_asset(_rig(), self.project, fmt="usda",
                            dest_dir=self.project / _REL / "model" / "null",
                            base_name="CHAR_GEO_DINGO_null", user="adam")
        add_proposed(self.project, "DINGO", ["GEO", "RIG"])  # components are created by hand (ADR 0023)
        self.rig_res = publish_light_asset(_skinned_rig(), self.project, fmt="usda",
                                           dest_dir=self.project / _REL / "rig" / "null",
                                           base_name="CHAR_RIG_DINGO_null", user="adam")
        add_proposed(self.project, "DINGO")
        self.dest = self.project / "shot" / "SEQ001" / "SHOT010" / "anim" / "dingo"

    def _publish(self, anim: AnimData | None = None) -> dict:
        return publish_light_asset(_rig(anim or _anim()), self.project, fmt="usda",
                                   dest_dir=self.dest, base_name="SEQ001_SHOT010_ANIM_DINGO",
                                   user="adam")

    def test_only_the_motion_is_published(self) -> None:
        res = self._publish()
        self.assertEqual(sorted(res["layers"]), ["anim", "root"])
        self.assertEqual(res["warnings"][0][:9], "geometrie")
        layer = Sdf.Layer.FindOrOpen(str(res["layers"]["anim"]))
        self.assertEqual(layer.defaultPrim, "DINGO")
        self.assertEqual(layer.GetPrimAtPath("/DINGO").specifier, Sdf.SpecifierOver)
        self.assertIsNotNone(layer.GetPrimAtPath("/DINGO/skel/Anim"))
        self.assertIsNone(layer.GetPrimAtPath("/DINGO/skel/Skeleton"))
        self.assertIsNone(layer.GetPrimAtPath("/DINGO/geo"))
        root = Sdf.Layer.FindOrOpen(str(res["version_root"]))
        self.assertEqual((root.startTimeCode, root.endTimeCode, root.timeCodesPerSecond),
                         (1001.0, 1003.0, 25.0))
        # No proxy for a motion (no render mesh): no stub file either.
        self.assertEqual(list(res["folder"].glob("*.proxy.usda")), [])

    def test_referenced_on_the_asset_it_animates_it(self) -> None:
        res = self._publish()
        asset = self.project / _REL / "usd" / "DINGO_LAST.usda"
        stage = Usd.Stage.CreateInMemory()
        prim = stage.DefinePrim("/assets/DINGO")
        prim.GetReferences().AddReference(str(asset))
        prim.GetReferences().AddReference(str(res["root"]))
        skel = UsdSkel.Skeleton(stage.GetPrimAtPath("/assets/DINGO/skel/Skeleton"))
        query = UsdSkel.Cache().GetSkelQuery(skel)
        self.assertTrue(query.GetAnimQuery())
        self.assertEqual(list(query.GetAnimQuery().GetJointOrder()), ["Root/Hip"])

    def test_the_rig_puts_its_weights_on_the_model_geometry(self) -> None:
        # ADR 0034: the RIG layer overrides the model's mesh and its proxy with the skin.
        self.assertFalse([w for w in self.rig_res["warnings"] if "GEO" in w], self.rig_res["warnings"])
        stage = Usd.Stage.Open(str(self.project / _REL / "usd" / "DINGO_LAST.usda"))
        self.assertEqual(stage.GetPrimAtPath("/DINGO").GetTypeName(), "SkelRoot")
        for path in ("/DINGO/geo/render/body", "/DINGO/geo/proxy/body"):
            binding = UsdSkel.BindingAPI(stage.GetPrimAtPath(path))
            self.assertEqual(list(binding.GetJointIndicesPrimvar().Get()), [1, 1, 0], path)
            self.assertEqual(binding.GetSkeletonRel().GetTargets(), [Sdf.Path("/DINGO/skel/Skeleton")])
        # The rig file itself carries no geometry, only overrides.
        layer = Sdf.Layer.FindOrOpen(str(self.rig_res["layers"]["skel"]))
        self.assertEqual(layer.GetPrimAtPath("/DINGO/geo/render/body").specifier, Sdf.SpecifierOver)
        self.assertNotIn("model", self.rig_res["layers"])

    def test_the_rig_finds_the_geo_without_a_component(self) -> None:
        # Live 2026-09-26 (MARIE): GEO published, no component created yet (ADR 0023):
        # the RIG reads the GEO LAST itself, no warning, the proxy gets its weights.
        tokens = tok.load_tokens(self.project)
        tokens["NAME"]["MARIE"] = "assets/chara/MARIE"
        tok.save_tokens(self.project, tokens)
        publish_light_asset(_rig(), self.project, fmt="usda",
                            dest_dir=self.project / "assets/chara/MARIE/model/null",
                            base_name="CHAR_GEO_MARIE_null", user="adam")
        res = publish_light_asset(_skinned_rig(), self.project, fmt="usda",
                                  dest_dir=self.project / "assets/chara/MARIE/rig/null",
                                  base_name="CHAR_RIG_MARIE_null", user="adam")
        self.assertFalse([w for w in res["warnings"] if "GEO" in w], res["warnings"])
        layer = Sdf.Layer.FindOrOpen(str(res["layers"]["skel"]))
        self.assertIsNotNone(layer.GetPrimAtPath("/MARIE/geo/proxy/body"))

    def test_an_asset_clip_checks_the_rig_without_a_component(self) -> None:
        # Live 2026-09-26: CHAR_ANIM_MARIE_SMOOTH warned "squelette non verifie" while the
        # RIG was published: the check read the component only.
        tokens = tok.load_tokens(self.project)
        tokens["NAME"]["MARIE"] = "assets/chara/MARIE"
        tok.save_tokens(self.project, tokens)
        publish_light_asset(_skinned_rig(), self.project, fmt="usda",
                            dest_dir=self.project / "assets/chara/MARIE/rig/null",
                            base_name="CHAR_RIG_MARIE_null", user="adam")
        res = publish_light_asset(_rig(_anim(joints=("Root/Tail",))), self.project, fmt="usda",
                                  dest_dir=self.project / "assets/chara/MARIE/anim/smooth",
                                  base_name="CHAR_ANIM_MARIE_SMOOTH", user="adam")
        self.assertFalse([w for w in res["warnings"] if "non verifie" in w], res["warnings"])
        self.assertTrue(any("Root/Tail" in w for w in res["warnings"]), res["warnings"])

    def test_joints_missing_from_the_rig_are_reported(self) -> None:
        res = self._publish(_anim(joints=("Root/Tail",)))
        self.assertTrue(any("absent" in w and "Root/Tail" in w for w in res["warnings"]), res["warnings"])

    def test_a_rig_imported_in_maya_keeps_matching(self) -> None:
        # mayaUsd adds a root joint named after the Skeleton prim: Skeleton/Root/Hip.
        res = self._publish(_anim(joints=("Skeleton/Root/Hip",)))
        layer = Sdf.Layer.FindOrOpen(str(res["layers"]["anim"]))
        joints = layer.GetAttributeAtPath("/DINGO/skel/Anim.joints").default
        self.assertEqual(list(joints), ["Root/Hip"])
        self.assertTrue(any("Skeleton" in w for w in res["warnings"]))

    def test_the_anim_node_lists_it_by_tokens(self) -> None:
        from features.importer.shot_anim import list_shot_anims

        tokens = tok.load_tokens(self.project)
        tokens.setdefault("SEQ", {})["SEQ001"] = "shot/SEQ001"
        tok.save_tokens(self.project, tokens)
        self._publish()
        self._publish()
        items = list_shot_anims(self.project)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual((item["seq"], item["shot"], item["task"], item["character"], item["name"]),
                         ("SEQ001", "SHOT010", "ANIM", "DINGO", "DINGO"))
        self.assertEqual(list(item["versions"]), ["v001", "v002"])
        self.assertTrue(item["last"].endswith("SEQ001_SHOT010_ANIM_DINGO_LAST.usda"))

    def test_the_houdini_anim_node_scripts_are_valid_python(self) -> None:
        from dcc.houdini.hda import flux_anim_hda

        compile(flux_anim_hda.BOOTSTRAP, "bootstrap", "exec")
        compile(flux_anim_hda.MODULE_FUNCTIONS, "module", "exec")
        compile(flux_anim_hda._build_code("C:/tmp/flux_anim.hda"), "build", "exec")

    def test_no_motion_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            publish_light_asset(_rig(None), self.project, fmt="usda", dest_dir=self.dest,
                                base_name="SEQ001_SHOT010_ANIM_DINGO")


if __name__ == "__main__":
    unittest.main()
