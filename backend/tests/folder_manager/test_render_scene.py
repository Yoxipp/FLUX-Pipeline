# ADR 0036: default render scene of a sequence, built by hython. hython is faked: the
# tests check the plan (10 default shots + the shots of the sequence, project resolution),
# what the generated script builds (the maintainer's layout: STRUCTURE, sequence env / lights, per
# shot FLUX Shot + grafts + crypto + render settings + ROP, light_node on the lights
# graft), that an existing scene is never overwritten and that a new sequence (no shot
# yet) gets its 10 shots.

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from features.folder_manager import houdini_render_scene as hr


class RenderScene(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name) / "PROJ"
        self.project.mkdir()
        (self.project / "project.json").write_text(json.dumps(
            {"project_id": "x", "fps": 24, "resolution": [2048, 858]}), encoding="utf-8")
        self.shots = [("SEQ001", "SHOT010"), ("SEQ001", "SHOT020"), ("SEQ002", "SHOT010")]
        staged = [{"seq": "SEQ001", "shot": "SHOT010", "range": [1001, 1048], "fps": 24.0}]
        self.patches = [
            mock.patch("features.importer.library_import._stage_shots", return_value=self.shots),
            mock.patch("features.usd_assembler.shot_light.list_stage_shots", return_value=staged),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_plan_lists_the_shots_of_the_sequence_with_the_project_resolution(self) -> None:
        plan = hr.build_plan(self.project, "seq001")
        self.assertEqual(plan["seq"], "SEQ001")
        self.assertEqual(plan["resolution"], [2048, 858])
        names = [s["shot"] for s in plan["shots"]]
        self.assertEqual(names, [f"SHOT{n:03d}" for n in range(1, 11)] + ["SHOT020"])
        by_name = {s["shot"]: s for s in plan["shots"]}
        self.assertEqual(by_name["SHOT010"]["range"], [1001, 1048])
        self.assertFalse(by_name["SHOT020"]["has_stage"])
        self.assertIn("hitPz", plan["aovs"])                          # depth AOV
        self.assertIn("__variance", plan["aovs"])                     # denoise

    def test_script_builds_one_branch_and_rop_per_shot(self) -> None:
        script = hr._gen_script(hr.build_plan(self.project, "SEQ001"), "C:/p/SEQ001_render")
        compile(script, "render_scene", "exec")                       # valid Python for hython
        for needle in ('createNode("flux_shot"', '"STRUCTURE"', '"graft_env_seq"', '"graft_light_seq"',
                       'createNode("graftbranches"', 'parm("light_node").set(prev.path())',
                       'createNode("karmacryptomatte"', 'createNode("karmarendersettings"',
                       'createNode("usdrender"', 'parm("render_rop").set(rop.path())',
                       'rop.parm("loppath").set(end.path())', "BRAY_HdKarma", "hou.hipFile.clear",
                       "hou.setSessionModuleSource"):
            self.assertIn(needle, script, needle)
        self.assertEqual(hr.GRAFTS[0][0], "LIGHTS")                   # light rig = lights only
        self.assertNotIn("hipFile.load", script)                       # built from an empty scene

    def test_an_existing_scene_is_never_overwritten(self) -> None:
        base = hr.render_scene_base(self.project, "SEQ001")
        base.parent.mkdir(parents=True)
        base.with_suffix(".hipnc").write_text("artist work", encoding="utf-8")
        with mock.patch.object(hr, "_run_offline") as run:
            res = hr.create_sequence_render_scene(self.project, "SEQ001")
        run.assert_not_called()
        self.assertEqual((res["ok"], res["created"]), (True, False))
        self.assertEqual(base.with_suffix(".hipnc").read_text(encoding="utf-8"), "artist work")

    def test_generation_reports_the_shots_without_stage(self) -> None:
        done = {"ok": True, "path": "C:/p/SEQ001_render.hip", "shots": ["SHOT010", "SHOT020"]}
        with mock.patch.object(hr, "_run_offline", return_value=done) as run:
            res = hr.create_sequence_render_scene(self.project, "SEQ001")
        self.assertIn("SEQ001_render", run.call_args.args[0])
        self.assertTrue(res["created"])
        self.assertNotIn("SHOT010", res["without_stage"])             # the only staged shot
        self.assertIn("SHOT020", res["without_stage"])

    def test_a_new_sequence_gets_ten_shots(self) -> None:
        plan = hr.build_plan(self.project, "SEQ404")
        self.assertEqual([s["shot"] for s in plan["shots"]], [f"SHOT{n:03d}" for n in range(1, 11)])
        done = {"ok": True, "path": "C:/p/SEQ404_render.hip", "shots": []}
        with mock.patch.object(hr, "_run_offline", return_value=done) as run:
            self.assertTrue(hr.create_sequence_render_scene(self.project, "SEQ404")["created"])
        run.assert_called_once()

    def test_the_scene_opens_on_stage(self) -> None:
        compile(hr.SESSION_SOURCE, "session", "exec")
        self.assertIn('pane.setPwd(stage)', hr.SESSION_SOURCE)
        self.assertIn("hou.isUIAvailable()", hr.SESSION_SOURCE)      # nothing in hython

    def test_one_builtin_preset_per_sequence_for_the_new_scene_menu(self) -> None:
        base = hr.render_scene_base(self.project, "SEQ002")
        base.parent.mkdir(parents=True)
        base.with_suffix(".hip").write_text("x", encoding="utf-8")
        presets = hr.builtin_presets(self.project)
        self.assertEqual([p["id"] for p in presets],
                         [hr.BUILTIN_PREFIX + "SEQ001", hr.BUILTIN_PREFIX + "SEQ002"])
        for p in presets:
            self.assertEqual((p["task"], p["soft"], p["builtin"]), ("SEQ", "houdini", True))
            self.assertTrue(p["file"])                          # the launcher lists linked presets only
        self.assertEqual([p["exists"] for p in presets], [False, True])
        self.assertEqual(presets[1]["file"], "SEQ002_render.hip")

    def test_opening_a_builtin_preset_builds_then_returns_the_real_scene(self) -> None:
        done = {"ok": True, "path": "C:/p/SEQ001_render.hip", "shots": ["SHOT010"]}
        with mock.patch.object(hr, "_run_offline", return_value=done):
            res = hr.open_builtin_preset(self.project, hr.BUILTIN_PREFIX + "SEQ001")
        self.assertEqual(res["path"], "C:/p/SEQ001_render.hip")
        self.assertFalse(hr.open_builtin_preset(self.project, "preset_1")["ok"])


if __name__ == "__main__":
    unittest.main()
