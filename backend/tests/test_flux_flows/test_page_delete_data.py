# Deleting a TOOL page also moves its shared data (pages_data/<id>/) to _trash (bug the maintainer
# 2026-10-30: a page recreated with the same id got the old board back).

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from flux_flows import page_data, page_store, pages


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


if __name__ == "__main__":
    unittest.main()
