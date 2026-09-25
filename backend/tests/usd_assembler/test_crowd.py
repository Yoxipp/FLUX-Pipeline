# A6 / A7 (ADR 0022): shared skeletons, animation clips and the shot crowd layer.

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pxr import Sdf, Usd, UsdSkel

from features.folder_manager import tokens as tok
from features.usd_assembler import crowd
from features.usd_assembler import shot_stage as ss
from features.usd_assembler.component_auto import add_proposed
from features.usd_export import AnimData, LightAsset, MeshData, SkeletonData, publish_light_asset

_ID = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
_BIPED = ["Root", "Root/Hip", "Root/Hip/Knee"]


def _asset(joints=_BIPED, anim: AnimData | None = None, points=((0, 0, 0), (1, 0, 0), (1, 1, 0))) -> LightAsset:
    return LightAsset(
        asset="tmp",
        skeleton=SkeletonData(joints=list(joints), bind_transforms=[_ID] * len(joints),
                              rest_transforms=[_ID] * len(joints)),
        meshes=[MeshData(name="body", points=list(points), face_vertex_counts=[3],
                         face_vertex_indices=[0, 1, 2])],
        anim=anim,
    )


def _anim(joint="Root/Hip") -> AnimData:
    rots = [[(0, 0, 0, 1)], [(0, 0.3826834, 0, 0.9238795)], [(0, 0.7071068, 0, 0.7071068)]]
    return AnimData(joints=[joint], times=[1.0, 2.0, 3.0], translations=[[(0, 0, 0)]] * 3,
                    rotations=rots, scales=[[(1, 1, 1)]] * 3, fps=24.0)


class Crowd(unittest.TestCase):
    def setUp(self) -> None:
        env = mock.patch.dict(os.environ, {"FLUX_PROXY_USD": "0"})
        env.start()
        self.addCleanup(env.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name) / "PROJ"
        self.project.mkdir()
        tokens = tok.build_default_tokens()
        for name in ("BOB", "TIM", "DOG"):
            tokens["NAME"][name] = f"assets/chara/{name}"
        tokens["SEQ"]["SEQ001"] = "shot/SEQ001"
        tokens["SHOT"]["SEQ001/SHOT010"] = "shot/SEQ001/SHOT010"
        tok.save_tokens(self.project, tokens)
        self._geo("BOB", _asset())
        self._geo("TIM", _asset(points=((0, 0, 0), (2, 0, 0), (2, 2, 0))))
        self._geo("DOG", _asset(joints=["Root", "Root/Tail"]))
        publish_light_asset(_asset(anim=_anim()), self.project, fmt="usda",
                            dest_dir=self.project / "assets/chara/BOB/anim/walk",
                            base_name="CHAR_ANIM_BOB_walk", user="adam")

    def _geo(self, name: str, asset: LightAsset) -> None:
        publish_light_asset(asset, self.project, fmt="usda",
                            dest_dir=self.project / f"assets/chara/{name}/model/null",
                            base_name=f"CHAR_GEO_{name}_null", user="adam")
        add_proposed(self.project, name, ["GEO"])      # components are created by hand (ADR 0023)

    def test_same_joints_same_signature(self) -> None:
        self.assertEqual(crowd.skeleton_signature(_BIPED), crowd.skeleton_signature(list(_BIPED)))
        self.assertNotEqual(crowd.skeleton_signature(_BIPED), crowd.skeleton_signature(_BIPED[:2]))
        self.assertEqual(crowd.skeleton_signature([]), "")

    def test_assets_sharing_a_rig_and_their_clips(self) -> None:
        compat = crowd.compatibility(self.project)
        self.assertEqual(compat["assets"]["BOB"]["compatible"], ["TIM"])
        self.assertEqual(compat["assets"]["DOG"]["compatible"], [])
        self.assertEqual(compat["assets"]["BOB"]["joint_count"], 3)
        # The walk clip moves Root/Hip: it fits BOB and TIM, not DOG.
        self.assertEqual(compat["assets"]["TIM"]["clips"], ["CHAR_ANIM_BOB_walk"])
        self.assertEqual(compat["assets"]["DOG"]["clips"], [])
        clip = compat["clips"][0]
        self.assertEqual((clip["asset"], clip["clip"], clip["range"]), ("BOB", "walk", [1, 3]))

    def test_the_publish_writes_the_signature(self) -> None:
        root = self.project / "assets/chara/BOB/model/null/CHAR_GEO_BOB_null_v001/CHAR_GEO_BOB_null.usda"
        flux = dict(Sdf.Layer.FindOrOpen(str(root)).customLayerData)["flux"]
        self.assertEqual(flux["skeleton_signature"], crowd.skeleton_signature(_BIPED))
        self.assertEqual(flux["joint_count"], 3)
        self.assertEqual(crowd.component_skeleton(self.project, "BOB")["signature"], flux["skeleton_signature"])

    def test_weights_draw_more_of_an_asset_and_a_clip(self) -> None:
        # 2026-09-25: "pouvoir choisir si on veut plus de tel asset, plus de telle anim".
        pts = [{"p": [i, 0, 0]} for i in range(400)]
        a = crowd.plan_agents(pts, ["BOB", "TIM"], ["walk", "run"], seed=3,
                              component_weights={"BOB": 3, "TIM": 1}, clip_weights={"walk": 1, "run": 0})
        bob = sum(1 for x in a if x["component"] == "BOB")
        self.assertTrue(250 < bob < 350, bob)
        self.assertEqual({x["clip"] for x in a}, {"walk"})
        a = crowd.plan_agents(pts, ["BOB", "TIM"], [], seed=3, component_weights={"BOB": 0, "TIM": 1})
        self.assertEqual({x["component"] for x in a}, {"TIM"})

    def test_an_agent_only_plays_a_clip_of_its_rig(self) -> None:
        pts = [{"p": [i, 0, 0]} for i in range(60)]
        a = crowd.plan_agents(pts, ["BOB", "DOG"], ["walk", "trot"], seed=1,
                              fits={"BOB": {"walk"}, "DOG": {"trot"}})
        for x in a:
            self.assertEqual(x["clip"], {"BOB": "walk", "DOG": "trot"}[x["component"]])
        a = crowd.plan_agents(pts, ["BOB"], ["trot"], seed=1, fits={"BOB": {"walk"}})
        self.assertEqual({x["clip"] for x in a}, {""})

    def test_agents_are_deterministic_with_a_seed(self) -> None:
        pts = [{"p": [i, 0, 0]} for i in range(20)]
        a = crowd.plan_agents(pts, ["BOB", "TIM"], ["c"], seed=7, offset=(0, 10), speed=(0.5, 2))
        b = crowd.plan_agents(pts, ["BOB", "TIM"], ["c"], seed=7, offset=(0, 10), speed=(0.5, 2))
        self.assertEqual(a, b)
        self.assertEqual({x["component"] for x in a}, {"BOB", "TIM"})
        self.assertTrue(all(0 <= x["offset"] <= 10 and 0.5 <= x["speed"] <= 2 for x in a))
        self.assertNotEqual(a, crowd.plan_agents(pts, ["BOB", "TIM"], ["c"], seed=8, offset=(0, 10)))
        with self.assertRaises(ValueError):
            crowd.plan_agents(pts, [], [])

    def test_preview_layer_animates_each_agent_with_its_offset(self) -> None:
        pts = [{"p": [0, 0, 0]}, {"p": [5, 0, 0], "ry": 90}]
        res = crowd.build_crowd(self.project, "SEQ001", "SHOT010", "crowd", pts, components=["TIM"],
                                clips=["CHAR_ANIM_BOB_walk"], seed=1, offset=(4, 4), speed=(2, 2))
        self.assertEqual(res["agents"], 2)
        layer = Sdf.Layer.FindOrOpen(str(res["path"]))
        ref = layer.GetPrimAtPath("/crowd/crowd/agent_0001").referenceList.prependedItems[0]
        self.assertFalse(os.path.isabs(ref.assetPath))
        anim_ref = layer.GetPrimAtPath("/crowd/crowd/agent_0001/crowd_anim").referenceList.prependedItems[0]
        # Clip starts at frame 1: speed pivots on it (offset 4 + 1 * (1 - 0.5)).
        self.assertEqual(anim_ref.layerOffset, Sdf.LayerOffset(4.5, 0.5))
        stage = Usd.Stage.Open(str(res["path"]))
        agent = stage.GetPrimAtPath("/crowd/crowd/agent_0002")
        self.assertTrue(agent.IsA(UsdSkel.Root))
        self.assertFalse(agent.IsInstanceable())
        cache = UsdSkel.Cache()
        cache.Populate(UsdSkel.Root(agent), Usd.PrimDefaultPredicate)
        query = cache.GetSkelQuery(UsdSkel.Skeleton(stage.GetPrimAtPath("/crowd/crowd/agent_0002/skel/Skeleton")))
        anim = query.GetAnimQuery()
        self.assertTrue(anim)
        # Speed 2, offset 4: the clip's first frame (1) plays at 1 + 4 = 5, then twice as fast.
        self.assertEqual(anim.GetJointTransformTimeSamples(), [5.0, 5.5, 6.0])
        self.assertEqual(stage.GetDefaultPrim().GetPath(), Sdf.Path("/crowd"))

    def test_publish_adds_the_crowd_layer_to_the_shot_stage(self) -> None:
        pts = [{"p": [0, 0, 0]}, {"p": [5, 0, 0]}]
        res = crowd.build_crowd(self.project, "SEQ001", "SHOT010", "crowd", pts, components=["BOB", "TIM"],
                                clips=["CHAR_ANIM_BOB_walk", "NOPE"], publish=True, user="adam")
        self.assertEqual((res["version"], res["base"]), ("v001", "SEQ001_SHOT010_CROWD"))
        self.assertIn("clip inconnu : NOPE", res["warnings"])
        self.assertIn("CROWD", tok.load_tokens(self.project)["TYPE_SHOT"])
        folder = self.project / "shot/SEQ001/SHOT010/crowd/null"  # no group = variante null
        self.assertTrue((folder / "SEQ001_SHOT010_CROWD_LAST.usda").is_file())
        stage = Usd.Stage.Open(str(ss.last_file(self.project, "SEQ001", "SHOT010")))
        self.assertTrue(any("SEQ001_SHOT010_CROWD" in layer.identifier for layer in stage.GetLayerStack()))
        self.assertTrue(stage.GetPrimAtPath("/crowd/crowd/agent_0002/geo/render/body"))
        # Frozen (ADR 0017): the published crowd references the component and clip versions.
        layer = Sdf.Layer.FindOrOpen(str(folder / "SEQ001_SHOT010_CROWD_v001" / "SEQ001_SHOT010_CROWD.usda"))
        refs = [r.assetPath for path in ("/crowd/crowd/agent_0001", "/crowd/crowd/agent_0001/crowd_anim")
                for r in layer.GetPrimAtPath(path).referenceList.prependedItems]
        self.assertTrue(refs and not any("_LAST" in r for r in refs), refs)


if __name__ == "__main__":
    unittest.main()
