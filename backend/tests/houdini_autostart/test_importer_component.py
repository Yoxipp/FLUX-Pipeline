# ADR 0023: the /stage FLUX Import lists the files of a component (GEO, GROOM, LOOKDEV,
# ANIM, other), one toggle each. The toggles live on the node only; a shader without an
# active target is greyed but keeps its toggle; warnings never unselect anything; the
# inner apply_component LOP turns the toggles into variant selections.

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pxr import Usd, UsdGeom

from dcc.houdini.hda import flux_importer_hda, flux_importer_lop_hda
from features.folder_manager import tokens as tok
from features.usd_assembler import component_auto as ca


class _Parm:
    def __init__(self, value=""):
        self.value = value

    def eval(self):
        return self.value

    def evalAsString(self):
        return str(self.value)

    def set(self, value):
        self.value = value


class _Node:
    """Fake LOP importer: every parm exists (multiparm instances appear when set)."""

    def __init__(self, **values):
        self.parms: dict[str, _Parm] = {k: _Parm(v) for k, v in values.items()}

    def parm(self, name):
        return self.parms.setdefault(name, _Parm(0 if name.endswith("_files") else ""))

    def evalParm(self, name):
        return self.parm(name).eval()

    def row(self, prefix: str, fid: str) -> int:
        for i in range(1, self.parm(f"{prefix}_files").eval() + 1):
            if self.evalParm(f"{prefix}_id{i}") == fid:
                return i
        raise KeyError(fid)


def _usd(path: Path, prim: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.Mesh.Define(stage, prim)
    stage.SetDefaultPrim(stage.GetPrimAtPath("/" + prim.strip("/").split("/")[0]))
    stage.GetRootLayer().Save()


class ImporterComponent(unittest.TestCase):
    def setUp(self) -> None:
        env = mock.patch.dict(os.environ, {"FLUX_PROXY_USD": "0"})
        env.start()
        self.addCleanup(env.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name) / "PROJ"
        self.project.mkdir()
        tokens = tok.build_default_tokens()
        tokens["NAME"]["UTAH"] = "assets/chara/UTAH"
        tokens["NAME"]["BOX"] = "assets/props/BOX"
        tok.save_tokens(self.project, tokens)
        base = "assets/chara/UTAH/extra"
        for name in ("body", "hat", "low", "skin", "rig", "walk", "run"):
            _usd(self.project / base / f"{name}.usda", f"/{name.upper()}")
        ca.create_component(self.project, "UTAH", ["GEO", "SHADING", "RIG", "ANIM"])
        f = lambda fid, dept, **kw: {"id": fid, "department": dept, "source": "manual",   # noqa: E731
                                     "path": f"{base}/{fid}.usda", **kw}
        ca.save_component(self.project, "UTAH", {"departments": ["GEO", "SHADING", "RIG", "ANIM"], "files": [
            f("body", "GEO"), f("hat", "GEO"), f("low", "GEO", proxy_of=["body"], active=False),
            f("skin", "SHADING", targets=["body", "hat"]), f("rig", "RIG"),
            f("walk", "ANIM", targets=["rig"]), f("run", "ANIM", targets=["rig"]),
        ]})
        _usd(self.project / "assets/props/BOX/model/box.usda", "/BOX")
        ca.create_component(self.project, "BOX", ["GEO"])
        ca.save_component(self.project, "BOX", {"departments": ["GEO"], "files": [
            {"id": "box", "department": "GEO", "source": "manual", "path": "assets/props/BOX/model/box.usda"}]})

        self.ns: dict = {}
        exec(flux_importer_hda._MODULE_FUNCTIONS, self.ns)

        def post(path, payload):
            self.assertEqual(path, "/usd/component/check")
            try:
                return ca.component_files(self.project, payload["name"], payload["version"], payload["active"],
                                          payload.get("previous"))
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
        self.ns["_post"] = post
        self.node = _Node(project="PROJ", source_mode="library", lib_item="component:UTAH", lib_version="LAST",
                          prim_path="/assets/UTAH", comp_state="{}", comp_memory="{}", comp_key="")

    def _state(self) -> dict:
        return json.loads(self.node.evalParm("comp_state"))

    def _toggle(self, prefix: str, fid: str, on: bool) -> None:
        self.node.parm(f"{prefix}_on{self.node.row(prefix, fid)}").set(1 if on else 0)
        self.ns["on_component_toggle"](self.node)

    def test_files_are_grouped_by_kind_with_proxies_on_and_anims_off(self) -> None:
        self.ns["_fill_component"](self.node)
        n = self.node
        self.assertEqual((n.evalParm("geo_files"), n.evalParm("look_files"), n.evalParm("anim_files"),
                          n.evalParm("other_files"), n.evalParm("groom_files")), (3, 1, 2, 1, 0))
        self.assertEqual(n.evalParm(f"geo_on{n.row('geo', 'low')}"), 1)       # proxy: on by default
        self.assertEqual(n.evalParm(f"anim_on{n.row('anim', 'walk')}"), 0)    # preview: off by default
        self.assertEqual(self._state(), {"body": "on", "hat": "on", "low": "on", "skin": "on",
                                         "rig": "on", "walk": "off", "run": "off"})
        self.assertEqual(n.evalParm("comp_has_warn"), 0)

    def test_one_animation_per_rig_the_last_checked_wins(self) -> None:
        # ADR 0028: checking a second animation of the same rig unchecks the first.
        self.ns["_fill_component"](self.node)
        self._toggle("anim", "walk", True)
        self._toggle("anim", "run", True)
        self.assertEqual((self._state()["walk"], self._state()["run"]), ("off", "on"))
        self.assertEqual(self.node.evalParm(f"anim_on{self.node.row('anim', 'walk')}"), 0)

    def test_shader_greyed_without_geometry_then_restored(self) -> None:
        self.ns["_fill_component"](self.node)
        look = self.node.row("look", "skin")
        self._toggle("geo", "body", False)
        self.assertEqual(self.node.evalParm(f"look_ok{look}"), 1)             # hat still on
        self._toggle("geo", "hat", False)
        self.assertEqual(self.node.evalParm(f"look_ok{look}"), 0)             # greyed
        self.assertEqual(self.node.evalParm(f"look_on{look}"), 1)             # its state is kept
        self.assertEqual(self._state()["skin"], "off")
        self._toggle("geo", "hat", True)
        self.assertEqual((self.node.evalParm(f"look_ok{look}"), self._state()["skin"]), (1, "on"))

    def test_a_variant_block_with_nothing_checked_composes_nothing(self) -> None:
        # Live 2026-09-25 (OGRE): two animations = two variants of one block, both
        # unchecked: the component's default variant still played.
        files = [
            {"id": "rig", "kind": "rig", "targets": [], "variant_set": "rig", "active": True},
            {"id": "animA", "kind": "animation", "targets": ["rig"], "block": "anim", "variant": "A",
             "variant_set": "anim", "active": False},
            {"id": "animB", "kind": "animation", "targets": ["rig"], "block": "anim", "variant": "B",
             "variant_set": "anim", "active": False},
        ]
        self.ns["_post"] = lambda path, payload: {"files": files, "warnings": [],
                                                  "active": {f["id"]: payload["active"].get(f["id"], f["active"])
                                                             for f in files}}
        self.ns["_fill_component"](self.node)
        self.assertEqual(self._state(), {"rig": "on", "anim": "off"})     # "off": no such variant
        self._toggle("anim", "animB", True)
        self.assertEqual(self._state()["anim"], "B")
        self.assertEqual(self.node.evalParm("groom_files"), 0)          # no groom: section hidden

    def test_toggles_are_remembered_per_component_and_never_saved(self) -> None:
        self.ns["_fill_component"](self.node)
        self._toggle("geo", "hat", False)
        self.node.parm("lib_item").set("component:BOX")
        self.ns["_fill_component"](self.node)
        self.assertEqual(self._state(), {"box": "on"})
        self.node.parm("lib_item").set("component:UTAH")
        self.ns["_fill_component"](self.node)
        self.assertEqual(self._state()["hat"], "off")
        recipe = ca.current_recipe(self.project, "UTAH")
        self.assertTrue(next(f for f in recipe["files"] if f["id"] == "hat")["active"])

    def test_a_decor_or_shot_clears_the_content(self) -> None:
        self.ns["_fill_component"](self.node)
        self.node.parm("lib_item").set("shot:SEQ001/SHOT010")
        self.ns["_fill_component"](self.node)
        self.assertEqual((self.node.evalParm("geo_files"), self._state()), (0, {}))

    def test_apply_component_sets_the_variant_selections(self) -> None:
        self.ns["_fill_component"](self.node)
        self._toggle("geo", "hat", False)
        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/assets/UTAH").GetReferences().AddReference(
            str(self.project / "assets/chara/UTAH/usd/UTAH_LAST.usda"))
        self.assertTrue(stage.GetPrimAtPath("/assets/UTAH/geo/render/hat").IsValid())
        warnings: list[str] = []
        node = self.node

        class _Lop:
            def parent(self):
                return node

            def editableStage(self):
                return stage

            def addWarning(self, msg):
                warnings.append(msg)

        hou = mock.MagicMock()
        hou.pwd.return_value = _Lop()
        exec(flux_importer_lop_hda.APPLY_COMPONENT, {"hou": hou})
        self.assertFalse(stage.GetPrimAtPath("/assets/UTAH/geo/render/hat").IsValid())
        self.assertTrue(stage.GetPrimAtPath("/assets/UTAH/geo/render/body").IsValid())
        self.assertEqual(warnings, [])

    def test_the_lop_build_script_has_the_component_folders(self) -> None:
        code = flux_importer_lop_hda._build_code("x.hda", flux_importer_hda.PYTHON_MODULE)
        compile(code, "build", "exec")
        for needle in ('"comp_folder"', '"apply_component"', "on_component_toggle",
                       "_full.setInput(0, _apply)", "folderType.Collapsible", "MAX_ROWS"):
            self.assertIn(needle, code)
        # Fixed rows filled by FLUX: no + / - (no multiparm), empty sections hidden.
        self.assertNotIn("MultiparmBlock", code)
        compile(flux_importer_lop_hda.APPLY_COMPONENT, "apply", "exec")


if __name__ == "__main__":
    unittest.main()
