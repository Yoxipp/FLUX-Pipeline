# FLUX Crowd, 2026-09-25: input 1 = assets (FLUX Import in a Merge), input 2 = the
# scatter points, input 3 = the animations; one weight row per asset and per animation.

from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom, UsdSkel, Vt

from dcc.houdini.hda import flux_crowd_hda


class _Parm:
    def __init__(self, value=""):
        self.value = value

    def eval(self):
        return self.value

    def evalAsString(self):
        return str(self.value)

    def set(self, value):
        self.value = value


class _Input:
    def __init__(self, stage):
        self._stage = stage

    def stage(self):
        return self._stage


class _Node:
    def __init__(self, inputs, **values):
        self._inputs = inputs
        self.parms = {k: _Parm(v) for k, v in values.items()}

    def input(self, i):
        return self._inputs[i] if i < len(self._inputs) else None

    def parm(self, name):
        default = 0 if name.endswith("_count") else (1.0 if "_w" in name else "")
        return self.parms.setdefault(name, _Parm(default))

    def evalParm(self, name):
        return self.parm(name).eval()

    def node(self, _name):
        return None


class CrowdInputs(unittest.TestCase):
    def setUp(self) -> None:
        hou = types.ModuleType("hou")
        hou.frame = lambda: 1001.0
        sys.modules["hou"] = hou
        self.addCleanup(sys.modules.pop, "hou", None)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ns: dict = {}
        exec(flux_crowd_hda.MODULE_FUNCTIONS, self.ns)
        self.ns["_compat"] = lambda node, fresh=False: {
            "assets": {"BOB": {"joint_count": 3}, "TIM": {"joint_count": 3}},
            "clips": [{"base": "CHAR_ANIM_BOB_walk", "asset": "BOB", "clip": "walk", "range": [1, 24]},
                      {"base": "CHAR_ANIM_BOB_walkfast", "asset": "BOB", "clip": "walkfast"}]}

    def _assets(self) -> Usd.Stage:
        stage = Usd.Stage.CreateInMemory()
        for name in ("BOB", "TIM"):
            prim = stage.DefinePrim(f"/assets/{name}")
            Usd.ModelAPI(prim).SetKind("component")
            Usd.ModelAPI(prim).SetAssetInfo({"name": name})
            UsdGeom.Mesh.Define(stage, f"/assets/{name}/geo/render/body")
        return stage

    def _points(self) -> Usd.Stage:
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/scatter").AddTranslateOp().Set(Gf.Vec3d(10, 0, 0))
        pts = UsdGeom.Points.Define(stage, "/scatter/points")
        pts.CreatePointsAttr(Vt.Vec3fArray([Gf.Vec3f(0, 0, 0), Gf.Vec3f(1, 0, 2)]))
        pts.CreateWidthsAttr(Vt.FloatArray([2.0, 4.0]))
        quarter = Gf.Rotation(Gf.Vec3d(0, 1, 0), 90).GetQuat()
        UsdGeom.PrimvarsAPI(pts).CreatePrimvar("orient", Sdf.ValueTypeNames.QuathArray).Set(
            Vt.QuathArray([Gf.Quath(1, 0, 0, 0), Gf.Quath(quarter)]))
        return stage

    def _clips(self) -> Usd.Stage:
        clip = Path(self._tmp.name) / "CHAR_ANIM_BOB_walk_LAST.usda"
        cs = Usd.Stage.CreateNew(str(clip))
        UsdSkel.Animation.Define(cs, "/BOB/skel/Anim")
        cs.SetDefaultPrim(cs.GetPrimAtPath("/BOB"))
        cs.GetRootLayer().Save()
        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/assets/walk").GetReferences().AddReference(str(clip))
        return stage

    def test_inputs_fill_the_weight_rows_and_the_points(self) -> None:
        node = _Node([_Input(self._assets()), _Input(self._points()), _Input(self._clips())],
                     project="P", asset_memory="{}", clip_memory="{}")
        assets, clips = self.ns["read_inputs"](node)
        self.assertEqual((assets, clips), (["BOB", "TIM"], ["CHAR_ANIM_BOB_walk"]))
        self.assertEqual(node.evalParm("asset_count"), 2)
        self.assertIn("BOB", node.evalParm("asset_label1"))
        self.assertEqual(node.evalParm("clip_label1"), "BOB walk  1-24")
        node.parm("asset_w1").set(3.0)
        self.ns["read_inputs"](node)                    # re-read: the weight stays
        self.assertEqual(self.ns["_weights"](node, "asset"), {"BOB": 3.0, "TIM": 1.0})
        pts = self.ns["_input_points"](node)
        self.assertEqual([p["p"] for p in pts], [[10.0, 0.0, 0.0], [11.0, 0.0, 2.0]])
        self.assertEqual([p["scale"] for p in pts], [1.0, 2.0])     # width = 2 * pscale
        self.assertAlmostEqual(pts[0]["ry"], 0.0)
        self.assertAlmostEqual(pts[1]["ry"], 90.0, places=1)       # half floats

    def test_without_inputs_the_menus_are_used(self) -> None:
        node = _Node([], project="P", assets="BOB", clips="CHAR_ANIM_BOB_walkfast",
                     asset_memory="{}", clip_memory="{}")
        self.assertEqual(self.ns["read_inputs"](node), (["BOB"], ["CHAR_ANIM_BOB_walkfast"]))
        self.assertIsNone(self.ns["_input_points"](node))

    def test_build_sends_the_weights(self) -> None:
        sent = {}
        self.ns["_post"] = lambda path, payload: sent.update(payload) or {"ok": True, "agents": 2, "path": "x"}
        node = _Node([_Input(self._assets()), _Input(self._points()), _Input(self._clips())],
                     project="P", seq="SEQ001", shot="SHOT010", group="crowd", seed=0,
                     offsetx=0.0, offsety=0.0, speedx=1.0, speedy=1.0, asset_memory="{}", clip_memory="{}")
        self.ns["generate"](node)
        self.assertEqual(sent["components"], ["BOB", "TIM"])
        self.assertEqual(sent["component_weights"], {"BOB": 1.0, "TIM": 1.0})
        self.assertEqual(sent["clip_weights"], {"CHAR_ANIM_BOB_walk": 1.0})
        self.assertEqual(len(sent["points"]), 2)
        json.dumps(sent)


if __name__ == "__main__":
    unittest.main()
