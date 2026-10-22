# P1 (2026-10-22): port types, can_connect (01 §3, ADR 0058) and the @flow_node registry.

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from flux_flows.nodes import registry
from flux_flows.nodes.registry import NodeDefinitionError, flow_node, port
from flux_flows.types import can_connect, is_valid_type


class Types(unittest.TestCase):
    def test_valid_types(self) -> None:
        for t in ("exec", "any", "path", "list[path]", "list[list[str]]", "session[maya]", "session[*]"):
            self.assertTrue(is_valid_type(t), t)
        for t in ("string", "list[exec]", "session[]", "list[]", "Path"):
            self.assertFalse(is_valid_type(t), t)

    def test_ok_and_implicit(self) -> None:
        cases = {
            ("path", "path"): "ok", ("session[maya]", "session[maya]"): "ok",
            ("int", "float"): "implicit", ("dir", "path"): "implicit", ("dir", "str"): "implicit",
            ("path", "str"): "implicit", ("publish", "any"): "implicit", ("list[path]", "any"): "implicit",
            ("list[dir]", "list[path]"): "implicit", ("list[int]", "list[any]"): "implicit",
            ("session[maya]", "session[*]"): "implicit", ("pattern", "str"): "implicit",
            ("dcc_node", "str"): "implicit",
        }
        for (src, dst), status in cases.items():
            with self.subTest(src=src, dst=dst):
                self.assertEqual(can_connect(src, dst).status, status)

    def test_incompatible_keeps_a_reason(self) -> None:
        for src, dst, word in [
            ("exec", "str", "execution"), ("str", "exec", "execution"), ("any", "path", "any"),
            ("int", "bool", "Compare"), ("float", "int", "Math"), ("str", "path", "Path"),
            ("path", "dir", "parent"), ("dict", "str", "JsonValue"), ("publish", "path", "PublishFields"),
            ("session[maya]", "session[houdini]", "houdini"), ("str", "pattern", "motif"),
            ("list[path]", "path", "ForEach"), ("path", "list[path]", "List"),
        ]:
            with self.subTest(src=src, dst=dst):
                res = can_connect(src, dst)
                self.assertEqual(res.status, "incompatible")
                self.assertIn(word, res.reason_fr)
                self.assertTrue(res.reason_en)
                self.assertNotIn("—", res.reason_fr)

    def test_foreach_fix(self) -> None:
        self.assertEqual(can_connect("list[path]", "path").fix, "insert_foreach")


class Registry(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_flows_nodes_"))
        self._saved = dict(registry._REGISTRY)

    def tearDown(self) -> None:
        registry.load_team_nodes(None)
        registry._REGISTRY.clear()
        registry._REGISTRY.update(self._saved)
        registry._TEAM_SIG = None
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_declaration_checks(self) -> None:
        with self.assertRaises(NodeDefinitionError):
            flow_node("nofamily", "X")
        with self.assertRaises(NodeDefinitionError):
            flow_node("render.thing", "X")
        with self.assertRaises(NodeDefinitionError):
            flow_node("data.bad", "X", inputs=[port("a", "string")])
        with self.assertRaises(NodeDefinitionError):
            flow_node("data.dup", "X", inputs=[port("a", "str"), port("a", "int")])

    def test_team_files_marker_errors_and_reload(self) -> None:
        (self.tmp / "good.py").write_text(
            "from flux_flows.nodes.registry import flow_node, port\n"
            "@flow_node('data.team_value', 'TeamValue', outputs=[port('value', 'int', 'la valeur', 'the value', 3)],\n"
            "           shelf=2, aliases=['const'])\n"
            "def body(ctx, inputs, params):\n    return {'value': 3}\n", encoding="utf-8")
        (self.tmp / "v1_node.py").write_text("raise RuntimeError('a v1 node must not be imported')\n", encoding="utf-8")
        (self.tmp / "broken.py").write_text("# @flow_node\nraise ValueError('boom')\n", encoding="utf-8")
        cat = registry.catalog(self.tmp)
        types = {n["type"]: n for n in cat["nodes"]}
        self.assertIn("data.team_value", types)
        node = types["data.team_value"]
        self.assertEqual((node["source"], node["file"], node["shelf"], node["aliases"]),
                         ("team", "good.py", 2, ["const"]))
        self.assertEqual(node["outputs"][0]["doc_fr"], "la valeur")
        self.assertEqual([e["file"] for e in cat["node_errors"]], ["broken.py"])
        self.assertEqual(len(cat["families"]), 10)
        self.assertTrue(any(t["id"] == "dir" for t in cat["types"]))
        # Unchanged files: no re-import; removed file: its node goes away.
        self.assertEqual(registry.load_team_nodes(self.tmp), cat["node_errors"])
        (self.tmp / "good.py").unlink()
        registry.load_team_nodes(self.tmp)
        self.assertIsNone(registry.get_node("data.team_value"))


if __name__ == "__main__":
    unittest.main()
