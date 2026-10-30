# Deleting a TOOL page also moves its shared data (pages_data/<id>/) to _trash (bug the maintainer
# 2026-10-30: a page recreated with the same id got the old board back), and a restore
# puts the page and its data back together, never over a page of the same id.

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from flux_flows import locations, page_data, page_store, pages, rights
from flux_flows.store import FlowStoreError
from routers import flows as flows_router


def _board_page(per: str = "project", collection: str = "wall") -> pages.Page:
    return pages.parse_page({"page": 1, "id": "moodboard", "label": "Moodboard",
                             "data": [{"id": collection, "kind": "board", "per": per}],
                             "layout": [{"row": [{"id": "board", "kind": "board", "source": {"data": collection}}]}]})


CARD = [{"op": "put", "fields": {"type": "card", "x": 0, "y": 0, "text": "old"}}]


class DeleteMovesData(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_page_delete_"))
        self.roots = {"shipped": self.tmp / "shipped" / "pages", "team": self.tmp / "ext" / "pages",
                      "project": self.tmp / "proj" / "_flux_setup" / "pages"}

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, scope: str, page: pages.Page) -> Path:
        spec = page.data[0]
        folder = page_data.collection_dir(self.roots, scope, page.id, spec)
        page_data.write_ops(folder, spec, CARD, user="ADAM")
        return folder

    def _records(self, scope: str, page: pages.Page) -> list:
        folder = page_data.collection_dir(self.roots, scope, page.id, page.data[0])
        return page_data.read_records(folder)["records"]

    def test_recreated_project_page_starts_empty(self) -> None:
        page = _board_page()
        page_store.save_page(self.roots, "project", page, user="ADAM")
        self._write("project", page)
        done = page_store.delete_page(self.roots, "project", "moodboard", user="ADAM")
        trash = Path(done["trash"])
        self.assertEqual([Path(p) for p in done["data_trash"]],
                         [trash.parent / f"{trash.stem}_data"])
        kept = Path(done["data_trash"][0]) / "wall"
        self.assertEqual(page_data.read_records(kept)["records"][0]["text"], "old")
        self.assertFalse((self.roots["project"].parent / "pages_data" / "moodboard").exists())
        page_store.save_page(self.roots, "project", page, user="ADAM")
        self.assertEqual(self._records("project", page), [])

    def test_team_page_moves_team_and_project_data(self) -> None:
        team_page = _board_page("team")
        page_store.save_page(self.roots, "team", team_page, user="ADAM")
        self._write("team", team_page)
        project_side = self.roots["project"].parent / "pages_data" / "moodboard" / "old_wall"
        page_data.write_ops(project_side, _board_page(collection="old_wall").data[0], CARD, user="ADAM")
        done = page_store.delete_page(self.roots, "team", "moodboard", user="ADAM")
        self.assertEqual(len(done["data_trash"]), 2)
        self.assertFalse((self.roots["team"].parent / "pages_data" / "moodboard").exists())
        self.assertFalse(project_side.exists())
        self.assertTrue((self.roots["project"] / "_trash").is_dir())
        page_store.save_page(self.roots, "team", team_page, user="ADAM")
        self.assertEqual(self._records("team", team_page), [])

    def test_shared_project_folder_keeps_the_other_page_collections(self) -> None:
        # A team page (per: project) and a project page with the same id share the folder.
        team_page = _board_page("project", "wall")
        project_page = _board_page("project", "notes")
        page_store.save_page(self.roots, "team", team_page, user="ADAM")
        page_store.save_page(self.roots, "project", project_page, user="ADAM")
        self._write("team", team_page)
        self._write("project", project_page)
        done = page_store.delete_page(self.roots, "project", "moodboard", user="ADAM")
        self.assertEqual([Path(p).name for p in done["data_trash"]], ["notes"])
        self.assertEqual(len(self._records("team", team_page)), 1)
        self.assertEqual(self._records("project", project_page), [])

    def test_page_without_data_still_deletes(self) -> None:
        page = pages.parse_page({"page": 1, "id": "moodboard", "label": "M",
                                 "layout": [{"row": [{"id": "go", "kind": "button", "label": "Go"}]}]})
        page_store.save_page(self.roots, "team", page, user="ADAM")
        done = page_store.delete_page(self.roots, "team", "moodboard", user="ADAM")
        self.assertEqual(done["data_trash"], [])
        self.assertTrue(Path(done["trash"]).is_file())

    def _deleted(self, scope: str = "project") -> str:
        page = _board_page("team" if scope == "team" else "project")
        page_store.save_page(self.roots, scope, page, user="ADAM")
        self._write(scope, page)
        return Path(page_store.delete_page(self.roots, scope, "moodboard", user="ADAM")["trash"]).name

    def test_restore_brings_page_and_board_back(self) -> None:
        for scope in ("project", "team"):
            with self.subTest(scope=scope):
                file = self._deleted(scope)
                listed = page_store.list_trash(self.roots, scope)
                self.assertEqual([(e["file"], e["id"], e["data"], e["exists"]) for e in listed],
                                 [(file, "moodboard", True, False)])
                done = page_store.restore_page(self.roots, scope, file, user="ADAM")
                self.assertEqual(done["id"], "moodboard")
                self.assertEqual(page_store.resolve(self.roots, "moodboard"), "project" if scope == "project" else "team")
                page = page_store.read_page(self.roots, scope, "moodboard")["page"]
                self.assertEqual(self._records(scope, page)[0]["text"], "old")
                self.assertEqual(page_store.list_trash(self.roots, scope), [])
                self.assertFalse(any(any((Path(self.roots[s]) / "_trash").glob("*_data")) for s in ("team", "project")))
                page_store.delete_page(self.roots, scope, "moodboard", user="ADAM")

    def test_restore_never_overwrites_a_page_of_the_same_id(self) -> None:
        file = self._deleted()
        fresh = _board_page()
        page_store.save_page(self.roots, "project", fresh, user="BOB")
        page_data.write_ops(page_data.collection_dir(self.roots, "project", "moodboard", fresh.data[0]),
                            fresh.data[0], [{"op": "put", "fields": {"type": "card", "x": 0, "y": 0, "text": "new"}}],
                            user="BOB")
        self.assertTrue(page_store.list_trash(self.roots, "project")[0]["exists"])
        with self.assertRaises(FlowStoreError) as taken:
            page_store.restore_page(self.roots, "project", file, user="ADAM")
        self.assertEqual(taken.exception.status, 409)
        self.assertEqual([r["text"] for r in self._records("project", fresh)], ["new"])
        self.assertTrue((self.roots["project"] / "_trash" / file).is_file())
        # Page deleted again but its new board still there: the old board is not merged into it.
        page_store.delete_page(self.roots, "project", "moodboard", user="BOB")
        page_data.write_ops(page_data.collection_dir(self.roots, "project", "moodboard", fresh.data[0]),
                            fresh.data[0], CARD, user="BOB")
        with self.assertRaises(FlowStoreError) as busy:
            page_store.restore_page(self.roots, "project", file, user="ADAM")
        self.assertEqual((busy.exception.status, busy.exception.detail["collection"]), (409, "wall"))
        self.assertIsNone(page_store.resolve(self.roots, "moodboard"))

    def test_restore_rejects_unknown_files(self) -> None:
        for name in ("nope_20261030_120000.yml", "../moodboard.yml", "moodboard.yml"):
            with self.assertRaises(FlowStoreError) as gone:
                page_store.restore_page(self.roots, "project", name, user="ADAM")
            self.assertEqual(gone.exception.status, 404)


class RestoreRoute(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_page_restore_"))
        self.roots = {"shipped": locations.shipped_dir(), "team": self.tmp / "ext" / "flows",
                      "project": None, "perso": self.tmp / "user" / "flows"}
        self.boxes: dict = {"flows_team_td": True}
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

    def test_list_and_restore_need_team_td(self) -> None:
        doc = {"page": 1, "id": "moodboard", "label": "Moodboard",
               "layout": [{"row": [{"id": "go", "kind": "button", "label": "Go"}]}]}
        self.assertEqual(self.client.put("/flows/pages/moodboard", json={"scope": "team", "page": doc}).status_code, 200)
        self.assertEqual(self.client.delete("/flows/pages/moodboard", params={"scope": "team"}).status_code, 200)
        listed = self.client.get("/flows/pages/trash").json()
        self.assertEqual(list(listed), ["team"])
        file = listed["team"][0]["file"]
        self.boxes = {}
        self.assertEqual(self.client.post(f"/flows/pages/trash/{file}/restore", json={"scope": "team"}).status_code, 403)
        self.boxes = {"flows_team_td": True}
        done = self.client.post(f"/flows/pages/trash/{file}/restore", json={"scope": "team"})
        self.assertEqual((done.status_code, done.json()["id"]), (200, "moodboard"))
        self.assertEqual(self.client.get("/flows/pages/moodboard").json()["scope"], "team")


if __name__ == "__main__":
    unittest.main()
