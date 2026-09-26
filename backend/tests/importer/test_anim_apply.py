# 2026-09-26: one FLUX Anim node applies several characters' animations (shot
# animations and asset clips) with an optional rotation noise.

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pxr import Gf, Sdf, Usd, UsdSkel

from features.folder_manager import tokens as tok
from features.importer.anim_apply import anim_file, anim_info, build_anim_layer, list_anims
from features.usd_assembler.component_auto import add_proposed
from features.usd_export import publish_light_asset
from tests.usd_export.test_shot_anim import _REL, _anim, _rig, _skinned_rig


class AnimApply(unittest.TestCase):
    def setUp(self) -> None:
        env = mock.patch.dict(os.environ, {"FLUX_PROXY_USD": "0"})
        env.start()
        self.addCleanup(env.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name) / "PROJ"
        self.project.mkdir()
        tokens = tok.build_default_tokens()
        tokens["NAME"]["DINGO"] = _REL
        tokens["SEQ"]["SEQ001"] = "shot/SEQ001"
        tok.save_tokens(self.project, tokens)
        publish_light_asset(_rig(), self.project, fmt="usda", dest_dir=self.project / _REL / "model" / "null",
                            base_name="CHAR_GEO_DINGO_null")
        add_proposed(self.project, "DINGO", ["GEO", "RIG"])
        publish_light_asset(_skinned_rig(), self.project, fmt="usda", dest_dir=self.project / _REL / "rig" / "null",
                            base_name="CHAR_RIG_DINGO_null")
        add_proposed(self.project, "DINGO")
        publish_light_asset(_rig(_anim()), self.project, fmt="usda",
                            dest_dir=self.project / "shot/SEQ001/SHOT010/anim/dingo",
                            base_name="SEQ001_SHOT010_ANIM_DINGO")
        publish_light_asset(_rig(_anim()), self.project, fmt="usda",
                            dest_dir=self.project / _REL / "anim" / "walk",
                            base_name="CHAR_ANIM_DINGO_walk")

    def test_shot_animations_and_asset_clips_are_listed(self) -> None:
        items = {i["key"]: i for i in list_anims(self.project)}
        self.assertEqual(items["SEQ001_SHOT010_ANIM_DINGO"]["kind"], "shot")
        self.assertEqual(items["CHAR_ANIM_DINGO_walk"]["kind"], "clip")
        self.assertEqual(items["CHAR_ANIM_DINGO_walk"]["clip"], "walk")
        info = anim_info(anim_file(items["CHAR_ANIM_DINGO_walk"]))
        self.assertEqual((info["root"], info["joints"], info["start"], info["end"]), ("DINGO", 1, 1001.0, 1003.0))

    def _stage(self, layer: str) -> Usd.Stage:
        stage = Usd.Stage.CreateInMemory()
        # The scene runs at the animation's fps (FLUX Anim "plage auto" sets it): a 24 fps
        # stage would rescale a 25 fps layer.
        stage.SetTimeCodesPerSecond(25.0)
        stage.SetFramesPerSecond(25.0)
        stage.DefinePrim("/assets/DINGO").GetReferences().AddReference(
            str(self.project / _REL / "usd" / "DINGO_LAST.usda"))
        stage.DefinePrim("/assets/DINGO_02").GetReferences().AddReference(
            str(self.project / _REL / "usd" / "DINGO_LAST.usda"))
        stage.GetRootLayer().subLayerPaths.append(layer)
        return stage

    def _hip_rotation(self, stage: Usd.Stage, prim: str, t: float) -> Gf.Quatf:
        anim = UsdSkel.Animation(stage.GetPrimAtPath(prim + "/skel/Anim"))
        return anim.GetRotationsAttr().Get(t)[0]

    def test_two_characters_one_layer_with_noise(self) -> None:
        items = {i["key"]: i for i in list_anims(self.project)}
        out = Path(self._tmp.name) / "hip" / "flux_anim.usda"
        rows = [{"file": anim_file(items["SEQ001_SHOT010_ANIM_DINGO"]), "target": "/assets/DINGO"},
                {"file": anim_file(items["CHAR_ANIM_DINGO_walk"]), "target": "/assets/DINGO_02"}]
        res = build_anim_layer(out, rows)
        self.assertEqual(res["range"], {"start": 1001.0, "end": 1003.0, "fps": 25.0})
        clean = self._stage(res["layer"])
        q = self._hip_rotation(clean, "/assets/DINGO_02", 1002.0)
        self.assertAlmostEqual(q.GetImaginary()[1], 0.3826834, places=5)
        # The skeleton of each character plays its animation.
        for prim in ("/assets/DINGO", "/assets/DINGO_02"):
            skel = UsdSkel.Skeleton(clean.GetPrimAtPath(prim + "/skel/Skeleton"))
            cache = UsdSkel.Cache()
            cache.Populate(UsdSkel.Root(clean.GetPrimAtPath(prim)), Usd.PrimDefaultPredicate)
            self.assertTrue(cache.GetSkelQuery(skel).GetAnimQuery(), prim)

        noisy = build_anim_layer(out, rows, noise={"amplitude": 10.0, "frequency": 1.0, "seed": 3})
        self.assertTrue(all(r["noise"] for r in noisy["rows"]))
        stage = self._stage(noisy["layer"])
        a = self._hip_rotation(stage, "/assets/DINGO", 1002.0)
        b = self._hip_rotation(stage, "/assets/DINGO_02", 1002.0)
        self.assertNotEqual(tuple(a.GetImaginary()), tuple(q.GetImaginary()))
        self.assertNotEqual(tuple(a.GetImaginary()), tuple(b.GetImaginary()))   # own noise each

    def test_a_bad_row_is_reported_not_raised(self) -> None:
        res = build_anim_layer(Path(self._tmp.name) / "x.usda",
                               [{"file": "", "target": "/assets/DINGO"}, {"file": "a.usd", "target": "oops"}])
        self.assertEqual([bool(r["error"]) for r in res["rows"]], [True, True])
        self.assertIsNone(res["range"])
        self.assertIsNotNone(Sdf.Layer.FindOrOpen(res["layer"]))


if __name__ == "__main__":
    unittest.main()
