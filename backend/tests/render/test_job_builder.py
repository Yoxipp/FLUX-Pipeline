# Tractor job builder: frame chunks, farm path rules, .alf / JSON dry run (ADR 0015).
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from features.render import job_builder as jb


def _spec(**over):
    base = dict(
        title="PROJ sh010 v003",
        project="team_a",
        user="adam",
        usd_path="//srv/flux/PROJ/shot/SQ01/SH010/usd/SQ01_SH010_v003.usda",
        output_pattern="//srv/flux/PROJ/shot/SQ01/SH010/render/v003/SQ01_SH010.$F4.exr",
        frame_start=1001,
        frame_end=1012,
        chunk_size=5,
    )
    base.update(over)
    return jb.RenderJobSpec(**base)


class ChunkTests(unittest.TestCase):
    def test_chunks_cover_range(self):
        self.assertEqual(jb.chunk_frames(1001, 1012, 5), [(1001, 1005), (1006, 1010), (1011, 1012)])

    def test_single_frame(self):
        self.assertEqual(jb.chunk_frames(5, 5, 10), [(5, 5)])

    def test_step(self):
        self.assertEqual(jb.chunk_frames(1, 9, 2, step=2), [(1, 3), (5, 7), (9, 9)])

    def test_bad_range(self):
        with self.assertRaises(jb.JobValidationError):
            jb.chunk_frames(10, 1, 5)
        with self.assertRaises(jb.JobValidationError):
            jb.chunk_frames(1, 10, 0)


class PathTests(unittest.TestCase):
    def test_drive_letter_refused(self):
        with self.assertRaises(jb.JobValidationError):
            jb.validate_farm_path("D:/flux/a.usda", "USD")

    def test_unc_accepted_and_normalized(self):
        self.assertEqual(jb.validate_farm_path(r"\\srv\flux\a.usda", "USD"), "//srv/flux/a.usda")
        self.assertTrue(jb.is_unc_path(r"\\srv\flux"))

    def test_relative_accepted(self):
        self.assertEqual(jb.validate_farm_path("shot/a.usda", "USD"), "shot/a.usda")

    def test_spec_with_drive_letter_refused(self):
        with self.assertRaises(jb.JobValidationError):
            jb.to_alf(_spec(output_pattern="C:/render/a.$F4.exr"))

    def test_simulation_accepts_drive_letter(self):
        self.assertIn("C:/render/a.$F4.exr", jb.to_alf(_spec(output_pattern="C:/render/a.$F4.exr"), strict=False))


class AlfTests(unittest.TestCase):
    def test_alf_structure(self):
        alf = jb.to_alf(_spec(maxactive=4, service="houdini", metadata={"shot": "SQ01_SH010"}))
        self.assertTrue(alf.startswith("##AlfredToDo 3.0"))
        self.assertIn("-projects {team_a}", alf)
        self.assertIn("-maxactive 4", alf)
        self.assertIn('-metadata {{"shot": "SQ01_SH010"}}', alf)
        self.assertEqual(alf.count("RemoteCmd"), 3)
        self.assertIn("--renderer BRAY_HdKarma -Va1 --frame 1011 --frame-count 2", alf)
        self.assertEqual(alf.count("{"), alf.count("}"))

    def test_scheduled_start(self):
        self.assertIn("-after {3 7 21:05}", jb.to_alf(_spec(start_after="2027-03-07T21:05")))
        self.assertNotIn("-after", jb.to_alf(_spec()))
        with self.assertRaises(jb.JobValidationError):
            jb.to_alf(_spec(start_after="demain"))

    def test_renderman_delegate(self):
        self.assertIn("HdPrmanLoaderRendererPlugin", jb.to_alf(_spec(renderer="renderman")))

    def test_shot_render_settings(self):
        # ADR 0060: the published shot renders with its render layer's settings.
        alf = jb.to_alf(_spec(renderer="renderman", render_settings="/Render/renderman"))
        self.assertIn("--renderer HdPrmanLoaderRendererPlugin --settings /Render/renderman -Va1", alf)
        self.assertNotIn("--settings", jb.to_alf(_spec()))

    def test_unknown_renderer(self):
        with self.assertRaises(jb.JobValidationError):
            jb.to_alf(_spec(renderer="arnold"))

    def test_tcl_injection_refused(self):
        with self.assertRaises(jb.JobValidationError):
            jb.to_alf(_spec(title="x} ; exec rm {"))


class DryRunTests(unittest.TestCase):
    def test_writes_alf_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = jb.dry_run(_spec(), Path(tmp))
            self.assertTrue(Path(out["alf"]).is_file())
            data = json.loads(Path(out["json"]).read_text(encoding="utf-8"))
            self.assertEqual(data["verb"], "spool")
            self.assertEqual(len(data["chunks"]), 3)
            self.assertEqual(data["spec"]["project"], "team_a")


if __name__ == "__main__":
    unittest.main()
