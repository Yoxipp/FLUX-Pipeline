# ADR 0036: default render scene of a sequence, built by hython. hython is faked: the
# tests check the plan (shots of the sequence, project resolution), what the generated
# script builds (one FLUX Shot branch + ROP per shot, light_node on the lights null),
# that an existing scene is never overwritten and that an empty sequence is refused.

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
        self.assertEqual([s["shot"] for s in plan["shots"]], ["SHOT010", "SHOT020"])
        self.assertEqual(plan["shots"][0]["range"], [1001, 1048])
        self.assertFalse(plan["shots"][1]["has_stage"])
        self.assertIn("hitPz", plan["aovs"])                          # depth AOV

    def test_script_builds_one_branch_and_rop_per_shot(self) -> None:
        script = hr._gen_script(hr.build_plan(self.project, "SEQ001"), "C:/p/SEQ001_render")
        compile(script, "render_scene", "exec")                       # valid Python for hython
        for needle in ('createNode("flux_shot"', '"SHOT_LIGHTS_"', 'parm("light_node").set(lights.path())',
                       'createNode("karmacryptomatte"', 'createNode("karmarendersettings"',
                       'createNode("usdrender"', 'parm("render_rop").set(rop.path())',
                       'rop.parm("loppath").set(end.path())', "BRAY_HdKarma", "hou.hipFile.clear"):
            self.assertIn(needle, script, needle)
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
        self.assertEqual((res["created"], res["without_stage"]), (True, ["SHOT020"]))

    def test_a_sequence_without_shots_is_refused(self) -> None:
        with mock.patch.object(hr, "_run_offline") as run:
            res = hr.create_sequence_render_scene(self.project, "SEQ404")
        run.assert_not_called()
        self.assertFalse(res["ok"])

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
