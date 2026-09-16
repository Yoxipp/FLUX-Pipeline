# test_publish_form.py — the generic front form and destination preview.
#
# Phase 2 lets the front render a form from the action's parameters and preview
# where a publish would land, both without a per-feature code path. These tests
# lock the field list and prove the preview resolves a path without copying.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from flux_actions import commands as _commands  # noqa: F401  (populate registry)
from flux_actions.runner import build_publish_form, preview_publish_action


class PublishFormTests(unittest.TestCase):
    """build_publish_form exposes only the user-facing fields, in run order."""

    def setUp(self):
        self.fields = build_publish_form()
        self.by_name = {(f["step"], f["name"]): f for f in self.fields}

    def test_only_open_visible_params_are_fields(self):
        names = [f["name"] for f in self.fields]
        # source_path (typed by the user) and description (typed by the user).
        self.assertIn("source_path", names)
        self.assertIn("description", names)
        # Wired-by-reference params never surface as fields.
        self.assertNotIn("filename", names)
        # A hidden param (target_name) never surfaces either.
        self.assertNotIn("target_name", names)

    def test_fields_follow_step_order(self):
        steps = [f["step"] for f in self.fields]
        # select comes before publish, matching the action's index order.
        self.assertLess(steps.index("select"), steps.index("publish"))

    def test_fields_carry_the_render_metadata(self):
        source = self.by_name[("select", "source_path")]
        self.assertEqual(source["type"], "path")
        self.assertEqual(source["label"], "Fichier a publier")
        self.assertTrue(source["ask_user"])


class PublishPreviewTests(unittest.TestCase):
    """preview_publish_action resolves the destination without writing bytes."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_preview_resolves_folder_and_writes_nothing(self):
        before = list(self.project.rglob("*"))
        dest = preview_publish_action(
            source_path=Path("/scenes/CHAR_RIG_HERO_null_LAST.mb"),
            project_path=self.project,
            user="tester",
            project_name="TestProj",
        )
        self.assertIsNotNone(dest)
        # Same folder the real publish would use, but nothing was created.
        self.assertEqual(dest, self.project / "assets/chara/HERO/rig/null")
        self.assertEqual(list(self.project.rglob("*")), before)

    def test_preview_returns_none_for_unparseable_name(self):
        dest = preview_publish_action(
            source_path=Path("/scenes/not_a_flux_name.png"),
            project_path=self.project,
            user="tester",
            project_name="TestProj",
        )
        self.assertIsNone(dest)


if __name__ == "__main__":
    unittest.main()
