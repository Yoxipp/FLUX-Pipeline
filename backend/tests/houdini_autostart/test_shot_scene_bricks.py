# ADR 0023 points 14-16: the team builds the sequence template; FLUX gives the bricks.
# Several FLUX Shot nodes side by side: each finds its own branch (its lights), gets its
# own render ROP (range, camera, output of that shot) and renders alone or with the
# whole sequence. Houdini is faked.

from __future__ import annotations

import sys
import types
import unittest

from dcc.houdini.hda import flux_shot_switch_hda


class _Parm:
    def __init__(self, value=""):
        self.value, self.expr = value, None

    def eval(self):
        return self.value

    def evalAsString(self):
        return str(self.value)

    def set(self, value):
        self.value = value

    def setExpression(self, expr, _lang=None):
        self.expr = expr


class _Type:
    def __init__(self, name, registry):
        self._name, self._registry = name, registry

    def name(self):
        return self._name

    def instances(self):
        return [n for n in self._registry.values() if n.type().name() == self._name]


class _Node:
    def __init__(self, hou, path, kind, **parms):
        self.hou, self._path, self._type = hou, path, _Type(kind, hou.nodes)
        self.parms = {k: _Parm(v) for k, v in parms.items()}
        self._inputs: list[_Node] = []
        self.rendered = None
        hou.nodes[path] = self

    def path(self):
        return self._path

    def type(self):
        return self._type

    def parm(self, name):
        return self.parms.setdefault(name, _Parm())

    def evalParm(self, name):
        return self.parm(name).eval()

    def setInput(self, _i, node):
        self._inputs = [node]

    def setInputs(self, nodes):
        self._inputs = list(nodes)

    def inputs(self):
        return self._inputs

    def outputs(self):
        return [n for n in self.hou.nodes.values() if self in n._inputs]

    def createNode(self, kind, name):
        return _Node(self.hou, f"{self._path}/{name}", kind)

    def render(self, frame_range=None):
        if self.evalParm("fail"):
            raise RuntimeError("karma a plante")
        self.rendered = frame_range


def _fake_hou():
    hou = types.SimpleNamespace(nodes={})
    hou.node = lambda path: hou.nodes.get(path)
    hou.exprLanguage = types.SimpleNamespace(Hscript="hscript")
    return hou


class ShotSceneBricks(unittest.TestCase):
    def setUp(self) -> None:
        self.hou = hou = _fake_hou()
        _Node(hou, "/out", "ropnet")
        common = _Node(hou, "/stage/COMMON_LIGHTS", "light")
        self.shots = {}
        for shot, rng in (("SH010", (1001, 1010)), ("SH020", (1001, 1024))):
            node = _Node(hou, f"/stage/{shot}", "flux_shot", project="P", seq="SEQ001", shot=shot,
                         frame_rangex=rng[0], frame_rangey=rng[1], camera="/cams/c", light_node="",
                         render_rop="", status_msg="")
            node.setInput(0, common)
            lights = _Node(hou, f"/stage/{shot}_LIGHTS", "light")
            lights.setInput(0, node)
            self.shots[shot] = (node, lights)
        merge = _Node(hou, "/stage/ALL", "merge")       # a sequence-level merge must not be a branch end
        merge.setInputs([self.shots["SH010"][1], self.shots["SH020"][1]])
        sys.modules["hou"] = hou
        self.addCleanup(sys.modules.pop, "hou", None)
        self.ns: dict = {}
        exec(flux_shot_switch_hda.MODULE_FUNCTIONS, self.ns)

    def test_each_shot_finds_its_own_branch(self) -> None:
        for shot, (node, lights) in self.shots.items():
            self.assertIs(self.ns["_light_source"](node), lights, shot)

    def test_one_render_rop_per_shot_follows_that_shot(self) -> None:
        node, lights = self.shots["SH020"]
        self.ns["create_render_rop"](node)
        rop = self.hou.node(node.evalParm("render_rop"))
        self.assertEqual(rop.path(), "/out/RENDER_SEQ001_SH020")
        self.assertEqual(rop.evalParm("loppath"), lights.path())
        self.assertEqual(rop.parm("f2").expr, 'ch("/stage/SH020/frame_rangey")')
        self.assertEqual(rop.parm("override_camera").expr, 'chs("/stage/SH020/camera")')
        self.assertEqual(rop.evalParm("outputimage"), '`chs("/stage/SH020/render_picture")`')
        self.ns["create_render_rop"](node)                       # clicked again: same ROP
        self.assertEqual(len(self.hou.node("/out").type().instances()), 1)
        self.assertEqual(sum(1 for p in self.hou.nodes if p.startswith("/out/RENDER_")), 1)

    def test_the_sequence_renders_every_shot_with_its_own_range(self) -> None:
        for node, _lights in self.shots.values():
            self.ns["create_render_rop"](node)
        self.ns["render_sequence"](self.shots["SH010"][0])
        self.assertEqual(self.hou.node("/out/RENDER_SEQ001_SH010").rendered, (1001, 1010))
        self.assertEqual(self.hou.node("/out/RENDER_SEQ001_SH020").rendered, (1001, 1024))
        self.assertIn("2 shot(s) rendu(s)", self.shots["SH010"][0].evalParm("status_msg"))

    def test_a_failing_shot_never_stops_the_others(self) -> None:
        for node, _lights in self.shots.values():
            self.ns["create_render_rop"](node)
        self.hou.node("/out/RENDER_SEQ001_SH010").parm("fail").set(True)
        self.ns["render_sequence"](self.shots["SH020"][0])
        self.assertEqual(self.hou.node("/out/RENDER_SEQ001_SH020").rendered, (1001, 1024))
        msg = self.shots["SH020"][0].evalParm("status_msg")
        self.assertIn("1 shot(s) rendu(s)", msg)
        self.assertIn("SH010 (karma a plante)", msg)

    def test_a_shot_without_rop_says_so(self) -> None:
        node = self.shots["SH010"][0]
        self.ns["render_shot"](node)
        self.assertIn("pas de ROP", node.evalParm("status_msg"))

    def test_the_build_script_has_the_render_bricks(self) -> None:
        code = flux_shot_switch_hda._build_code("x.hda")
        compile(code, "build", "exec")
        for needle in ('"render_picture"', '"render_rop"', "create_render_rop", "render_sequence"):
            self.assertIn(needle, code)
        compile(flux_shot_switch_hda.BOOTSTRAP, "boot", "exec")


if __name__ == "__main__":
    unittest.main()
