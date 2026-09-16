# test_buffers.py — buffer serialisation and minimal diff.

from __future__ import annotations

import unittest

from flux_core.buffers import (
    REMOVED,
    ActionBuffer,
    CommandBuffer,
    OutputRef,
    ParameterBuffer,
    StepBuffer,
    diff_dicts,
)


class SerializeTests(unittest.TestCase):
    def test_action_tree_serialises(self):
        action = ActionBuffer(name="pub", shelf="Publish")
        step = StepBuffer(name="setup", index=10)
        cmd = CommandBuffer(name="a", command="make_type")
        cmd.parameters["p"] = ParameterBuffer(name="p", type="str", value="model")
        step.commands["a"] = cmd
        action.steps["setup"] = step

        data = action.serialize()
        self.assertEqual(data["name"], "pub")
        self.assertEqual(data["steps"]["setup"]["commands"]["a"]["parameters"]["p"]["value"], "model")
        # A missing label falls back to the parameter name.
        self.assertEqual(data["steps"]["setup"]["commands"]["a"]["parameters"]["p"]["label"], "p")

    def test_output_ref_serialises_as_from(self):
        p = ParameterBuffer(name="p", type="str", value=OutputRef("setup", "a", "value"))
        self.assertEqual(p.serialize()["value"], {"from": "setup.a.value"})

    def test_ordered_steps_by_index(self):
        action = ActionBuffer(name="x")
        action.steps["late"] = StepBuffer(name="late", index=20)
        action.steps["early"] = StepBuffer(name="early", index=10)
        self.assertEqual([s.name for s in action.ordered_steps()], ["early", "late"])


class DiffTests(unittest.TestCase):
    def test_changed_leaf_only(self):
        old = {"a": 1, "b": {"c": 2, "d": 3}}
        new = {"a": 1, "b": {"c": 9, "d": 3}}
        self.assertEqual(diff_dicts(old, new), {"b": {"c": 9}})

    def test_added_key(self):
        self.assertEqual(diff_dicts({"a": 1}, {"a": 1, "b": 2}), {"b": 2})

    def test_removed_key_marked(self):
        self.assertEqual(diff_dicts({"a": 1, "b": 2}, {"a": 1}), {"b": REMOVED})

    def test_no_change_is_empty(self):
        self.assertEqual(diff_dicts({"a": {"b": 1}}, {"a": {"b": 1}}), {})


if __name__ == "__main__":
    unittest.main()
