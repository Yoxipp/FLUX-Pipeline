# P7 (2026-10-24): /flows/pages routes (04_PAGES_TOOL, 01 §14), Team TD to edit, everyone reads.

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


def _page(label: str = "Daily render") -> dict:
    return {"page": 1, "id": "daily_render", "label": label, "icon": "film",
            "layout": [{"row": [{"id": "dest_folder", "kind": "dir", "label": "Dossier",
                                 "bind": {"flow": "daily_render", "param": "dest_folder"}}]},
                       {"row": [{"id": "render", "kind": "button", "label": "Lancer",
                                 "on_click": {"flow": "daily_render", "button_id": "render"}}]}]}


def _flow() -> dict:
    return {"flux_flow": 2, "name": "daily_render",
            "interface": [{"id": "dest_folder", "type": "dir", "default": "$FLUX/DAILY"}],
            "nodes": {"b": {"type": "event.button", "params": {"button_id": "render"}}}}


class PagesRouter(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_pages_router_"))
        self.roots = {"shipped": locations.shipped_dir(), "team": self.tmp / "ext" / "flows",
                      "project": self.tmp / "proj" / "flows", "perso": self.tmp / "user" / "flows"}
        self.boxes: dict = {}
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

    def test_edit_needs_team_td_and_everyone_reads(self) -> None:
        r = self.client.put("/flows/pages/daily_render", json={"scope": "team", "page": _page()})
        self.assertEqual((r.status_code, r.json()["detail"]["required"]), (403, "team_td"))
        self.boxes = {"flows_td": True}
        self.assertEqual(self.client.put("/flows/pages/daily_render", json={"scope": "team", "page": _page()}).status_code, 403)
        self.boxes = {"flows_team_td": True}
        saved = self.client.put("/flows/pages/daily_render", json={"scope": "team", "page": _page()})
        self.assertEqual(saved.status_code, 200)
        self.assertIn("P_FLOW_NOT_FOUND", [i["code"] for i in saved.json()["issues"]])
        self.boxes = {}
        listed = self.client.get("/flows/pages").json()
        self.assertEqual([p["id"] for p in listed["pages"]], ["daily_render"])
        self.assertEqual(listed["can_edit"], {"team": False, "project": False})
        got = self.client.get("/flows/pages/daily_render").json()
        self.assertEqual((got["scope"], got["rev"], got["can_edit"]), ("team", saved.json()["rev"], False))
        self.assertEqual(got["page"]["layout"][1]["row"][0]["on_click"]["button_id"], "render")
        self.assertEqual(self.client.delete("/flows/pages/daily_render", params={"scope": "team"}).status_code, 403)

    def test_conflict_and_schema_errors(self) -> None:
        self.boxes = {"flows_team_td": True}
        rev = self.client.put("/flows/pages/daily_render", json={"scope": "team", "page": _page()}).json()["rev"]
        self.client.put("/flows/pages/daily_render", json={"scope": "team", "page": _page("B"), "base_rev": rev})
        late = self.client.put("/flows/pages/daily_render", json={"scope": "team", "page": _page("C"), "base_rev": rev})
        self.assertEqual((late.status_code, late.json()["detail"]["by"]), (409, "ADAM"))
        bad = self.client.put("/flows/pages/daily_render", json={"scope": "team", "page": {**_page(), "colour": 1}})
        self.assertEqual(bad.status_code, 422)
        other = self.client.put("/flows/pages/other_page", json={"scope": "team", "page": _page()})
        self.assertEqual(other.status_code, 400)

    def test_validate_sees_the_flows(self) -> None:
        self.boxes = {"flows_team_td": True}
        self.client.put("/flows/daily_render", json={"flow": _flow(), "scope": "team"})
        r = self.client.post("/flows/pages/validate", json={"page": _page(), "scope": "team"})
        self.assertEqual([i["code"] for i in r.json()["issues"]], ["P_FLOW_INACTIVE"])

    def test_templates_are_listed_apart(self) -> None:
        listed = self.client.get("/flows/pages").json()
        self.assertEqual(listed["pages"], [])
        self.assertIsInstance(listed["templates"], list)

    def test_missing_page_is_404(self) -> None:
        self.assertEqual(self.client.get("/flows/pages/nothing_here").status_code, 404)


if __name__ == "__main__":
    unittest.main()
