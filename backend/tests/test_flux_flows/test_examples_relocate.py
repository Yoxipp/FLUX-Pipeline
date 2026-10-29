# ADR 0069 (2026-10-29): the Exemples category, Dupliquer an example (with its TOOL page),
# Renommer and Changer de portee (relocate: versions and state follow, inactive, old one in the trash).

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from flux_flows import locations, page_store, rights, scheduler, store
from flux_flows.model import parse_flow
from routers import flows as flows_router


def _flow(name: str, page: str = "") -> dict:
    nodes = {"m": {"type": "event.manual"}, "n": {"type": "flux.notify", "params": {"text": "x"}}}
    links = [{"from": "m.then", "to": "n.exec"}]
    if page:
        nodes["p"] = {"type": "event.page_inputs", "params": {"page": page, "ports": {"outputs": {"go": "exec"}}}}
    return {"flux_flow": 2, "name": name, "nodes": nodes, "links": links}


class Relocate(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_relocate_"))
        self.roots = {"shipped": locations.shipped_dir(), "team": self.tmp / "team",
                      "project": self.tmp / "proj" / "_flux_setup" / "flows", "perso": self.tmp / "me"}

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _versions(self, scope: str, name: str) -> dict:
        return store.list_versions(self.roots, scope, name)

    def test_move_takes_versions_and_state_and_deactivates(self) -> None:
        store.increment_flow(self.roots, "project", "daily", user="ADAM", flow=parse_flow(_flow("daily")))
        doc = _flow("daily")
        doc["nodes"]["n"]["params"]["text"] = "y"
        rev = store.read_state(Path(self.roots["project"]), "daily")["revision"]
        store.increment_flow(self.roots, "project", "daily", user="ADAM", flow=parse_flow(doc), base_revision=rev)
        store.set_active(self.roots, "project", "daily", True, user="ADAM")
        root = Path(self.roots["project"])
        (store.flow_folder(root, "daily") / "seen_w.json").write_text("{}", encoding="utf-8")
        got = store.relocate_flow(self.roots, "daily", "project", "perso", user="ADAM")
        self.assertEqual((got["scope"], got["name"]), ("perso", "daily"))
        moved = store.read_flow(self.roots, "perso", "daily")
        self.assertEqual((moved["state"]["current"], moved["state"]["active"]), (2, False))
        self.assertIsNone(moved["state"]["active_version"])
        self.assertEqual(store.read_flow(self.roots, "perso", "daily", 1)["flow"].nodes["n"].params["text"], "x")
        self.assertTrue((store.flow_folder(Path(self.roots["perso"]), "daily") / "seen_w.json").is_file())
        self.assertFalse(store.working_file(root, "daily").exists())          # the old one is in the trash
        self.assertTrue(any((root / "_trash").iterdir()))

    def test_rename_renames_every_version(self) -> None:
        store.increment_flow(self.roots, "team", "old_name", user="ADAM", flow=parse_flow(_flow("old_name")))
        store.relocate_flow(self.roots, "old_name", "team", "team", user="ADAM", new_name="new_name")
        got = store.read_flow(self.roots, "team", "new_name", 1)
        self.assertEqual(got["flow"].name, "new_name")
        self.assertIsNone(store.resolve(self.roots, "old_name"))

    def test_refusals(self) -> None:
        store.save_flow(self.roots, "team", parse_flow(_flow("aa")), user="ADAM")
        store.save_flow(self.roots, "project", parse_flow(_flow("aa")), user="ADAM")
        for args, status in ((("aa", "team", "project"), 409), (("aa", "team", "team"), 400),
                             (("zzz", "team", "project"), 404), (("example_daily_render", "shipped", "team"), 403)):
            with self.assertRaises(store.FlowStoreError) as cm:
                store.relocate_flow(self.roots, *args, user="ADAM")
            self.assertEqual(cm.exception.status, status, args)


class ExamplesRoutes(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_examples_"))
        self.roots = {"shipped": locations.shipped_dir(), "team": self.tmp / "ext" / "flows",
                      "project": self.tmp / "PROJ" / "_flux_setup" / "flows", "perso": self.tmp / "me" / "flows"}
        app = FastAPI()
        app.include_router(flows_router.router, prefix="/flows")
        team_td = rights.rights_from_data("ADAM", {rights.TEAM_TD_KEY: True})
        self._patches = [
            mock.patch.object(locations, "roots_for", side_effect=lambda **_: dict(self.roots)),
            mock.patch.object(rights, "current_rights", side_effect=lambda: team_td),
            mock.patch.object(scheduler, "_SCHEDULER", None),
        ]
        for p in self._patches:
            p.start()
        self.client = TestClient(app).__enter__()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_examples_have_their_category(self) -> None:
        listed = {(f["scope"], f["name"]): f["category"] for f in self.client.get("/flows").json()}
        self.assertEqual(listed[("shipped", "example_daily_render")], "examples")
        self.assertEqual(listed[("shipped", "publish_maya")], "pipe")

    def test_duplicate_an_example_creates_its_page(self) -> None:
        r = self.client.post("/flows/example_daily_render/copy",
                             json={"from_scope": "shipped", "to_scope": "project", "project": "PROJ",
                                   "new_name": "daily_render"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["pages"], [{"page": "daily_render", "status": "created", "scope": "project"}])
        pages_root = locations.page_roots("PROJ")
        self.assertEqual(page_store.resolve(pages_root, "daily_render"), "project")
        listed = {(f["scope"], f["name"]): f["category"] for f in self.client.get("/flows").json()}
        self.assertEqual(listed[("project", "daily_render")], "project")          # a normal flow now
        label = self.client.get("/flows/daily_render", params={"project": "PROJ"}).json()["flow"]["label"]
        self.assertFalse(label.lower().startswith("exemple"), label)
        r = self.client.post("/flows/example_daily_render/copy",
                             json={"from_scope": "shipped", "to_scope": "project", "project": "PROJ",
                                   "new_name": "daily_two"})
        self.assertEqual(r.json()["pages"], [{"page": "daily_render", "status": "exists"}])   # never overwritten

    def test_duplicate_to_team_without_project_creates_a_team_page(self) -> None:
        self.roots["project"] = None
        r = self.client.post("/flows/example_daily_render/copy",
                             json={"from_scope": "shipped", "to_scope": "team", "new_name": "daily_team"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["pages"], [{"page": "daily_render", "status": "created", "scope": "team"}])

    def test_relocate_route(self) -> None:
        store.increment_flow(self.roots, "project", "mine", user="ADAM", flow=parse_flow(_flow("mine")))
        r = self.client.post("/flows/mine/relocate", json={"from_scope": "project", "to_scope": "team",
                                                            "project": "PROJ"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.client.get("/flows/mine", params={"project": "PROJ"}).json()["scope"], "team")
        r = self.client.post("/flows/mine/relocate", json={"from_scope": "team", "to_scope": "team",
                                                            "new_name": "Bad Name"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
