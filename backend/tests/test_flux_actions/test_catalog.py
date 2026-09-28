# B6 (2026-09-28): node catalogue, function nodes, team nodes and team copies of actions.

from __future__ import annotations

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from flux_actions import catalog
from flux_core import ActionQuery
from flux_core.status import Status


class Catalog(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_catalog_"))
        self.p = mock.patch.object(catalog, "_config_dir", return_value=self.tmp)
        self.p.start()

    def tearDown(self) -> None:
        self.p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _doc(self, index_b: int = 20) -> dict:
        return {"name": "demo", "description": "demo action", "steps": [
            {"name": "a", "index": 10, "note": "first", "commands": [
                {"name": "join", "command": "call_function", "note": "a code function",
                 "parameters": {"function": "core.paths:is_subpath", "child": "C:/x/y", "parent": "C:/x"}}]},
            {"name": "b", "index": index_b, "commands": [
                {"name": "echo", "command": "call_function",
                 "parameters": {"function": "json:dumps", "obj": {"from": "a.join.result"}}}]},
        ]}

    def test_commands_and_functions_listed(self) -> None:
        keys = {c["key"] for c in catalog.list_commands()}
        self.assertTrue({"copy_publish", "call_function"} <= keys)
        fns = {f["id"]: f for f in catalog.list_functions()}
        self.assertIn("core.paths:is_subpath", fns)
        self.assertEqual([a["name"] for a in fns["core.paths:is_subpath"]["args"]][:2], ["child", "parent"])

    def test_save_renders_valid_yaml_that_runs(self) -> None:
        path = Path(catalog.save_action(self._doc())["path"])
        text = path.read_text(encoding="utf-8")
        self.assertIn("# demo action", text)
        self.assertIn("        # a code function", text)
        self.assertEqual(catalog.resolve_action_file(Path("x/demo.yml")), path)
        query = ActionQuery.from_file(path)
        self.assertIs(asyncio.run(query.execute()), Status.COMPLETED)
        self.assertEqual(query.buffer.steps["b"].commands["echo"].outputs["result"], "true")

    def test_link_to_a_later_step_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            catalog.save_action(self._doc(index_b=5))

    def test_reset_goes_back_to_the_shipped_file(self) -> None:
        catalog.save_action(self._doc())
        self.assertTrue(catalog.reset_action("demo"))
        self.assertEqual(catalog.resolve_action_file(Path("x/demo.yml")), Path("x/demo.yml"))

    def test_utility_nodes_chain(self) -> None:
        work = self.tmp / "work"
        doc = {"name": "files_demo", "steps": [
            {"name": "a", "index": 10, "commands": [{"name": "dir", "command": "make_folder",
                                                     "parameters": {"path": str(work / "out")}}]},
            {"name": "b", "index": 20, "commands": [{"name": "txt", "command": "write_text", "parameters": {
                "path": str(work / "out" / "note.txt"), "text": "hello"}}]},
            {"name": "c", "index": 30, "commands": [{"name": "ls", "command": "list_files", "parameters": {
                "folder": {"from": "a.dir.path"}, "pattern": "*.txt"}}]},
            {"name": "d", "index": 40, "commands": [{"name": "cp", "command": "copy_file", "parameters": {
                "source": {"from": "c.ls.first"}, "destination": str(work / "copy.txt")}}]},
        ]}
        query = ActionQuery.from_file(Path(catalog.save_action(doc)["path"]))
        self.assertIs(asyncio.run(query.execute()), Status.COMPLETED)
        self.assertEqual((work / "copy.txt").read_text(encoding="utf-8"), "hello")
        self.assertTrue(catalog.list_functions()[0]["useful"])

    def test_team_node_is_written_and_registered(self) -> None:
        res = catalog.save_user_node("team_echo", catalog.node_template("team_echo"))
        self.assertEqual(res["error"], "")
        self.assertIn("team_echo", {c["key"] for c in catalog.list_commands()})


if __name__ == "__main__":
    unittest.main()
