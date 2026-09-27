# test_action_graph.py — the read-only node-flow graph of an action's YAML.
#
# Proves build_action_graph turns publish.yml into the expected nodes/edges, so the
# front renders the real step/command tree (not a hand-kept copy). Read only: the
# builder never runs the action.

from __future__ import annotations

import unittest

from flux_actions import build_action_graph, list_action_names


class ActionGraphTests(unittest.TestCase):
    def test_publish_graph_nodes(self):
        graph = build_action_graph("publish")
        self.assertEqual(graph["name"], "publish")
        ids = {n["id"] for n in graph["nodes"]}
        self.assertEqual(ids, {"select.select", "resolve.output", "publish.publish"})

    def test_publish_graph_edges(self):
        graph = build_action_graph("publish")
        order = [e for e in graph["edges"] if e["kind"] == "order"]
        data = [e for e in graph["edges"] if e["kind"] == "dataflow"]

        # Order: select -> resolve -> publish (consecutive steps by index).
        self.assertEqual(
            {(e["source"], e["target"]) for e in order},
            {("select.select", "resolve.output"), ("resolve.output", "publish.publish")},
        )
        # Data flow: 4 wired parameters in publish.yml.
        self.assertEqual(len(data), 4)
        self.assertIn(("resolve.output", "publish.publish"),
                      {(e["source"], e["target"]) for e in data})

    def test_node_carries_command_and_params(self):
        graph = build_action_graph("publish")
        by_id = {n["id"]: n for n in graph["nodes"]}
        resolve = by_id["resolve.output"]
        self.assertEqual(resolve["data"]["command"], "build_output_path")
        self.assertEqual(resolve["data"]["step"], "resolve")
        # its filename param is wired from select.select.filename
        filename = next(p for p in resolve["data"]["params"] if p["name"] == "filename")
        self.assertTrue(filename["wired"])
        self.assertEqual(filename["value"], {"from": "select.select.filename"})

    def test_positions_are_present_for_react_flow(self):
        graph = build_action_graph("publish")
        for node in graph["nodes"]:
            self.assertIn("position", node)
            self.assertEqual(node["position"], {"x": 0, "y": 0})

    def test_list_action_names_includes_publish(self):
        names = list_action_names()
        self.assertIn("publish", names)
        self.assertEqual(names, sorted(names))

    def test_every_yaml_of_the_config_is_listed(self):
        # A4 (2026-09-27): all the actions, not a hand-kept list.
        from flux_actions.graph import CONFIG_DIR

        names = list_action_names()
        for f in CONFIG_DIR.glob("*.yml"):
            self.assertIn(f.stem, names)

    def test_graph_carries_description_steps_and_docs(self):
        graph = build_action_graph("publish_maya")
        self.assertEqual(graph["file"], "publish_maya.yml")
        self.assertIn("Maya", graph["description"])
        self.assertEqual([s["name"] for s in graph["steps"]], ["select", "resolve", "export", "publish"])
        for node in graph["nodes"]:
            self.assertTrue(node["data"]["doc"], node["id"])          # docstring of the command
            for param in node["data"]["params"]:
                self.assertIn("tooltip", param)
        order = [e for e in graph["edges"] if e["kind"] == "order"]
        self.assertEqual(len(order), 3)                               # one per pair of steps

    def test_unknown_action_raises(self):
        with self.assertRaises(KeyError):
            build_action_graph("does_not_exist")


if __name__ == "__main__":
    unittest.main()
