# Importer rule (2026-09-25): one shader per geometry, one animation per rig.
# The file just checked wins; files on other targets are untouched.

from __future__ import annotations

import unittest

from features.usd_assembler import component_recipe as cr


def _f(fid, kind, targets=(), active=False):
    return {"id": fid, "kind": kind, "targets": list(targets), "active": active}


RECIPE = {"files": [
    _f("body", "geometry", active=True), _f("beak", "geometry", active=True),
    _f("rig_a", "rig", active=True), _f("rig_b", "rig", active=True),
    _f("sh_body_red", "shader", ["body"], True), _f("sh_body_blue", "shader", ["body"]),
    _f("sh_beak", "shader", ["beak"], True), _f("sh_all", "shader", ["body", "beak"]),
    _f("walk_a", "animation", ["rig_a"]), _f("run_a", "animation", ["rig_a"]),
    _f("walk_b", "animation", ["rig_b"]),
]}


class ExclusiveTargets(unittest.TestCase):
    def test_checked_shader_wins_its_geometry_only(self) -> None:
        before = cr.active_map(RECIPE)
        after = cr.exclusive_by_target(RECIPE, dict(before, sh_body_blue=True), before)
        self.assertTrue(after["sh_body_blue"])
        self.assertFalse(after["sh_body_red"])
        self.assertTrue(after["sh_beak"])              # the beak keeps its own shader

    def test_shader_on_two_geometries_takes_both(self) -> None:
        before = cr.active_map(RECIPE)
        after = cr.exclusive_by_target(RECIPE, dict(before, sh_all=True), before)
        self.assertTrue(after["sh_all"])
        self.assertFalse(after["sh_body_red"])
        self.assertFalse(after["sh_beak"])

    def test_animation_goes_to_its_own_rig(self) -> None:
        before = dict(cr.active_map(RECIPE), walk_a=True, walk_b=True)
        after = cr.exclusive_by_target(RECIPE, dict(before, run_a=True), before)
        self.assertTrue(after["run_a"])
        self.assertFalse(after["walk_a"])
        self.assertTrue(after["walk_b"])               # the other rig keeps its anim

    def test_without_previous_the_recipe_order_wins(self) -> None:
        after = cr.exclusive_by_target(RECIPE, {"sh_body_blue": True})
        self.assertTrue(after["sh_body_red"])
        self.assertFalse(after["sh_body_blue"])

    def test_geometry_toggles_are_never_touched(self) -> None:
        after = cr.exclusive_by_target(RECIPE, {"body": False}, cr.active_map(RECIPE))
        self.assertFalse(after["body"])
        self.assertTrue(after["beak"])


if __name__ == "__main__":
    unittest.main()
