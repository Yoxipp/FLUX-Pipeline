# P1 (2026-10-22): v1 actions -> v2 flows (01 §15).

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

from flux_actions import commands  # noqa: F401 - registers the v1 commands
from flux_flows import locations, migrate_v1, rights, store
from flux_flows.model import load_flow_text

CUSTOM = """# my_tool.yml - team tool.
#
# FR:
# Outil maison.
name: my_tool
steps:
  b:
    index: 20
    commands:
      log:
        command: log_message
        parameters:
          text:
            value: {from: "a.fmt.text"}
  a:
    index: 10
    commands:
      fmt:
        command: format_text
        parameters:
          template:
            value: "hello {name}"
"""


def _links(flow) -> set:
    return {(l.from_, l.to) for l in flow.links}


class Convert(unittest.TestCase):
    def test_shipped_files_are_up_to_date(self) -> None:
        # The dev script was run and its output committed: nothing would change.
        reports = migrate_v1.migrate_shipped(write=False)
        self.assertEqual({r["status"] for r in reports}, {"unchanged"}, reports)
        self.assertEqual(len(reports), 5)

    def test_publish_maya_order_and_links(self) -> None:
        flow, report = migrate_v1.convert_action(migrate_v1.v1_config_dir() / "publish_maya.yml",
                                                 flow_name="legacy_publish_maya")
        self.assertIsNone(report["error"])
        chain = ["n1", "n2", "n3", "n4", "n5"]
        commands_in_order = [flow.nodes[n].params["command"] for n in chain[1:]]
        self.assertEqual(commands_in_order, ["select_dcc_publish", "build_output_path", "maya_export", "copy_publish"])
        for a, b in zip(chain, chain[1:]):
            self.assertIn((f"{a}.then", f"{b}.exec"), _links(flow))
        self.assertIn(("n3.output_path", "n5.output_path"), _links(flow))
        self.assertIn(("n4.source_path", "n5.source_path"), _links(flow))
        self.assertEqual(flow.nodes["n3"].params["ports"]["outputs"], {"output_path": "path"})
        self.assertEqual((flow.origin.kind, flow.origin.name, flow.origin.shelf), ("v1", "publish_maya", "publish"))
        self.assertTrue(flow.description.startswith("Publish depuis Maya"))
        self.assertEqual(report["unresolved_links"], [])

    def test_steps_sorted_by_index_and_literals_kept(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="flux_mig_"))
        try:
            (tmp / "my_tool.yml").write_text(CUSTOM, encoding="utf-8")
            flow, report = migrate_v1.convert_action(tmp / "my_tool.yml", flow_name="my_tool")
            self.assertIsNone(report["error"])
            self.assertEqual(flow.nodes["n2"].params["command"], "format_text")
            self.assertEqual(flow.nodes["n2"].params["params"], {"template": "hello {name}"})
            self.assertIn(("n2.text", "n3.text"), _links(flow))
            self.assertEqual(flow.description, "Outil maison.")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_unknown_command_is_reported(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="flux_mig_"))
        try:
            (tmp / "bad.yml").write_text("name: bad\nsteps:\n  s:\n    commands:\n      c: {command: no_such_cmd}\n",
                                         encoding="utf-8")
            flow, report = migrate_v1.convert_action(tmp / "bad.yml", flow_name="bad")
            self.assertIsNone(flow)
            self.assertEqual(report["unknown_commands"], ["no_such_cmd"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_shipped_flows_load(self) -> None:
        paths = list(locations.shipped_dir().glob("legacy_*.flow.yml"))
        self.assertEqual(len(paths), 5)
        for path in paths:
            flow = load_flow_text(path.read_text(encoding="utf-8"))
            self.assertEqual(flow.origin.kind, "v1")


class Team(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_mig_team_"))
        self.actions = self.tmp / "CONFIG" / "actions"
        self.actions.mkdir(parents=True)
        shutil.copy(migrate_v1.v1_config_dir() / "publish.yml", self.actions / "publish.yml")
        (self.actions / "my_tool.yml").write_text(CUSTOM, encoding="utf-8")
        self.nodes_src = self.tmp / "CONFIG" / "nodes"
        self.nodes_src.mkdir()
        (self.nodes_src / "mine.py").write_text("# v1 node\n", encoding="utf-8")
        self.nodes_dst = self.tmp / "CONFIG" / "extensions" / "nodes"
        self.roots = {"team": self.tmp / "CONFIG" / "extensions" / "flows"}
        self.before = {p.name: p.read_bytes() for p in self.actions.iterdir()}

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, dry_run: bool) -> dict:
        return migrate_v1.migrate_team(self.roots, actions_dir=self.actions, nodes_src=self.nodes_src,
                                       nodes_dst=self.nodes_dst, shipped_names=["publish"], user="ADAM",
                                       dry_run=dry_run)

    def _status(self, report: dict) -> dict:
        return {a["flow"]: a["status"] for a in report["actions"]}

    def test_dry_run_writes_nothing(self) -> None:
        report = self._run(True)
        self.assertEqual(self._status(report), {"legacy_publish": "would_write", "my_tool": "would_write"})
        self.assertEqual(report["nodes"], [{"file": "mine.py", "status": "copied"}])
        self.assertFalse(self.roots["team"].exists())
        self.assertFalse(self.nodes_dst.exists())

    def test_write_then_idempotent_and_originals_intact(self) -> None:
        report = self._run(False)
        self.assertEqual(self._status(report), {"legacy_publish": "written", "my_tool": "written"})
        state = store.read_state(self.roots["team"], "legacy_publish")
        self.assertEqual((state["current"], state["active"]), (1, False))
        self.assertTrue(store.version_file(self.roots["team"], "legacy_publish", 1).is_file())
        lines = store.history_path(self.roots, "team").read_text(encoding="utf-8").splitlines()
        migrated = [h["flow"] for h in map(json.loads, lines) if h["kind"] == "migrate"]
        self.assertEqual(sorted(migrated), ["legacy_publish", "my_tool"])
        self.assertTrue((self.nodes_dst / "mine.py").is_file())
        # Second run: nothing written.
        again = self._run(False)
        self.assertEqual(set(self._status(again).values()), {"unchanged"})
        self.assertEqual(again["nodes"], [{"file": "mine.py", "status": "unchanged"}])
        self.assertEqual(store.read_state(self.roots["team"], "legacy_publish")["current"], 1)
        # An edited team flow is never overwritten.
        text = store.working_file(self.roots["team"], "my_tool").read_text(encoding="utf-8")
        edited = load_flow_text(text).model_copy(update={"label": "Edited"})
        store.save_flow(self.roots, "team", edited, user="ADAM", force=True)
        self.assertEqual(self._status(self._run(False))["my_tool"], "exists")
        self.assertEqual({p.name: p.read_bytes() for p in self.actions.iterdir()}, self.before)
        with self.assertRaises(store.FlowStoreError):
            store.set_active(self.roots, "team", "legacy_publish", True, user="ADAM")


class Route(unittest.TestCase):
    def test_migrate_needs_team_td(self) -> None:
        from routers import flows as flows_router

        td = rights.rights_from_data("BOB", {"flows_td": True})
        with mock.patch.object(rights, "current_rights", return_value=td):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(flows_router.post_migrate(flows_router.MigrateBody(dry_run=True)))
        self.assertEqual(ctx.exception.status_code, 403)
        team = rights.rights_from_data("ADAM", {"flows_team_td": True})
        with mock.patch.object(rights, "current_rights", return_value=team), \
             mock.patch.object(migrate_v1, "migrate_team_config", return_value={"dry_run": True}) as run:
            out = asyncio.run(flows_router.post_migrate(flows_router.MigrateBody()))
        run.assert_called_once_with(user="ADAM", dry_run=True)
        self.assertEqual(out, {"dry_run": True})


if __name__ == "__main__":
    unittest.main()
