# test_command_base.py — parameter inheritance, buffer building, validation.

from __future__ import annotations

import logging
import unittest

from flux_core.buffers import OutputRef
from flux_core.command_base import CommandBase
from flux_core.status import Status

_LOG = logging.getLogger("test")


class _Base(CommandBase):
    parameters = {
        "shared": {"type": "str", "value": "base", "label": "Shared"},
        "count": {"type": "int", "value": 1},
    }


class _Child(_Base):
    parameters = {
        # Override a single field of an inherited parameter, add a new one.
        "shared": {"value": "child"},
        "path": {"type": "path", "value": "/tmp/x"},
    }


class MergeTests(unittest.TestCase):
    def test_child_overrides_and_inherits(self):
        merged = _Child.merged_parameters()
        self.assertEqual(merged["shared"]["value"], "child")
        self.assertEqual(merged["shared"]["type"], "str")   # inherited field
        self.assertEqual(merged["shared"]["label"], "Shared")  # inherited field
        self.assertIn("count", merged)                       # inherited param
        self.assertIn("path", merged)                        # own param


class BuildBufferTests(unittest.TestCase):
    def test_overrides_and_yaml_only_param(self):
        buf = _Child.build_buffer("c", overrides={
            "count": {"value": 7},
            "extra": {"type": "str", "value": "yaml"},  # declared only in YAML
        })
        self.assertEqual(buf.parameters["count"].value, 7)
        self.assertEqual(buf.parameters["shared"].value, "child")
        self.assertEqual(buf.parameters["extra"].value, "yaml")


class CheckParametersTests(unittest.TestCase):
    def test_casts_and_flags_invalid(self):
        buf = _Base.build_buffer("b", overrides={"count": {"value": "3"}})
        self.assertTrue(_Base.check_parameters(buf, _LOG))
        self.assertEqual(buf.parameters["count"].value, 3)
        self.assertEqual(buf.status, Status.VALID)

    def test_bad_value_makes_invalid(self):
        buf = _Base.build_buffer("b", overrides={"count": {"value": "notint"}})
        self.assertFalse(_Base.check_parameters(buf, _LOG))
        self.assertEqual(buf.status, Status.INVALID)

    def test_output_ref_is_skipped(self):
        buf = _Base.build_buffer("b", overrides={"count": {"value": OutputRef("s", "c", "k")}})
        # An unresolved reference must not fail validation at this stage.
        self.assertTrue(_Base.check_parameters(buf, _LOG))


class ContextTests(unittest.TestCase):
    def test_missing_required_metadata(self):
        class Needs(CommandBase):
            required_metadata = ["task_id"]

        self.assertFalse(Needs.check_context_metadata({}, _LOG))
        self.assertTrue(Needs.check_context_metadata({"task_id": "T1"}, _LOG))


if __name__ == "__main__":
    unittest.main()
