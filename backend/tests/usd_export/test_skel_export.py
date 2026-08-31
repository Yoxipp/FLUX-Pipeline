# test_skel_export.py — deterministic tests for the light UsdSkel export core.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pxr import Usd, UsdSkel

from features.usd_export import (
    AnimData,
    LightAsset,
    MeshData,
    SkeletonData,
    author_light_asset,
    filter_animated_joints,
)

_ID = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
_MOVED = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 5, 0, 0, 1)   # translated


def _sample_asset(with_anim: bool = True) -> LightAsset:
    skel = SkeletonData(
        joints=["Root", "Root/Hip"],
        bind_transforms=[_ID, _ID],
        rest_transforms=[_ID, _ID],
    )
    mesh = MeshData(
        name="body",
        points=[(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
        face_vertex_counts=[4],
        face_vertex_indices=[0, 1, 2, 3],
        joint_indices=[0, 1, 0, 1],
        joint_weights=[1.0, 1.0, 1.0, 1.0],
        influences_per_point=1,
    )
    anim = None
    if with_anim:
        anim = AnimData(
            joints=["Root/Hip"],
            times=[1.0, 2.0],
            translations=[[(0, 0, 0)], [(5, 0, 0)]],
            rotations=[[(0, 0, 0, 1)], [(0, 0, 0, 1)]],
            scales=[[(1, 1, 1)], [(1, 1, 1)]],
        )
    return LightAsset(asset="CHAR_hero", skeleton=skel, meshes=[mesh], anim=anim)


class FilterAnimatedJoints(unittest.TestCase):
    def test_only_moving_joint_kept(self):
        joints = ["Root", "Root/Hip"]
        per_time = [[_ID, _ID], [_ID, _MOVED]]   # Hip moves, Root static
        self.assertEqual(filter_animated_joints(joints, per_time), ["Root/Hip"])

    def test_single_frame_is_static(self):
        self.assertEqual(filter_animated_joints(["A"], [[_ID]]), [])


class AuthorLightAsset(unittest.TestCase):
    def test_layers_written_and_root_composes(self):
        with tempfile.TemporaryDirectory() as d:
            paths = author_light_asset(_sample_asset(), d, fmt="usda")
            for key in ("model", "skel", "anim", "root"):
                self.assertTrue(paths[key].exists(), f"{key} layer missing")

            stage = Usd.Stage.Open(str(paths["root"]))
            # defaultPrim honours the publish contract (== asset token).
            self.assertEqual(stage.GetDefaultPrim().GetName(), "CHAR_hero")

            root = stage.GetPrimAtPath("/CHAR_hero")
            self.assertTrue(root and root.IsA(UsdSkel.Root))
            self.assertTrue(stage.GetPrimAtPath("/CHAR_hero/Skeleton").IsA(UsdSkel.Skeleton))
            self.assertTrue(stage.GetPrimAtPath("/CHAR_hero/body").IsValid())

            skel = UsdSkel.Skeleton(stage.GetPrimAtPath("/CHAR_hero/Skeleton"))
            self.assertEqual(list(skel.GetJointsAttr().Get()), ["Root", "Root/Hip"])

            anim = UsdSkel.Animation(stage.GetPrimAtPath("/CHAR_hero/Anim"))
            self.assertEqual(list(anim.GetJointsAttr().Get()), ["Root/Hip"])
            # animated joint carries two translation samples
            self.assertEqual(anim.GetTranslationsAttr().GetNumTimeSamples(), 2)

    def test_rig_only_skips_anim_layer(self):
        with tempfile.TemporaryDirectory() as d:
            paths = author_light_asset(_sample_asset(with_anim=False), d, fmt="usda")
            self.assertNotIn("anim", paths)
            stage = Usd.Stage.Open(str(paths["root"]))
            self.assertFalse(stage.GetPrimAtPath("/CHAR_hero/Anim").IsValid())

    def test_binding_targets_skeleton(self):
        with tempfile.TemporaryDirectory() as d:
            paths = author_light_asset(_sample_asset(), d, fmt="usda")
            stage = Usd.Stage.Open(str(paths["root"]))
            binding = UsdSkel.BindingAPI(stage.GetPrimAtPath("/CHAR_hero/body"))
            targets = binding.GetSkeletonRel().GetTargets()
            self.assertEqual([str(t) for t in targets], ["/CHAR_hero/Skeleton"])


if __name__ == "__main__":
    unittest.main()
