# 2026-09-26: the ANIM preset keeps the motion exact while dropping samples, holds
# keys in step mode and finds the root motion whatever the rig calls it; the RIG preset
# compacts the skin weights. Pure python (contract.py), Maya runs the same code.

from __future__ import annotations

import math
import unittest

from features.usd_export.contract import (
    AnimData, compact_weights, hold_keys, quat_angle, quat_slerp, reduce_samples, translation_roots,
)

_Q0 = (0.0, 0.0, 0.0, 1.0)


def _qy(deg: float) -> tuple:
    h = math.radians(deg) / 2.0
    return (0.0, math.sin(h), 0.0, math.cos(h))


def _anim(rots: list, times=None) -> AnimData:
    n = len(rots)
    return AnimData(joints=["Root/Hip"], times=times or [1001.0 + i for i in range(n)],
                    translations=[[(0.0, 0.0, 0.0)]], rotations=[[r] for r in rots],
                    scales=[[(1.0, 1.0, 1.0)]], translations_static=True, scales_static=True)


def _value_at(anim: AnimData, t: float) -> tuple:
    """What a USD consumer reads at *t*: slerp between the bracketing samples."""
    times = anim.times
    if t <= times[0]:
        return anim.rotations[0][0]
    for i in range(1, len(times)):
        if t <= times[i]:
            u = (t - times[i - 1]) / (times[i] - times[i - 1])
            return quat_slerp(anim.rotations[i - 1][0], anim.rotations[i][0], u)
    return anim.rotations[-1][0]


class ReduceSamples(unittest.TestCase):
    def test_a_linear_ramp_keeps_its_ends(self) -> None:
        anim = _anim([_qy(d) for d in range(0, 50, 5)])
        out = reduce_samples(anim)
        self.assertEqual(out.times, [1001.0, 1010.0])

    def test_every_source_frame_is_unchanged(self) -> None:
        # Ease in / out: a curve, a hold, then a curve again.
        rots = [_qy(d) for d in (0, 1, 4, 9, 16, 16, 16, 16, 20, 30, 45)]
        anim = _anim(rots)
        out = reduce_samples(anim)
        self.assertLess(len(out.times), len(anim.times))
        for t, q in zip(anim.times, anim.rotations):
            self.assertLess(quat_angle(_value_at(out, t), q[0]), 1e-3, t)

    def test_a_hold_keeps_its_last_frame(self) -> None:
        # Without 1004 kept, 1002..1004 would slide towards the next pose.
        anim = _anim([_qy(0), _qy(0), _qy(0), _qy(0), _qy(40)])
        out = reduce_samples(anim)
        self.assertEqual(out.times, [1001.0, 1004.0, 1005.0])


class HoldKeys(unittest.TestCase):
    def test_each_key_holds_until_the_next(self) -> None:
        anim = _anim([_qy(d) for d in (0, 10, 20, 30, 40, 50)])
        held = hold_keys(anim, [1001.0, 1004.0])
        self.assertEqual(held.interpolation, "held")
        got = [round(math.degrees(quat_angle(_Q0, r[0]))) for r in held.rotations]
        self.assertEqual(got, [0, 0, 0, 30, 30, 30])
        # Reduced, it still reads the same at every frame.
        out = reduce_samples(held)
        self.assertEqual(out.times, [1001.0, 1003.0, 1004.0, 1006.0])


class TranslationRoots(unittest.TestCase):
    def test_the_highest_moving_joint_wins_whatever_its_name(self) -> None:
        tokens = ["Root", "Root/Sk_Cog", "Root/Sk_Cog/Spine", "Root/Sk_Cog/Leg/Knee"]
        self.assertEqual(translation_roots(tokens, ["Root/Sk_Cog", "Root/Sk_Cog/Leg/Knee"]),
                         ["Root/Sk_Cog"])
        self.assertEqual(translation_roots(tokens, []), [])


class CompactWeights(unittest.TestCase):
    def test_zero_weights_are_dropped_and_rows_renormalised(self) -> None:
        # 2 points, 3 influences on joints 4, 7, 9.
        idx, w, size = compact_weights([4, 7, 9], [0.0, 0.5, 0.5, 0.2, 0.0, 0.0], 2)
        self.assertEqual(size, 2)
        self.assertEqual(idx, [7, 9, 4, 0])
        self.assertEqual(w, [0.5, 0.5, 1.0, 0.0])

    def test_max_influences_keeps_the_strongest(self) -> None:
        idx, w, size = compact_weights([0, 1, 2], [0.6, 0.3, 0.1], 1, max_influences=2)
        self.assertEqual((idx, size), ([0, 1], 2))
        self.assertAlmostEqual(sum(w), 1.0)
        self.assertAlmostEqual(w[0], 0.6 / 0.9)

    def test_numpy_path_matches_the_pure_python_reference(self) -> None:
        # Maya rigs: 325k points x 172 influences made the pure loop freeze Maya
        # (2026-09-27); the numpy path must give the same arrays.
        import random

        from features.usd_export.contract import _compact_weights_np, _compact_weights_py

        rnd = random.Random(7)
        n_pts, n_inf = 300, 12
        infl = [rnd.choice([-1] + list(range(20))) for _ in range(n_inf)]
        infl = list(dict.fromkeys(infl)) + [-1] * (n_inf - len(dict.fromkeys(infl)))
        flat = [round(rnd.random(), 3) if rnd.random() < 0.3 else 0.0 for _ in range(n_pts * n_inf)]
        for max_inf in (0, 4):
            ref = _compact_weights_py(infl, flat, n_pts, max_influences=max_inf, threshold=0.05)
            got = _compact_weights_np(infl, flat, n_pts, max_influences=max_inf, threshold=0.05)
            self.assertEqual(got[2], ref[2])
            self.assertEqual(got[0], ref[0])
            for a, b in zip(got[1], ref[1]):
                self.assertAlmostEqual(a, b)

    def test_numpy_path_merges_two_influences_on_one_joint(self) -> None:
        from features.usd_export.contract import _compact_weights_np

        idx, w, size = _compact_weights_np([3, 3, 5], [0.3, 0.3, 0.4], 1)
        self.assertEqual((idx, size), ([3, 5], 2))
        self.assertAlmostEqual(w[0], 0.6)
        self.assertAlmostEqual(w[1], 0.4)


if __name__ == "__main__":
    unittest.main()
