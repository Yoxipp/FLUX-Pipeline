# test_loader.py — YAML schema validation, inheritance, output references.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from flux_core.buffers import OutputRef
from flux_core.command_base import CommandBase
from flux_core.loader import ActionSchemaError, load_action
from flux_core.registry import _clear_registry, register

from tests.test_flux_core._registry_guard import setUpModule, tearDownModule  # noqa: F401


def _write(folder: Path, name: str, text: str) -> Path:
    path = folder / f"{name}.yml"
    path.write_text(text, encoding="utf-8")
    return path


class LoaderTests(unittest.TestCase):
    def setUp(self):
        _clear_registry()

        @register("noop")
        class Noop(CommandBase):
            parameters = {"foo": {"type": "str", "value": "default"}}

        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_typo_in_field_fails_with_path(self):
        # 'lavel' instead of 'label' must fail loudly, not be silently ignored.
        src = _write(self.dir, "bad", """
name: bad
steps:
  s:
    index: 10
    commands:
      c:
        command: noop
        parameters:
          foo:
            type: str
            lavel: oops
""")
        with self.assertRaises(ActionSchemaError) as ctx:
            load_action(src)
        self.assertIn("lavel", str(ctx.exception))

    def test_output_reference_becomes_outputref(self):
        src = _write(self.dir, "ref", """
name: ref
steps:
  s:
    index: 10
    commands:
      c:
        command: noop
        parameters:
          foo:
            value: {from: "s.other.result"}
""")
        action = load_action(src)
        value = action.steps["s"].commands["c"].parameters["foo"].value
        self.assertIsInstance(value, OutputRef)
        self.assertEqual((value.step, value.command, value.key), ("s", "other", "result"))

    def test_extends_merges_parent(self):
        _write(self.dir, "pull", """
name: pull
steps:
  s:
    index: 10
    commands:
      c:
        command: noop
        parameters:
          foo:
            type: str
            value: from_parent
""")
        child = _write(self.dir, "publish", """
name: publish
extends: pull
steps:
  s:
    commands:
      c:
        parameters:
          foo:
            value: from_child
""")
        action = load_action(child, search_paths=[self.dir])
        self.assertEqual(action.name, "publish")
        self.assertEqual(action.steps["s"].commands["c"].parameters["foo"].value, "from_child")


if __name__ == "__main__":
    unittest.main()
