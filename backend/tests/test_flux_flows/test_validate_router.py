# P4 (2026-10-23): validation through the API (01 §8, §14): POST /flows/validate,
# save with errors (valid = false), run refused, activation refused,
# E_DESTRUCTIVE_UNCONFIRMED on PUT / increment, W_SHIPPED_CHANGED after an unlock.

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from flux_flows import locations, rights
from routers import flows as flows_router


def _doc(name: str = "daily", erase: bool = False, broken: bool = False) -> dict:
    nodes = {"ev": {"type": "event.manual"},
             "d": {"type": "action.delete", "params": {"path": "$FLUX/tmp/x", "mode": "erase" if erase else "archive"}}}
    links = [{"from": "ev.then", "to": "d.exec"}]
    if broken:
        nodes["c"] = {"type": "action.copy"}           # source and dest empty
        links.append({"from": "d.then", "to": "c.exec"})
    return {"flux_flow": 2, "name": name, "nodes": nodes, "links": links}


class ValidateRouter(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_validate_router_"))
        self.shipped = self.tmp / "shipped"
        self.shipped.mkdir()
        self.roots = {"shipped": self.shipped, "team": self.tmp / "ext" / "flows", "project": None,
                      "perso": self.tmp / "user" / "flows"}
        self.boxes = {"flows_team_td": True}
        app = FastAPI()
        app.include_router(flows_router.router, prefix="/flows")
        self.client = TestClient(app)
        self._patches = [
            mock.patch.object(locations, "roots_for", side_effect=lambda **_: dict(self.roots)),
            mock.patch.object(rights, "current_rights", side_effect=lambda: rights.rights_from_data("ADAM", self.boxes)),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _put(self, doc: dict, **extra):
        return self.client.put(f"/flows/{doc['name']}", json={"flow": doc, "scope": "team", **extra})

    def test_validate_route(self) -> None:
        r = self.client.post("/flows/validate", json={"flow": _doc(broken=True), "scope": "team"})
        body = r.json()
        self.assertEqual(r.status_code, 200)
        self.assertFalse(body["valid"])
        self.assertIn("E_REQUIRED_EMPTY", [i["code"] for i in body["issues"]])
        self.assertTrue(all("message_en" in i and "fix" in i for i in body["issues"]))
        r = self.client.post("/flows/validate", json={"flow": {"flux_flow": 3, "name": "x_y"}, "scope": "team"})
        self.assertEqual([i["code"] for i in r.json()["issues"]], ["E_SCHEMA"])
        self.assertTrue(self.client.post("/flows/validate", json={"flow": _doc(), "scope": "team"}).json()["valid"])

    def test_save_with_errors_is_allowed_and_marked_invalid(self) -> None:
        r = self._put(_doc(broken=True))
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["valid"], r.json()["state"]["valid"]), (False, False))
        state = json.loads((self.roots["team"] / "daily" / "state.json").read_text(encoding="utf-8"))
        self.assertFalse(state["valid"])
        r = self._put(_doc(), base_revision=1)
        self.assertTrue(r.json()["state"]["valid"])

    def test_run_refused_on_errors(self) -> None:
        self.boxes = {"flows_team_td": True, "flows_td": True}
        r = self.client.post("/flows/daily/run", json={"scope": "team", "draft": _doc(broken=True)})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["detail"]["status"], "refused")
        self.assertIn("E_REQUIRED_EMPTY", [i["code"] for i in r.json()["detail"]["issues"]])

    def test_activation_refused_on_errors(self) -> None:
        self._put(_doc(broken=True))
        self.client.post("/flows/daily/increment", json={"scope": "team"})
        r = self.client.post("/flows/daily/activate", json={"scope": "team"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["detail"]["gate"][0]["code"], "E_REQUIRED_EMPTY")

    def test_destructive_needs_the_slider(self) -> None:
        r = self._put(_doc(erase=True))
        self.assertEqual(r.status_code, 409)
        detail = r.json()["detail"]
        self.assertEqual((detail["code"], detail["issues"][0]["node"]), ("E_DESTRUCTIVE_UNCONFIRMED", "d"))
        self.assertFalse((self.roots["team"] / "daily.flow.yml").exists())
        self.assertEqual(self._put(_doc(erase=True), confirmed_destructive=["d"]).status_code, 200)
        # Already destructive in the saved file: no new confirmation.
        self.assertEqual(self._put(_doc(erase=True), base_revision=1).status_code, 200)
        # Archive -> erase on an existing file is a new `!`, increment checks it too.
        self._put(_doc(), base_revision=2)
        r = self.client.post("/flows/daily/increment", json={"flow": _doc(erase=True), "scope": "team",
                                                             "base_revision": 3})
        self.assertEqual(r.status_code, 409)

    def test_shipped_changed_after_unlock(self) -> None:
        (self.shipped / "daily.flow.yml").write_text(
            "flux_flow: 2\nname: daily\nnodes:\n  ev: {type: event.manual, pos: [0, 0], params: {}}\nlinks: []\n",
            encoding="utf-8")
        self.assertEqual(self.client.post("/flows/daily/copy", json={"from_scope": "shipped", "to_scope": "team"})
                         .status_code, 200)
        doc = self.client.get("/flows/daily", params={"scope": "team"}).json()["flow"]
        codes = lambda: [i["code"] for i in self.client.post("/flows/validate", json={"flow": doc, "scope": "team"})
                         .json()["issues"]]
        self.assertNotIn("W_SHIPPED_CHANGED", codes())
        (self.shipped / "daily.flow.yml").write_text(
            "flux_flow: 2\nname: daily\nlabel: New\nnodes:\n  ev: {type: event.manual, pos: [0, 0], params: {}}\n"
            "links: []\n", encoding="utf-8")
        self.assertIn("W_SHIPPED_CHANGED", codes())


if __name__ == "__main__":
    unittest.main()
