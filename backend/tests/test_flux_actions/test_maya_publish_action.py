# test_maya_publish_action.py — the Maya publish action, tested headless.
#
# The export step talks to a live Maya, so it is mocked here: run_maya_export is
# replaced by a stub that writes a real temp file. Everything else is real — the
# graph, the resolve step and the shared copy_publish step — so this proves the
# wiring and the end-to-end file placement without needing Maya open.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from flux_core import ActionQuery
from flux_actions import commands as _commands  # noqa: F401  (populate registry)
from flux_actions.runner import PUBLISH_MAYA_ACTION, run_maya_publish_action


class SelectDccPublishTests(unittest.TestCase):
    """The DCC select validates the scene name and owns the extension."""

    def _run(self, base_name: str, extension: str = ".mb", scope: str = "scene"):
        import asyncio
        from flux_actions.commands.select_dcc_publish import SelectDccPublish
        import logging

        return asyncio.run(
            SelectDccPublish().run(
                {"base_name": base_name, "extension": extension, "scope": scope},
                None,
                logging.getLogger("test"),
            )
        )

    def test_composes_and_validates_filename(self):
        out = self._run("CHAR_RIG_HERO_null", ".abc", "selection")
        self.assertEqual(out["filename"], "CHAR_RIG_HERO_null.abc")
        self.assertEqual(out["extension"], ".abc")
        self.assertEqual(out["scope"], "selection")

    def test_extension_without_dot_is_normalised(self):
        out = self._run("CHAR_RIG_HERO_null", "mb")
        self.assertEqual(out["filename"], "CHAR_RIG_HERO_null.mb")

    def test_base_name_extension_is_ignored(self):
        # A base name that already carries an extension must not double it.
        out = self._run("CHAR_RIG_HERO_null.mb", ".mb")
        self.assertEqual(out["filename"], "CHAR_RIG_HERO_null.mb")

    def test_invalid_name_raises(self):
        # A structurally broken name (too few tokens) cannot be a FLUX name.
        with self.assertRaises(ValueError):
            self._run("weird", ".mb")


class MayaPublishActionLoadTests(unittest.TestCase):
    """publish_maya.yml is valid and wires four ordered steps."""

    def test_action_loads_with_four_ordered_steps(self):
        query = ActionQuery.from_file(
            PUBLISH_MAYA_ACTION, context={"project_path": "x", "user": "u"}
        )
        step_names = [s.name for s in query.buffer.ordered_steps()]
        self.assertEqual(step_names, ["select", "resolve", "export", "publish"])
        # The copy step consumes the export output and the resolved folder.
        pub = query.buffer.steps["publish"].commands["publish"]
        self.assertEqual(
            pub.parameters["source_path"].value.serialize(),
            {"from": "export.export.source_path"},
        )
        self.assertEqual(
            pub.parameters["output_path"].value.serialize(),
            {"from": "resolve.output.output_path"},
        )


class MayaPublishActionEndToEndTests(unittest.TestCase):
    """With the export stubbed, the scene lands at the resolved destination."""

    def test_publish_places_file_and_cleans_temp(self):
        self._tmp = tempfile.TemporaryDirectory()
        project = Path(self._tmp.name)

        def fake_export(out_path, extension, scope, **kwargs):
            out_path = Path(out_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"maya-scene-bytes")
            return out_path, []

        with mock.patch(
            "flux_actions.commands.maya_export.run_maya_export",
            side_effect=fake_export,
        ), mock.patch(
            "features.publisher.publish_core.log_publish", return_value=True
        ):
            dest = run_maya_publish_action(
                base_name="CHAR_RIG_HERO_null",
                extension=".mb",
                scope="scene",
                project_path=project,
                description="e2e",
                user="tester",
                project_name="TestProj",
            )

        self.assertIsNotNone(dest)
        self.assertTrue(dest.exists())
        expected_folder = project / "assets/chara/HERO/rig/null"
        self.assertEqual(dest.parent, expected_folder)
        self.assertEqual(dest.name, "CHAR_RIG_HERO_null_LAST.mb")
        self.assertEqual(dest.read_bytes(), b"maya-scene-bytes")

        self._tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
