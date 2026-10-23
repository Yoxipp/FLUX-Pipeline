# P3 (2026-10-23): team Python nodes, CONFIG/extensions/nodes/*.py reloaded per file.

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from flux_flows import locations
from flux_flows.nodes import registry
from routers import flows as flows_router
from tests.test_flux_flows._flow_helpers import flow, run_flow

NODE = ("from flux_flows.nodes.registry import flow_node, port\n"
        "@flow_node('{type}', 'X', outputs=[port('value', 'int')])\n"
        "def body(ctx, inputs, params):\n    return {{'value': {value}}}\n")


class TeamNodes(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_team_nodes_"))
        registry.ensure_builtin()

    def tearDown(self) -> None:
        registry.load_team_nodes(None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name: str, text: str) -> Path:
        path = self.tmp / name
        path.write_text(text, encoding="utf-8")
        st = path.stat()   # force a new signature even within the same mtime tick
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
        return path

    def _value(self, node_type: str):
        return registry.get_node(node_type).func(None, {}, {})["value"]

    def test_only_the_changed_file_is_reimported(self) -> None:
        self._write("a.py", NODE.format(type="data.team_a", value=1))
        self._write("b.py", NODE.format(type="data.team_b", value=2))
        self.assertEqual(registry.load_team_nodes(self.tmp), [])
        func_b = registry.get_node("data.team_b").func
        self._write("a.py", NODE.format(type="data.team_a", value=10))
        registry.load_team_nodes(self.tmp)
        self.assertEqual(self._value("data.team_a"), 10)
        self.assertIs(registry.get_node("data.team_b").func, func_b)   # b untouched

    def test_broken_file_does_not_block_the_others(self) -> None:
        self._write("good.py", NODE.format(type="data.team_good", value=1))
        self._write("bad.py", "# @flow_node\nraise ValueError('boom')\n")
        errors = registry.load_team_nodes(self.tmp)
        self.assertEqual([e["file"] for e in errors], ["bad.py"])
        self.assertIn("boom", errors[0]["error"])
        self.assertIsNotNone(registry.get_node("data.team_good"))
        self._write("bad.py", NODE.format(type="data.team_fixed", value=3))   # fixed: error goes away
        self.assertEqual(registry.load_team_nodes(self.tmp), [])
        self.assertEqual(self._value("data.team_fixed"), 3)

    def test_a_team_file_cannot_take_a_flux_type(self) -> None:
        self._write("steal.py", NODE.format(type="data.value", value=0))
        errors = registry.load_team_nodes(self.tmp)
        self.assertEqual([e["file"] for e in errors], ["steal.py"])
        self.assertEqual(registry.get_node("data.value").source, "flux")

    def test_removed_file_unloads_its_nodes(self) -> None:
        path = self._write("a.py", NODE.format(type="data.team_a", value=1))
        registry.load_team_nodes(self.tmp)
        path.unlink()
        registry.load_team_nodes(self.tmp)
        self.assertIsNone(registry.get_node("data.team_a"))

    def test_shipped_template_loads_and_simulates(self) -> None:
        shutil.copy(locations.shipped_dir() / "team_node_template.py", self.tmp / "hello.py")
        self.assertEqual(registry.load_team_nodes(self.tmp), [])
        spec = registry.get_node("data.team_hello")
        self.assertEqual((spec.source, spec.file, spec.effect), ("team", "hello.py", True))
        out = spec.simulate(None, {"name": "ADAM"}, {})
        self.assertIn("ADAM", out["lines"][0]["text_fr"])

    def test_engine_loads_team_nodes_before_refusing(self) -> None:
        self._write("a.py", NODE.format(type="data.team_a", value=7))
        f = flow({"n1": "event.manual", "a": "data.team_a"}, [])
        with mock.patch.object(locations, "team_nodes_dir", return_value=self.tmp):
            rec = run_flow(f)
        self.assertNotIn("E_UNKNOWN_NODE", [i["code"] for i in rec["issues"]])

    def test_template_route(self) -> None:
        app = FastAPI()
        app.include_router(flows_router.router, prefix="/flows")
        with mock.patch.object(locations, "team_nodes_dir", return_value=self.tmp):
            body = TestClient(app).get("/flows/nodes/template").json()
        self.assertEqual(body["filename"], "team_node_template.py")
        self.assertIn("@flow_node", body["text"])
        self.assertEqual(body["folder"], str(self.tmp))


if __name__ == "__main__":
    unittest.main()
