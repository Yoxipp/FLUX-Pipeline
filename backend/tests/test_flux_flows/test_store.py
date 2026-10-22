# P1 (2026-10-22): scoped store, working file + frozen versions (01 §6, ADR 0058).

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from flux_flows import store
from flux_flows.model import parse_flow
from flux_flows.store import FlowStoreError


def _flow(name: str = "daily", label: str = "Daily", value: int = 1):
    return parse_flow({"flux_flow": 2, "name": name, "label": label,
                       "nodes": {"n1": {"type": "data.value", "params": {"value": value}}}})


class Store(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_flows_store_"))
        self.roots = {s: self.tmp / s / "flows" for s in store.SCOPE_ORDER}
        self.roots["shipped"].mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _history(self, scope: str = "team") -> list:
        path = store.history_path(self.roots, scope)
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []

    def test_save_overwrites_and_logs(self) -> None:
        state = store.save_flow(self.roots, "team", _flow(), user="ADAM")
        self.assertEqual((state["revision"], state["current"]), (1, 0))
        state = store.save_flow(self.roots, "team", _flow(label="B"), user="ADAM", base_revision=1)
        self.assertEqual(state["revision"], 2)
        got = store.read_flow(self.roots, "team", "daily")
        self.assertEqual(got["flow"].label, "B")
        self.assertIn("scope: team", got["text"])
        self.assertIsNone(got["flow"].scope)
        self.assertEqual([h["kind"] for h in self._history()], ["save", "save"])
        self.assertEqual(self._history()[0]["user"], "ADAM")
        self.assertFalse((self.roots["team"] / "daily" / "versions").exists())

    def test_new_name_taken_and_stale_revision_conflict(self) -> None:
        store.save_flow(self.roots, "team", _flow(), user="ADAM")
        with self.assertRaises(FlowStoreError) as ctx:
            store.save_flow(self.roots, "team", _flow(), user="BOB")
        self.assertEqual(ctx.exception.status, 409)
        store.save_flow(self.roots, "team", _flow(label="x"), user="BOB", base_revision=1)
        with self.assertRaises(FlowStoreError) as ctx:
            store.save_flow(self.roots, "team", _flow(label="y"), user="ADAM", base_revision=1)
        self.assertEqual((ctx.exception.status, ctx.exception.detail["by"]), (409, "BOB"))
        state = store.save_flow(self.roots, "team", _flow(label="y"), user="ADAM", base_revision=1, force=True)
        self.assertEqual(state["saved_by"], "ADAM")

    def test_increment_only_when_content_changes(self) -> None:
        store.save_flow(self.roots, "team", _flow(), user="ADAM")
        res = store.increment_flow(self.roots, "team", "daily", user="ADAM")
        self.assertEqual((res["created"], res["state"]["current"]), (1, 1))
        res = store.increment_flow(self.roots, "team", "daily", user="ADAM")
        self.assertIsNone(res["created"])
        rev = res["state"]["revision"]
        res = store.increment_flow(self.roots, "team", "daily", user="ADAM", flow=_flow(value=2), base_revision=rev)
        self.assertEqual(res["created"], 2)
        self.assertTrue(store.version_file(self.roots["team"], "daily", 2).is_file())
        self.assertIn("version: 2", store.read_flow(self.roots, "team", "daily", 2)["text"])
        kinds = [h["kind"] for h in self._history()]
        self.assertEqual(kinds, ["save", "increment", "save", "increment"])

    def test_revert_creates_a_new_identical_version(self) -> None:
        store.save_flow(self.roots, "team", _flow(), user="ADAM")
        store.increment_flow(self.roots, "team", "daily", user="ADAM")
        rev = store.read_state(self.roots["team"], "daily")["revision"]
        store.increment_flow(self.roots, "team", "daily", user="ADAM", flow=_flow(value=9), base_revision=rev)
        res = store.revert_flow(self.roots, "team", "daily", 1, user="ADAM")
        self.assertEqual(res["created"], 3)
        v1 = store.read_flow(self.roots, "team", "daily", 1)["flow"]
        v3 = store.read_flow(self.roots, "team", "daily", 3)["flow"]
        self.assertEqual(v1, v3)
        self.assertEqual(store.read_flow(self.roots, "team", "daily")["flow"], v1)
        self.assertEqual([v["version"] for v in store.list_versions(self.roots, "team", "daily")["versions"]], [3, 2, 1])
        self.assertEqual(self._history()[-1]["to_version"], 1)

    def test_orphan_version_is_skipped(self) -> None:
        store.save_flow(self.roots, "team", _flow(), user="ADAM")
        orphan = store.version_file(self.roots["team"], "daily", 5)
        orphan.parent.mkdir(parents=True)
        orphan.write_text("broken", encoding="utf-8")
        self.assertEqual(store.increment_flow(self.roots, "team", "daily", user="ADAM")["created"], 6)

    def test_atomic_write_keeps_the_old_file(self) -> None:
        store.save_flow(self.roots, "team", _flow(), user="ADAM")
        before = store.working_file(self.roots["team"], "daily").read_text(encoding="utf-8")
        with mock.patch.object(store.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                store.save_flow(self.roots, "team", _flow(label="new"), user="ADAM", base_revision=1)
        self.assertEqual(store.working_file(self.roots["team"], "daily").read_text(encoding="utf-8"), before)
        self.assertEqual(list(self.roots["team"].glob(".flux_tmp_*")), [])
        self.assertEqual(store.read_state(self.roots["team"], "daily")["revision"], 1)

    def test_traversal_names_are_refused(self) -> None:
        for name in ("../x", "a/b", "..", "x\\y", "C:", ""):
            with self.subTest(name=name), self.assertRaises(FlowStoreError):
                store.read_flow(self.roots, "team", name)

    def test_shipped_is_read_only(self) -> None:
        (self.roots["shipped"] / "legacy_publish.flow.yml").write_text(
            "flux_flow: 2\nname: legacy_publish\nnodes: {}\nlinks: []\n", encoding="utf-8")
        self.assertEqual(store.read_flow(self.roots, "shipped", "legacy_publish")["flow"].name, "legacy_publish")
        with self.assertRaises(FlowStoreError) as ctx:
            store.save_flow(self.roots, "shipped", _flow("legacy_publish"), user="ADAM")
        self.assertEqual(ctx.exception.status, 403)
        with self.assertRaises(FlowStoreError):
            store.delete_flow(self.roots, "shipped", "legacy_publish", user="ADAM")

    def test_team_copy_shadows_shipped_and_delete_restores_it(self) -> None:
        (self.roots["shipped"] / "publish_x.flow.yml").write_text(
            "flux_flow: 2\nname: publish_x\nnodes: {}\nlinks: []\n", encoding="utf-8")
        store.copy_flow(self.roots, "publish_x", "shipped", "team", user="ADAM")
        self.assertEqual(store.resolve(self.roots, "publish_x"), "team")
        entries = [(e["scope"], e["shadowed"]) for e in store.list_flows(self.roots) if e["name"] == "publish_x"]
        self.assertEqual(entries, [("team", False), ("shipped", True)])
        store.delete_flow(self.roots, "team", "publish_x", user="ADAM")
        self.assertEqual(store.resolve(self.roots, "publish_x"), "shipped")
        trash = list((self.roots["team"] / "_trash").iterdir())
        self.assertEqual(len(trash), 1)
        self.assertTrue((trash[0] / "publish_x.flow.yml").is_file())
        self.assertTrue((trash[0] / "publish_x" / "state.json").is_file())

    def test_resolution_order(self) -> None:
        for scope in ("team", "project", "perso"):
            store.save_flow(self.roots, scope, _flow(), user="ADAM")
            self.assertEqual(store.resolve(self.roots, "daily"), scope)
        self.assertIsNone(store.resolve(self.roots, "nothing"))
        self.assertIsNone(store.history_path(self.roots, "perso"))
        self.assertTrue(store.history_path(self.roots, "project").is_file())

    def test_missing_scope_root(self) -> None:
        roots = dict(self.roots, project=None)
        with self.assertRaises(FlowStoreError):
            store.save_flow(roots, "project", _flow(), user="ADAM")
        self.assertIsNone(store.resolve(roots, "daily"))

    def test_activation_rules(self) -> None:
        store.save_flow(self.roots, "team", _flow("legacy_publish_maya"), user="ADAM")
        store.increment_flow(self.roots, "team", "legacy_publish_maya", user="ADAM")
        with self.assertRaises(FlowStoreError):
            store.set_active(self.roots, "team", "legacy_publish_maya", True, user="ADAM")
        store.save_flow(self.roots, "team", _flow(), user="ADAM")
        with self.assertRaises(FlowStoreError):
            store.set_active(self.roots, "team", "daily", True, user="ADAM")
        store.increment_flow(self.roots, "team", "daily", user="ADAM")
        state = store.set_active(self.roots, "team", "daily", True, user="ADAM")
        self.assertEqual((state["active"], state["active_version"]), (True, 1))
        rev = state["revision"]
        store.increment_flow(self.roots, "team", "daily", user="ADAM", flow=_flow(value=5), base_revision=rev)
        self.assertEqual(store.read_state(self.roots["team"], "daily")["active_version"], 1)

    def test_list_reports_broken_files(self) -> None:
        self.roots["team"].mkdir(parents=True)
        (self.roots["team"] / "broken.flow.yml").write_text("name: broken\nsteps: {}\n", encoding="utf-8")
        entry = store.list_flows(self.roots)[0]
        self.assertIn("migration", entry["error"])


if __name__ == "__main__":
    unittest.main()
