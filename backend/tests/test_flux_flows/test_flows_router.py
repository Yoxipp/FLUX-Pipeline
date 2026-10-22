# P1 (2026-10-22): /flows CRUD routes (01 §14, ADR 0058), rights checked backend side.

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from flux_flows import locations, rights
from routers import flows as flows_router


def _doc(name: str = "daily", label: str = "Daily") -> dict:
    return {"flux_flow": 2, "name": name, "label": label,
            "nodes": {"n1": {"type": "data.value", "params": {"value": 1}}}}


class Router(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_flows_router_"))
        self.roots = {"shipped": locations.shipped_dir(), "team": self.tmp / "ext" / "flows",
                      "project": self.tmp / "proj" / "flows", "perso": self.tmp / "user" / "flows"}
        self.boxes = {}
        app = FastAPI()
        app.include_router(flows_router.router, prefix="/flows")
        self.client = TestClient(app)
        self._patches = [
            mock.patch.object(locations, "roots_for", side_effect=self._roots_for),
            mock.patch.object(rights, "current_rights", side_effect=lambda: rights.rights_from_data("ADAM", self.boxes)),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _roots_for(self, *, user, project):
        roots = dict(self.roots)
        if not project:
            roots["project"] = None
        return roots

    def test_writes_need_the_boxes(self) -> None:
        r = self.client.put("/flows/daily", json={"flow": _doc(), "scope": "perso"})
        self.assertEqual((r.status_code, r.json()["detail"]["message"]), (403, "Case TD requise"))
        self.boxes = {"flows_td": True}
        self.assertEqual(self.client.put("/flows/daily", json={"flow": _doc(), "scope": "perso"}).status_code, 200)
        r = self.client.put("/flows/daily", json={"flow": _doc(), "scope": "team"})
        self.assertEqual((r.status_code, r.json()["detail"]["required"]), (403, "team_td"))
        r = self.client.post("/flows/legacy_publish/copy", json={"from_scope": "shipped", "to_scope": "team"})
        self.assertEqual(r.status_code, 403)

    def test_crud_cycle(self) -> None:
        self.boxes = {"flows_team_td": True}
        self.assertEqual(self.client.put("/flows/daily", json={"flow": _doc(), "scope": "team"}).status_code, 200)
        # Same name again without base_revision = 409.
        r = self.client.put("/flows/daily", json={"flow": _doc(), "scope": "team"})
        self.assertEqual(r.status_code, 409)
        r = self.client.post("/flows/daily/increment",
                             json={"flow": _doc(label="B"), "scope": "team", "base_revision": 1})
        self.assertEqual(r.json()["created"], 1)
        got = self.client.get("/flows/daily").json()
        self.assertEqual((got["scope"], got["category"], got["flow"]["label"]), ("team", "pipe", "B"))
        self.assertEqual(self.client.get("/flows/daily/versions", params={"scope": "team"}).json()["versions"][0]["version"], 1)
        self.assertTrue(self.client.post("/flows/daily/activate", json={"scope": "team"}).json()["active"])
        self.assertFalse(self.client.post("/flows/daily/deactivate", json={"scope": "team"}).json()["active"])
        self.assertEqual(self.client.post("/flows/daily/revert", json={"scope": "team", "to_version": 1}).status_code, 200)
        self.assertEqual(self.client.delete("/flows/daily", params={"scope": "team"}).status_code, 200)
        self.assertEqual(self.client.get("/flows/daily").status_code, 404)

    def test_list_and_legacy(self) -> None:
        listed = self.client.get("/flows").json()
        legacy = [e for e in listed if e["name"] == "legacy_publish_maya"][0]
        self.assertEqual((legacy["scope"], legacy["category"], legacy["legacy"]), ("shipped", "pipe", True))
        got = self.client.get("/flows/legacy_publish_maya").json()
        self.assertTrue(got["legacy"])
        self.assertEqual(got["flow"]["origin"]["name"], "publish_maya")
        # Unlock (Team TD) then activation is refused.
        self.boxes = {"flows_team_td": True}
        r = self.client.post("/flows/legacy_publish_maya/copy", json={"from_scope": "shipped", "to_scope": "team"})
        self.assertEqual(r.status_code, 200)
        self.client.post("/flows/legacy_publish_maya/increment", json={"scope": "team"})
        r = self.client.post("/flows/legacy_publish_maya/activate", json={"scope": "team"})
        self.assertEqual(r.status_code, 409)

    def test_bad_input(self) -> None:
        self.boxes = {"flows_team_td": True}
        r = self.client.put("/flows/other", json={"flow": _doc(), "scope": "team"})
        self.assertEqual(r.status_code, 400)   # name in body != address
        r = self.client.put("/flows/daily", json={"flow": {"name": "daily"}, "scope": "team"})
        self.assertEqual(r.status_code, 422)
        r = self.client.put("/flows/daily", json={"flow": _doc(), "scope": "moon"})
        self.assertEqual(r.status_code, 400)
        r = self.client.put("/flows/daily", json={"flow": _doc(), "scope": "shipped"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.get("/flows/Bad..name").status_code, 400)

    def test_static_routes_win(self) -> None:
        self.assertIn("td", self.client.get("/flows/rights").json())


class Roots(unittest.TestCase):
    def test_project_name_is_a_folder_name(self) -> None:
        for bad in ("..", "a/b", "a\\b", "."):
            with self.assertRaises(ValueError):
                locations.roots_for(user="ADAM", project=bad)


if __name__ == "__main__":
    unittest.main()
