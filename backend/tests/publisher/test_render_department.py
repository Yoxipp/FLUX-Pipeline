# RENDER shot department (2026-10-09): SEQ_SHOT_RENDER resolves to render/{seq}/{shot},
# also for projects whose tokens.json was written before RENDER existed, and an
# unresolved shot publish explains itself in readable words.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.constants import DEFAULT_CLASS_TOKENS, DEFAULT_SHOT_TYPE_TOKENS
from features.folder_manager import tokens as tok
from features.publisher.publish_core import explain_unresolved_publish, resolve_publish_path


class RenderDepartment(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "PROJ"
        self.project.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_render_is_a_default_shot_department(self) -> None:
        self.assertEqual(DEFAULT_SHOT_TYPE_TOKENS["RENDER"], "render/{seq}/{shot}")
        self.assertEqual(DEFAULT_CLASS_TOKENS["RENDER"], "render/{seq}/{shot}")

    def test_render_resolves_in_a_new_project(self) -> None:
        tok.save_tokens(self.project, tok.build_default_tokens())
        for name in ("SEQ0010_SHOT0010_RENDER_null_v001.exr", "RENDER_SEQ0010_SHOT0010_null_v001.exr"):
            self.assertEqual(resolve_publish_path(self.project, name),
                             self.project / "render" / "SEQ0010" / "SHOT0010" / "null", name)

    def test_project_tokens_without_render_fall_back_to_the_default(self) -> None:
        # tokens.json written before RENDER existed: neither TYPE_SHOT nor CLASS has it
        raw = tok.build_default_tokens()
        raw["TYPE_SHOT"].pop("RENDER")
        raw["CLASS"].pop("RENDER")
        tok.save_tokens(self.project, raw)
        self.assertEqual(resolve_publish_path(self.project, "SEQ010_SHOT020_RENDER_beauty_v002.exr"),
                         self.project / "render" / "SEQ010" / "SHOT020" / "beauty")

    def test_existing_departments_are_unchanged(self) -> None:
        raw = tok.build_default_tokens()
        raw["TYPE_SHOT"].pop("RENDER")
        tok.save_tokens(self.project, raw)
        self.assertEqual(resolve_publish_path(self.project, "SEQ010_SHOT020_LIGHT_null_v001.hip"),
                         self.project / "lighting" / "SEQ010" / "null")
        self.assertEqual(resolve_publish_path(self.project, "SEQ010_SHOT020_COMP_null_v001.nk"),
                         self.project / "comp" / "SEQ010" / "SHOT020" / "null")

    def test_a_project_override_still_wins(self) -> None:
        raw = tok.build_default_tokens()
        raw["TYPE_SHOT"]["RENDER"] = "out/{seq}_{shot}"
        tok.save_tokens(self.project, raw)
        self.assertEqual(resolve_publish_path(self.project, "SEQ010_SHOT020_RENDER_null_v001.exr"),
                         self.project / "out" / "SEQ010_SHOT020" / "null")

    def test_unknown_department_is_explained(self) -> None:
        tok.save_tokens(self.project, tok.build_default_tokens())
        name = "SEQ010_SHOT020_PAINTOVER_null_v001.png"
        self.assertIsNone(resolve_publish_path(self.project, name))
        reason = explain_unresolved_publish(self.project, name)
        self.assertIn("PAINTOVER", reason)
        self.assertIn("TYPE_SHOT", reason)


if __name__ == "__main__":
    unittest.main()
