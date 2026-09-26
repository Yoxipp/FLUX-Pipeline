# A6 / A7 (ADR 0022): shared skeletons, animation clips and the shot crowd layer.

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pxr import Gf, Sdf, Usd, UsdSkel, Vt

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

    def test_preview_without_shot_and_without_anim_places_static_agents(self) -> None:
        # 2026-09-26: a project without shots, no anim: the agents must still show.
        res = crowd.build_crowd(self.project, "", "", "crowd", [{"p": [1, 0, 0]}], components=["DOG"], clips=[])
        self.assertEqual(res["agents"], 1)
        self.assertEqual(Path(res["path"]).parent, self.project / "shot" / "crowd_work")
        stage = Usd.Stage.Open(str(res["path"]))
        agent = stage.GetPrimAtPath("/crowd/crowd/agent_0001")
        self.assertTrue(agent.IsValid() and agent.GetChildren())
        self.assertFalse(agent.HasRelationship("skel:animationSource"))
        with self.assertRaises(ValueError):
            crowd.build_crowd(self.project, "", "", "crowd", [{"p": [0, 0, 0]}], components=["DOG"],
                              clips=[], publish=True)

    def test_asset_without_component_uses_the_input_file(self) -> None:
        geo = Path(self._tmp.name) / "ogre.usda"
        stage = Usd.Stage.CreateNew(str(geo))
        stage.DefinePrim("/OGRE/body", "Mesh")
        stage.GetRootLayer().Save()
        res = crowd.build_crowd(self.project, "SEQ001", "SHOT010", "crowd", [{"p": [0, 0, 0]}],
                                components=["OGRE"], clips=[],
                                sources={"OGRE": {"file": geo.as_posix(), "prim": "/OGRE"}})
        self.assertEqual(res["agents"], 1)
        crowd_stage = Usd.Stage.Open(str(res["path"]))
        self.assertTrue(crowd_stage.GetPrimAtPath("/crowd/crowd/agent_0001/body").IsValid())

    def _ogre(self, run: bool = False) -> Path:
        """A component like OGRE: skinned skeleton, its walk in an "on" variant bound on the
        skeleton itself (what component_auto writes for an ANIM file with a rig target)."""
        tokens = tok.load_tokens(self.project)
        tokens["NAME"]["OGRE"] = "assets/chara/OGRE"
        tok.save_tokens(self.project, tokens)
        walk = next((self.project / "assets/chara/BOB/anim/walk").glob("*_LAST.usd*"))
        root = crowd._clip_root(walk)
        last = self.project / "assets/chara/OGRE/usd/OGRE_LAST.usda"
        last.parent.mkdir(parents=True)
        layer = Sdf.Layer.CreateNew(str(last))
        ogre = Sdf.PrimSpec(layer, "OGRE", Sdf.SpecifierDef, "SkelRoot")
        skel = Sdf.PrimSpec(Sdf.PrimSpec(ogre, "skel", Sdf.SpecifierDef, "Scope"), "Skeleton",
                            Sdf.SpecifierDef, "Skeleton")
        joints = Sdf.AttributeSpec(skel, "joints", Sdf.ValueTypeNames.TokenArray, Sdf.VariabilityUniform)
        joints.default = _BIPED
        rest = Sdf.AttributeSpec(skel, "restTransforms", Sdf.ValueTypeNames.Matrix4dArray, Sdf.VariabilityUniform)
        rest.default = Vt.Matrix4dArray([Gf.Matrix4d(1)] * len(_BIPED))
        vset = Sdf.VariantSetSpec(ogre, "anim_walk")
        Sdf.VariantSpec(vset, "off")
        on = Sdf.VariantSpec(vset, "on").primSpec
        anim = Sdf.PrimSpec(Sdf.PrimSpec(on, "anims", Sdf.SpecifierDef), "walk", Sdf.SpecifierDef)
        anim.referenceList.prependedItems = [Sdf.Reference(os.path.relpath(walk, last.parent).replace(os.sep, "/"),
                                                           Sdf.Path(f"/{root}/skel/Anim"))]
        over = Sdf.PrimSpec(Sdf.PrimSpec(on, "skel", Sdf.SpecifierOver), "Skeleton", Sdf.SpecifierOver)
        over.SetInfo("apiSchemas", Sdf.TokenListOp.Create(prependedItems=["SkelBindingAPI"]))
        Sdf.RelationshipSpec(over, "skel:animationSource", False).targetPathList.explicitItems = [
            Sdf.Path("/OGRE/anims/walk")]
        names = ["anim_walk"]
        if run:
            # A second clip, starting at 11: same skeleton binding (the stronger one wins in USD).
            anim_run = AnimData(joints=["Root/Hip"], times=[11.0, 12.0], translations=[[(0, 0, 0)]] * 2,
                                rotations=[[(0, 0, 0, 1)]] * 2, scales=[[(1, 1, 1)]] * 2, fps=24.0)
            publish_light_asset(_asset(anim=anim_run), self.project, fmt="usda",
                                dest_dir=self.project / "assets/chara/BOB/anim/run",
                                base_name="CHAR_ANIM_BOB_run", user="adam")
            run_file = next((self.project / "assets/chara/BOB/anim/run").glob("*_LAST.usd*"))
            vset = Sdf.VariantSetSpec(ogre, "anim_run")
            Sdf.VariantSpec(vset, "off")
            on = Sdf.VariantSpec(vset, "on").primSpec
            item = Sdf.PrimSpec(Sdf.PrimSpec(on, "anims", Sdf.SpecifierDef), "run", Sdf.SpecifierDef)
            item.referenceList.prependedItems = [Sdf.Reference(
                os.path.relpath(run_file, last.parent).replace(os.sep, "/"),
                Sdf.Path(f"/{crowd._clip_root(run_file)}/skel/Anim"))]
            over = Sdf.PrimSpec(Sdf.PrimSpec(on, "skel", Sdf.SpecifierOver), "Skeleton", Sdf.SpecifierOver)
            over.SetInfo("apiSchemas", Sdf.TokenListOp.Create(prependedItems=["SkelBindingAPI"]))
            Sdf.RelationshipSpec(over, "skel:animationSource", False).targetPathList.explicitItems = [
                Sdf.Path("/OGRE/anims/run")]
            ogre.variantSelections["anim_run"] = "on"
            names.append("anim_run")
        ogre.variantSetNameList.prependedItems = names
        ogre.variantSelections["anim_walk"] = "on"
        layer.defaultPrim = "OGRE"
        layer.Save()
        return last

    def _skel_anim_times(self, path: Path, agent: str):
        stage = Usd.Stage.Open(str(path))
        skel = UsdSkel.Skeleton(stage.GetPrimAtPath(f"/crowd/crowd/{agent}/skel/Skeleton"))
        query = UsdSkel.Cache().GetSkelQuery(skel)
        cache = UsdSkel.Cache()
        cache.Populate(UsdSkel.Root(stage.GetPrimAtPath(f"/crowd/crowd/{agent}")), Usd.PrimDefaultPredicate)
        anim = cache.GetSkelQuery(skel).GetAnimQuery()
        return anim.GetJointTransformTimeSamples() if anim else None

    def test_animation_unchecked_in_flux_import_does_not_play(self) -> None:
        # 2026-09-26: both anims of OGRE unchecked in FLUX Import, the crowd played one.
        self._ogre()
        pts = [{"p": [0, 0, 0]}]
        res = crowd.build_crowd(self.project, "SEQ001", "SHOT010", "crowd", pts, components=["OGRE"], clips=[],
                                looks={"OGRE": {"variants": {"anim_walk": "off"}, "inactive": []}})
        self.assertIsNone(self._skel_anim_times(res["path"], "agent_0001"))
        self.assertFalse(Usd.Stage.Open(str(res["path"])).GetPrimAtPath("/crowd/crowd/agent_0001/crowd_anim"))

    def test_asset_animation_gets_offset_and_speed(self) -> None:
        # The asset's own animation (checked in FLUX Import) follows Decalage / Vitesse.
        self._ogre()
        pts = [{"p": [0, 0, 0]}]
        res = crowd.build_crowd(self.project, "SEQ001", "SHOT010", "crowd", pts, components=["OGRE"], clips=[],
                                offset=(4, 4), speed=(2, 2),
                                looks={"OGRE": {"variants": {"anim_walk": "on"}, "inactive": []}})
        self.assertEqual(self._skel_anim_times(res["path"], "agent_0001"), [5.0, 5.5, 6.0])

    def test_crowd_clip_beats_the_asset_animation(self) -> None:
        self._ogre()
        res = crowd.build_crowd(self.project, "SEQ001", "SHOT010", "crowd", [{"p": [0, 0, 0]}],
                                components=["OGRE"], clips=["CHAR_ANIM_BOB_walk"], offset=(10, 10))
        self.assertEqual(self._skel_anim_times(res["path"], "agent_0001"), [11.0, 12.0, 13.0])

    def test_rotation_noise_varies_agents_but_not_the_root(self) -> None:
        self._ogre()
        pts = [{"p": [0, 0, 0]}, {"p": [2, 0, 0]}]
        res = crowd.build_crowd(self.project, "SEQ001", "SHOT010", "crowd", pts, components=["OGRE"], clips=[],
                                rot_noise=5.0, looks={"OGRE": {"variants": {"anim_walk": "on"}, "inactive": []}})
        noise = Path(res["path"]).with_name(Path(res["path"]).stem + "_noise.usdc")
        self.assertTrue(noise.is_file())
        stage = Usd.Stage.Open(str(res["path"]))
        r1 = stage.GetPrimAtPath("/crowd/crowd/agent_0001/crowd_anim").GetAttribute("rotations").Get(2)
        r2 = stage.GetPrimAtPath("/crowd/crowd/agent_0002/crowd_anim").GetAttribute("rotations").Get(2)
        self.assertEqual(len(r1), 1)                         # the walk animates Root/Hip only
        self.assertNotEqual(r1[0], r2[0])
        # Same seed, same crowd.
        again = crowd.build_crowd(self.project, "SEQ001", "SHOT010", "crowd", pts, components=["OGRE"], clips=[],
                                  rot_noise=5.0, looks={"OGRE": {"variants": {"anim_walk": "on"}, "inactive": []}})
        stage = Usd.Stage.Open(str(again["path"]))
        self.assertEqual(stage.GetPrimAtPath("/crowd/crowd/agent_0001/crowd_anim").GetAttribute("rotations").Get(2), r1)

    def test_rotation_noise_poses_still_agents(self) -> None:
        # 2026-09-26: OGRE anims unchecked, the noise did nothing (animated agents only).
        self._ogre()
        pts = [{"p": [0, 0, 0]}, {"p": [2, 0, 0]}]
        res = crowd.build_crowd(self.project, "SEQ001", "SHOT010", "crowd", pts, components=["OGRE"], clips=[],
                                rot_noise=10.0, looks={"OGRE": {"variants": {"anim_walk": "off"}, "inactive": []}})
        self.assertEqual(res["noised"], 2)
        stage = Usd.Stage.Open(str(res["path"]))
        cache = UsdSkel.Cache()
        poses = []
        for name in ("agent_0001", "agent_0002"):
            cache.Populate(UsdSkel.Root(stage.GetPrimAtPath(f"/crowd/crowd/{name}")), Usd.PrimDefaultPredicate)
            skel = UsdSkel.Skeleton(stage.GetPrimAtPath(f"/crowd/crowd/{name}/skel/Skeleton"))
            anim = cache.GetSkelQuery(skel).GetAnimQuery()
            self.assertTrue(anim)
            rot = UsdSkel.Animation(anim.GetPrim()).GetRotationsAttr().Get()
            self.assertEqual(rot[0], Gf.Quatf(1.0))                  # root untouched
            self.assertNotEqual(rot[1], Gf.Quatf(1.0))
            poses.append(rot[1])
        self.assertNotEqual(poses[0], poses[1])

    def test_noise_with_joint_names_without_path(self) -> None:
        noise = crowd._joint_noise(["hips", "spine", "head"], 10.0, "k")
        self.assertEqual(noise[0], Gf.Quatf(1.0))
        self.assertNotEqual(noise[1], Gf.Quatf(1.0))
        self.assertNotEqual(noise[2], Gf.Quatf(1.0))

    def test_two_checked_animations_are_shared_between_agents(self) -> None:
        # 2026-09-26: both OGRE anims checked in FLUX Import, the crowd played one only.
        self._ogre(run=True)
        pts = [{"p": [i, 0, 0]} for i in range(12)]
        res = crowd.build_crowd(self.project, "SEQ001", "SHOT010", "crowd", pts, components=["OGRE"], clips=[],
                                looks={"OGRE": {"variants": {"anim_walk": "on", "anim_run": "on"}, "inactive": []}})
        starts = {self._skel_anim_times(res["path"], f"agent_{i + 1:04d}")[0] for i in range(12)}
        self.assertEqual(starts, {1.0, 11.0})
        # Only one checked: every agent plays it.
        res = crowd.build_crowd(self.project, "SEQ001", "SHOT010", "crowd", pts, components=["OGRE"], clips=[],
                                looks={"OGRE": {"variants": {"anim_walk": "off", "anim_run": "on"}, "inactive": []}})
        starts = {self._skel_anim_times(res["path"], f"agent_{i + 1:04d}")[0] for i in range(12)}
        self.assertEqual(starts, {11.0})

    def test_rotation_noise_moves_and_differs_per_agent(self) -> None:
        # 2026-09-26: random along the animation, not the same noise on every agent.
        self._ogre()
        base = {1.0: _anim().rotations[0][0], 2.0: _anim().rotations[1][0], 3.0: _anim().rotations[2][0]}
        looks = {"OGRE": {"variants": {"anim_walk": "on"}, "inactive": []}}

        def noise(freq):
            res = crowd.build_crowd(self.project, "SEQ001", "SHOT010", "crowd", [{"p": [0, 0, 0]}, {"p": [2, 0, 0]}],
                                    components=["OGRE"], clips=[], rot_noise=10.0, noise_freq=freq, looks=looks)
            stage = Usd.Stage.Open(str(res["path"]))
            out = {}
            for name in ("agent_0001", "agent_0002"):
                attr = stage.GetPrimAtPath(f"/crowd/crowd/{name}/crowd_anim").GetAttribute("rotations")
                out[name] = []
                for t, (x, y, z, w) in base.items():
                    out[name].append(Gf.Quatf(w, x, y, z).GetInverse() * attr.Get(t)[0])
            return out

        moving = noise(1.0)
        self.assertNotEqual(moving["agent_0001"][0], moving["agent_0001"][2])     # moves in time
        self.assertNotEqual(moving["agent_0001"], moving["agent_0002"])           # per agent
        still = noise(0.0)
        a, b = still["agent_0001"][0], still["agent_0001"][2]
        self.assertTrue(Gf.IsClose(a.GetImaginary(), b.GetImaginary(), 1e-4))

    def test_instanceable_asset_still_gets_offset_and_noise(self) -> None:
        # 2026-09-26: noise 1000 did nothing. An instanceable asset made every agent an
        # instance: USD ignores what the crowd writes under it (anim, offset, noise).
        last = self._ogre()
        layer = Sdf.Layer.FindOrOpen(str(last))
        layer.GetPrimAtPath("/OGRE").instanceable = True
        layer.Save()
        looks = {"OGRE": {"variants": {"anim_walk": "on"}, "inactive": []}}
        res = crowd.build_crowd(self.project, "SEQ001", "SHOT010", "crowd", [{"p": [0, 0, 0]}],
                                components=["OGRE"], clips=[], offset=(4, 4), speed=(2, 2),
                                rot_noise=1000.0, looks=looks)
        stage = Usd.Stage.Open(str(res["path"]))
        self.assertFalse(stage.GetPrimAtPath("/crowd/crowd/agent_0001").IsInstance())
        self.assertEqual(self._skel_anim_times(res["path"], "agent_0001"), [5.0, 5.5, 6.0])
        rot = stage.GetPrimAtPath("/crowd/crowd/agent_0001/crowd_anim").GetAttribute("rotations").Get(5.5)
        self.assertNotEqual(rot[0], Gf.Quatf(0.9238795, 0, 0.3826834, 0))
        self.assertEqual(res["noised"], 1)
        self.assertIn("OGRE : 1 squelette(s), 3 joints, 1 anim(s), instance retiree", res["info"])

    def test_instanced_mode_shares_a_few_variations(self) -> None:
        # 2026-09-26: unique agents lag; instanced mode = N variations per asset / anim.
        self._ogre()
        pts = [{"p": [i, 0, 0]} for i in range(40)]
        res = crowd.build_crowd(self.project, "SEQ001", "SHOT010", "crowd", pts, components=["OGRE"], clips=[],
                                offset=(0, 20), rot_noise=10.0, variations=4,
                                looks={"OGRE": {"variants": {"anim_walk": "on"}, "inactive": []}})
        self.assertEqual(res["agents"], 40)
        self.assertLessEqual(res["variations"], 4)
        self.assertGreater(res["variations"], 1)
        self.assertEqual(res["noised"], 40)
        stage = Usd.Stage.Open(str(res["path"]))
        agents = [stage.GetPrimAtPath(f"/crowd/crowd/agent_{i + 1:04d}") for i in range(40)]
        self.assertTrue(all(a.IsInstance() for a in agents))
        self.assertEqual(len({a.GetPrototype().GetPath() for a in agents}), res["variations"])
        self.assertTrue(stage.GetPrimAtPath("/crowd_protos").IsAbstract())
        # Each variation plays with its own offset, seen through the instances.
        starts = set()
        for a in agents:
            skel = UsdSkel.Skeleton(stage.GetPrimAtPath(a.GetPath().AppendPath("skel/Skeleton")))
            cache = UsdSkel.Cache()
            cache.Populate(UsdSkel.Root(a), Usd.TraverseInstanceProxies())
            starts.add(cache.GetSkelQuery(skel).GetAnimQuery().GetJointTransformTimeSamples()[0])
        self.assertEqual(len(starts), res["variations"])
        self.assertEqual(stage.GetPrimAtPath("/crowd/crowd/agent_0001").GetAttribute("xformOp:translate").Get(),
                         Gf.Vec3d(0, 0, 0))
        self.assertEqual(stage.GetPrimAtPath("/crowd/crowd/agent_0002").GetAttribute("xformOp:translate").Get(),
                         Gf.Vec3d(1, 0, 0))

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
