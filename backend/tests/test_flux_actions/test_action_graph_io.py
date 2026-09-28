# B4 (2026-09-28): the Graph YAML shows inputs, outputs, notes and hidden hooks.

from __future__ import annotations

import unittest

from flux_actions.graph import build_action_graph


class ActionGraphIO(unittest.TestCase):
    def setUp(self) -> None:
        self.g = build_action_graph("publish")
        self.nodes = {n["id"]: n["data"] for n in self.g["nodes"]}

    def test_inputs_read_from_the_runner(self) -> None:
        got = {(i["kind"], i["name"], i["target"]) for i in self.g["inputs"]}
        self.assertIn(("context", "project_path", ""), got)
        self.assertIn(("runtime", "source_path", "select.select"), got)
        self.assertIn(("runtime", "description", "publish.publish"), got)

    def test_outputs_are_the_returned_keys(self) -> None:
        self.assertEqual(self.nodes["resolve.output"]["outputs"], ["output_path"])
        self.assertIn("dest_path", self.nodes["publish.publish"]["outputs"])

    def test_yaml_comments_become_notes(self) -> None:
        self.assertIn("set at run time", self.nodes["select.select"]["note"])

    def test_copy_publish_lists_files_and_hooks(self) -> None:
        kinds = {(e["kind"], e["label"]) for e in self.nodes["publish.publish"]["effects"]}
        self.assertIn(("output", "LAST"), kinds)
        self.assertIn(("hook", "Proxy USD"), kinds)
        self.assertEqual(self.nodes["select.select"]["effects"], [])


if __name__ == "__main__":
    unittest.main()
