# test_houdini_publish_action.py — the Houdini publish action, tested headless.
#
# The cook step talks to a live Houdini, so publish_houdini_rop is mocked here:
# it is the reused block that drives the HTTP client (the DCC boundary), mirrored
# by writing a real file. Everything else is real — the graph, the select step and
# the runner wiring — so this proves the wiring without needing Houdini open.

from __future__ import annotations

import asyncio
import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from flux_core import ActionQuery
from flux_actions import commands as _commands  # noqa: F401  (populate registry)
from flux_actions.runner import PUBLISH_HOUDINI_ACTION, run_houdini_publish_action


class SelectHoudiniPublishTests(unittest.TestCase):
    """The Houdini select validates the scene name and carries the cook intent."""

    def _run(self, base_name, extension=".abc", rop_node_path=None, is_sequence=False):
        from flux_actions.commands.select_houdini_publish import SelectHoudiniPublish

        return asyncio.run(
            SelectHoudiniPublish().run(
                {
                    "base_name": base_name,
                    "extension": extension,
                    "rop_node_path": rop_node_path,
                    "is_sequence": is_sequence,
                },
                None,
                logging.getLogger("test"),
            )
        )

    def test_emits_stem_without_extension(self):
        # publish_houdini_rop appends the extension itself, so select emits the stem.
        out = self._run("CHAR_RIG_HERO_null", ".abc")
        self.assertEqual(out["base_name"], "CHAR_RIG_HERO_null")
        self.assertEqual(out["extension"], ".abc")

    def test_extension_without_dot_is_normalised(self):
        out = self._run("CHAR_RIG_HERO_null", "bgeo")
        self.assertEqual(out["extension"], ".bgeo")

    def test_base_name_extension_is_stripped(self):
        out = self._run("CHAR_RIG_HERO_null.abc", ".abc")
        self.assertEqual(out["base_name"], "CHAR_RIG_HERO_null")

    def test_empty_rop_becomes_none(self):
        # A blank field from the UI means "use the selected node".
        out = self._run("CHAR_RIG_HERO_null", ".abc", rop_node_path="  ")
        self.assertIsNone(out["rop_node_path"])

    def test_rop_and_sequence_pass_through(self):
        out = self._run("CHAR_RIG_HERO_null", ".abc", rop_node_path="/out/geo1", is_sequence=True)
        self.assertEqual(out["rop_node_path"], "/out/geo1")
        self.assertTrue(out["is_sequence"])

    def test_invalid_name_raises(self):
        with self.assertRaises(ValueError):
            self._run("weird", ".abc")


class HoudiniPublishActionLoadTests(unittest.TestCase):
    """publish_houdini.yml is valid and wires two ordered steps."""

    def test_action_loads_with_two_ordered_steps(self):
        query = ActionQuery.from_file(
            PUBLISH_HOUDINI_ACTION, context={"project_path": "x", "user": "u"}
        )
        step_names = [s.name for s in query.buffer.ordered_steps()]
        self.assertEqual(step_names, ["select", "cook"])
        # The cook step consumes the select outputs by named reference.
        cook = query.buffer.steps["cook"].commands["cook"]
        self.assertEqual(
            cook.parameters["base_name"].value.serialize(),
            {"from": "select.select.base_name"},
        )
        self.assertEqual(
            cook.parameters["is_sequence"].value.serialize(),
            {"from": "select.select.is_sequence"},
        )


class HoudiniPublishActionEndToEndTests(unittest.TestCase):
    """With the cook stubbed, the runner returns the rich result and wiring."""

    def test_publish_returns_result_and_forwards_intent(self):
        self._tmp = tempfile.TemporaryDirectory()
        project = Path(self._tmp.name)
        landed = project / "assets/chara/HERO/rig/null/CHAR_RIG_HERO_null_LAST.abc"

        captured = {}

        def fake_cook(project_path, filename, extension, **kwargs):
            captured.update(kwargs)
            captured["filename"] = filename
            captured["extension"] = extension
            landed.parent.mkdir(parents=True, exist_ok=True)
            landed.write_bytes(b"houdini-cache-bytes")
            return {
                "ok": True,
                "path": str(landed),
                "version": 1,
                "version_str": "001",
                "rop_node": "/out/geo1",
                "is_sequence": False,
            }

        with mock.patch(
            "flux_actions.commands.houdini_export.publish_houdini_rop",
            side_effect=fake_cook,
        ):
            result = run_houdini_publish_action(
                base_name="CHAR_RIG_HERO_null",
                extension=".abc",
                project_path=project,
                description="e2e",
                user="tester",
                project_name="TestProj",
                rop_node_path="/out/geo1",
                is_sequence=False,
            )

        # The runner returns the legacy response shape the endpoint hands back.
        self.assertIsNotNone(result)
        self.assertTrue(result["ok"])
        self.assertEqual(result["version_str"], "001")
        self.assertEqual(result["rop_node"], "/out/geo1")
        dest = Path(result["path"])
        self.assertTrue(dest.exists())
        self.assertEqual(dest.name, "CHAR_RIG_HERO_null_LAST.abc")
        self.assertEqual(dest.read_bytes(), b"houdini-cache-bytes")
        # The select intent reached the reused publish block unchanged.
        self.assertEqual(captured["filename"], "CHAR_RIG_HERO_null")
        self.assertEqual(captured["extension"], ".abc")
        self.assertEqual(captured["rop_node_path"], "/out/geo1")
        self.assertEqual(captured["user"], "tester")
        self.assertEqual(captured["description"], "e2e")

        self._tmp.cleanup()

    def test_frame_padding_is_forwarded_to_publish_block(self):
        # The engine path must thread frame_padding through to publish_houdini_rop,
        # so sequences keep the caller's token width instead of the default.
        project = Path(tempfile.mkdtemp())
        landed = project / "assets/chara/HERO/rig/null/CHAR_RIG_HERO_null_LAST.abc"
        captured = {}

        def fake_cook(project_path, filename, extension, **kwargs):
            captured.update(kwargs)
            landed.parent.mkdir(parents=True, exist_ok=True)
            landed.write_bytes(b"x")
            return {
                "ok": True,
                "path": str(landed),
                "version": 1,
                "version_str": "001",
                "rop_node": "/out/geo1",
                "is_sequence": True,
            }

        try:
            with mock.patch(
                "flux_actions.commands.houdini_export.publish_houdini_rop",
                side_effect=fake_cook,
            ):
                run_houdini_publish_action(
                    base_name="CHAR_RIG_HERO_null",
                    extension=".abc",
                    project_path=project,
                    description="",
                    user="tester",
                    is_sequence=True,
                    frame_padding=6,
                )
            self.assertEqual(captured.get("frame_padding"), 6)
        finally:
            import shutil
            shutil.rmtree(project, ignore_errors=True)

    def test_frame_padding_omitted_leaves_publish_default(self):
        # When no padding is given, the engine must NOT pass one, so the publish
        # block applies its own FRAME_PADDING (single source of truth).
        project = Path(tempfile.mkdtemp())
        landed = project / "assets/chara/HERO/rig/null/CHAR_RIG_HERO_null_LAST.abc"
        captured = {}

        def fake_cook(project_path, filename, extension, **kwargs):
            captured.update(kwargs)
            landed.parent.mkdir(parents=True, exist_ok=True)
            landed.write_bytes(b"x")
            return {"ok": True, "path": str(landed), "version": 1, "version_str": "001",
                    "rop_node": "/out/geo1", "is_sequence": False}

        try:
            with mock.patch(
                "flux_actions.commands.houdini_export.publish_houdini_rop",
                side_effect=fake_cook,
            ):
                run_houdini_publish_action(
                    base_name="CHAR_RIG_HERO_null",
                    extension=".abc",
                    project_path=project,
                    description="",
                    user="tester",
                )
            self.assertNotIn("frame_padding", captured)
        finally:
            import shutil
            shutil.rmtree(project, ignore_errors=True)

    def test_failed_cook_returns_none(self):
        project = Path(tempfile.mkdtemp())
        try:
            with mock.patch(
                "flux_actions.commands.houdini_export.publish_houdini_rop",
                return_value={"ok": False, "error": "No ROP node selected in Houdini"},
            ):
                result = run_houdini_publish_action(
                    base_name="CHAR_RIG_HERO_null",
                    extension=".abc",
                    project_path=project,
                    description="",
                    user="tester",
                )
            self.assertIsNone(result)
        finally:
            import shutil
            shutil.rmtree(project, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
