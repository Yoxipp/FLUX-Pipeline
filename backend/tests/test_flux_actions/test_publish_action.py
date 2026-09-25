# test_publish_action.py — the publish action reproduces the legacy publish.
#
# Two levels of proof:
#   * wiring   : the action graph loads, flows data by reference, and calls the
#                legacy copy half (copy_publish) with the resolved folder fed by
#                the resolve step. No path is computed twice. This is the parity
#                contract now that publish is split into resolve + copy.
#   * end-to-end: a real temp project + a real source file; the action produces
#                 the same active LAST file the legacy path would.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from flux_core import ActionQuery, Status
from flux_actions import commands as _commands  # noqa: F401  (populate registry)
from flux_actions.runner import PUBLISH_ACTION, run_publish_action


class PublishActionLoadTests(unittest.TestCase):
    """The bundled publish.yml is valid and wires three ordered steps."""

    def test_action_loads_with_three_ordered_steps(self):
        query = ActionQuery.from_file(PUBLISH_ACTION, context={"project_path": "x", "user": "u"})
        step_names = [s.name for s in query.buffer.ordered_steps()]
        self.assertEqual(step_names, ["select", "resolve", "publish"])
        # The data-flow reference survived loading as an unresolved OutputRef.
        resolve = query.buffer.steps["resolve"].commands["output"].parameters["filename"]
        self.assertEqual(resolve.value.serialize(), {"from": "select.select.filename"})


class PublishActionWiringTests(unittest.TestCase):
    """The action calls the legacy copy half with the folder the resolve step produced."""

    def test_calls_copy_half_with_resolved_folder(self):
        project_path = Path("/projects/TestProj")
        source_path = Path("/scenes/CHAR_RIG_HERO_null_LAST.mb")
        # Default tokens: CHAR -> assets/chara, RIG -> rig, instance null.
        resolved_folder = project_path / "assets/chara/HERO/rig/null"
        sentinel = resolved_folder / "CHAR_RIG_HERO_null_LAST.mb"

        with mock.patch(
            "flux_actions.commands.copy_publish.run_copy_publish",
            return_value=sentinel,
        ) as copy_half:
            dest = run_publish_action(
                source_path=source_path,
                project_path=project_path,
                description="first pass",
                user="tester",
                project_name="TestProj",
            )

        self.assertEqual(dest, sentinel)
        copy_half.assert_called_once()
        args = copy_half.call_args.args
        # Copy contract: source, the ALREADY-RESOLVED folder, logical name, ...
        self.assertEqual(args[0], source_path)                          # source_path
        self.assertEqual(args[1], resolved_folder)                       # output_path (from resolve)
        self.assertEqual(args[2], "CHAR_RIG_HERO_null_LAST.mb")          # filename
        self.assertEqual(args[3], "first pass")                          # description
        self.assertEqual(args[4], "tester")                              # user
        self.assertEqual(args[5], "TestProj")                            # project_name

    def test_unparseable_source_fails_cleanly(self):
        with mock.patch(
            "flux_actions.commands.copy_publish.run_copy_publish"
        ) as copy_half:
            dest = run_publish_action(
                source_path=Path("/scenes/not_a_flux_name.png"),
                project_path=Path("/projects/TestProj"),
                description="",
                user="tester",
                project_name="TestProj",
            )
        self.assertIsNone(dest)
        # The action stops at the resolve step: no destination resolves for a name
        # whose tokens are undefined, so the copy half is never reached.
        copy_half.assert_not_called()


class PublishActionEndToEndTests(unittest.TestCase):
    """A real file is published to the resolved destination on disk."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        self.source = self.project.parent / "CHAR_RIG_HERO_null_LAST.mb"
        self.source.write_bytes(b"maya-scene-bytes")

    def tearDown(self):
        self.source.unlink(missing_ok=True)
        self._tmp.cleanup()

    def test_publish_creates_last_file_at_resolved_path(self):
        # Keep the activity log (a global CONFIG file) out of the test.
        with mock.patch(
            "features.publisher.publish_core.log_publish", return_value=True
        ):
            dest = run_publish_action(
                source_path=self.source,
                project_path=self.project,
                description="e2e",
                user="tester",
                project_name="TestProj",
            )

        self.assertIsNotNone(dest)
        self.assertTrue(dest.exists())
        # Default tokens: CHAR -> assets/chara, RIG -> rig, instance null.
        expected_folder = self.project / "assets/chara/HERO/rig/null"
        self.assertEqual(dest.parent, expected_folder)
        self.assertEqual(dest.name, "CHAR_RIG_HERO_null_LAST.mb")
        self.assertEqual(dest.read_bytes(), b"maya-scene-bytes")


if __name__ == "__main__":
    unittest.main()
