# test_action_query.py — end-to-end headless execution of an action graph.

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from flux_core.action_query import ActionQuery
from flux_core.command_base import CommandBase
from flux_core.registry import _clear_registry, register
from flux_core.status import Status

from tests.test_flux_core._registry_guard import setUpModule, tearDownModule  # noqa: F401


def _write(folder: Path, name: str, text: str) -> Path:
    path = folder / f"{name}.yml"
    path.write_text(text, encoding="utf-8")
    return path


class ActionQueryTests(unittest.TestCase):
    def setUp(self):
        _clear_registry()

        @register("make_type")
        class MakeType(CommandBase):
            parameters = {"publish_type": {"type": "str", "value": "model"}}

            async def run(self, parameters, action_query, logger):
                return {"value": parameters["publish_type"]}

        @register("use_type")
        class UseType(CommandBase):
            parameters = {"incoming": {"type": "str"}}

            async def run(self, parameters, action_query, logger):
                return {"echo": parameters["incoming"].upper()}

        @register("boom")
        class Boom(CommandBase):
            async def run(self, parameters, action_query, logger):
                raise RuntimeError("kaboom")

        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_output_flows_between_steps(self):
        src = _write(self.dir, "flow", """
name: flow
steps:
  setup:
    index: 10
    commands:
      a:
        command: make_type
  build:
    index: 20
    commands:
      b:
        command: use_type
        parameters:
          incoming:
            value: {from: "setup.a.value"}
""")
        diffs = []
        query = ActionQuery.from_file(src, context={"task_id": "T1"}, on_diff=diffs.append)
        status = asyncio.run(query.execute())

        self.assertEqual(status, Status.COMPLETED)
        self.assertEqual(query.buffer.steps["build"].commands["b"].outputs["echo"], "MODEL")
        self.assertTrue(diffs, "the front should have received at least one diff")

    def test_override_before_run(self):
        src = _write(self.dir, "ov", """
name: ov
steps:
  setup:
    index: 10
    commands:
      a:
        command: make_type
""")
        query = ActionQuery.from_file(src)
        query.set_parameter("setup", "a", "publish_type", "rig")
        asyncio.run(query.execute())
        self.assertEqual(query.buffer.steps["setup"].commands["a"].outputs["value"], "rig")

    def test_command_error_halts_and_reports(self):
        src = _write(self.dir, "err", """
name: err
steps:
  one:
    index: 10
    commands:
      a:
        command: boom
  two:
    index: 20
    commands:
      b:
        command: make_type
""")
        query = ActionQuery.from_file(src)
        status = asyncio.run(query.execute())
        self.assertEqual(status, Status.ERROR)
        # The second step must never have started.
        self.assertEqual(query.buffer.steps["two"].status, Status.WAITING)


if __name__ == "__main__":
    unittest.main()
