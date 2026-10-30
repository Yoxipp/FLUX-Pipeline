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
        self.assertEqual(saved.json()["issues"], [])
        self.boxes = {}
        listed = self.client.get("/flows/pages").json()
        self.assertEqual([p["id"] for p in listed["pages"]], ["daily_render"])
        self.assertEqual(listed["can_edit"], {"team": False, "project": False})
        got = self.client.get("/flows/pages/daily_render").json()
        self.assertEqual((got["scope"], got["rev"], got["can_edit"]), ("team", saved.json()["rev"], False))
        self.assertNotIn("on_click", got["page"]["layout"][1]["row"][0])   # ADR 0068: dropped
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

    def test_templates_are_listed_apart(self) -> None:
        listed = self.client.get("/flows/pages").json()
        self.assertEqual(listed["pages"], [])
        self.assertIsInstance(listed["templates"], list)

    def test_access_sorts_pages_for_me(self) -> None:
        # ADR 0078: a page for others is still listed (Other tools), with for_me false.
        self.boxes = {"flows_team_td": True}
        mine = dict(_page(), access={"users": ["adam"]})
        theirs = dict(_page("Anim"), id="anim_tools", access={"departments": ["ANIM"], "roles": ["lead"]})
        self.assertEqual(self.client.put("/flows/pages/daily_render", json={"scope": "team", "page": mine}).status_code, 200)
        self.assertEqual(self.client.put("/flows/pages/anim_tools", json={"scope": "team", "page": theirs}).status_code, 200)
        listed = {p["id"]: p for p in self.client.get("/flows/pages").json()["pages"]}
        self.assertEqual((listed["daily_render"]["for_me"], listed["anim_tools"]["for_me"]), (True, False))
        self.assertEqual(listed["anim_tools"]["access"], {"users": [], "roles": ["lead"], "departments": ["ANIM"]})
        got = self.client.get("/flows/pages/daily_render").json()
        self.assertEqual(got["page"]["access"], {"users": ["ADAM"]})
        bad = dict(_page(), access={"roles": ["boss"]})
        self.assertEqual(self.client.put("/flows/pages/daily_render", json={"scope": "team", "page": bad}).status_code, 422)

    def test_viewer_role_and_departments_match(self) -> None:
        from flux_flows import pages
        access = pages.Access(roles=["lead"], departments=["ANIM"])
        self.assertTrue(pages.page_for(None, None))
        self.assertTrue(pages.page_for(pages.Access(), "X"))
        self.assertTrue(pages.page_for(access, "X", "lead", []))
        self.assertTrue(pages.page_for(access, "X", "artist", ["anim"]))
        self.assertFalse(pages.page_for(access, "X", "artist", ["RIG"]))
        # A person picked before a rename keeps access under the new name (ADR 0079).
        with mock.patch("features.accounts.aliases.load_aliases", return_value={"ADAM": "ADAM_FR"}):
            self.assertTrue(pages.page_for(pages.Access(users=["ADAM"]), "ADAM_FR"))
            self.assertFalse(pages.page_for(pages.Access(users=["ADAM"]), "EVA"))
        with mock.patch.object(flows_router, "_viewer", return_value=("artist", ["ANIM"])):
            self.boxes = {"flows_team_td": True}
            doc = dict(_page(), access={"departments": ["ANIM"]})
            self.client.put("/flows/pages/daily_render", json={"scope": "team", "page": doc})
            listed = self.client.get("/flows/pages", params={"project": "P"}).json()["pages"]
            self.assertTrue(listed[0]["for_me"])

    def test_missing_page_is_404(self) -> None:
        self.assertEqual(self.client.get("/flows/pages/nothing_here").status_code, 404)


if __name__ == "__main__":
    unittest.main()
