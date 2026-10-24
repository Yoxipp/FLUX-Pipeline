# P7 (2026-10-24): TOOL page store, rev conflict, _history, scopes (04_PAGES_TOOL §2).

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from flux_flows import page_store, pages
from flux_flows.store import FlowStoreError


def _page(page_id: str = "daily_render", label: str = "Daily render"):
    return pages.parse_page({"page": 1, "id": page_id, "label": label,
                             "layout": [{"row": [{"id": "go", "kind": "button", "label": "Go"}]}]})


class Store(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_pages_store_"))
        self.roots = {"shipped": self.tmp / "shipped" / "pages", "team": self.tmp / "ext" / "pages",
                      "project": self.tmp / "proj" / "_flux_setup" / "pages"}
        self.roots["shipped"].mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_then_conflict(self) -> None:
        first = page_store.save_page(self.roots, "team", _page(), user="ADAM")
        self.assertTrue(first["changed"])
        with self.assertRaises(FlowStoreError) as new:
            page_store.save_page(self.roots, "team", _page(), user="BOB")
        self.assertEqual(new.exception.status, 409)
        second = page_store.save_page(self.roots, "team", _page(label="B"), user="BOB", base_rev=first["rev"])
        with self.assertRaises(FlowStoreError) as late:
            page_store.save_page(self.roots, "team", _page(label="C"), user="ADAM", base_rev=first["rev"])
        self.assertEqual((late.exception.status, late.exception.detail["by"]), (409, "BOB"))
        self.assertIn("BOB", str(late.exception))
        forced = page_store.save_page(self.roots, "team", _page(label="C"), user="ADAM", base_rev=first["rev"], force=True)
        self.assertNotEqual(forced["rev"], second["rev"])
        got = page_store.read_page(self.roots, "team", "daily_render")
        self.assertEqual((got["page"].label, got["rev"]), ("C", forced["rev"]))

    def test_unchanged_save_writes_nothing(self) -> None:
        first = page_store.save_page(self.roots, "team", _page(), user="ADAM")
        again = page_store.save_page(self.roots, "team", _page(), user="ADAM", base_rev=first["rev"])
        self.assertFalse(again["changed"])
        self.assertEqual(page_store.list_history(self.roots, "team", "daily_render"), [])

    def test_history_keeps_20_and_ignores_other_pages(self) -> None:
        rev = page_store.save_page(self.roots, "team", _page(), user="ADAM")["rev"]
        page_store.save_page(self.roots, "team", _page("daily_render_two"), user="ADAM")
        for i in range(25):
            rev = page_store.save_page(self.roots, "team", _page(label=f"L{i}"), user="ADAM", base_rev=rev)["rev"]
        self.assertEqual(len(page_store.list_history(self.roots, "team", "daily_render")), 20)
        rev2 = page_store.read_page(self.roots, "team", "daily_render_two")["rev"]
        page_store.save_page(self.roots, "team", _page("daily_render_two", "X"), user="ADAM", base_rev=rev2)
        self.assertEqual(len(page_store.list_history(self.roots, "team", "daily_render_two")), 1)
        self.assertEqual(len(page_store.list_history(self.roots, "team", "daily_render")), 20)

    def test_history_jsonl(self) -> None:
        page_store.save_page(self.roots, "team", _page(), user="ADAM")
        page_store.delete_page(self.roots, "team", "daily_render", user="ADAM")
        lines = [json.loads(l) for l in (self.tmp / "ext" / "history.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([l["kind"] for l in lines], ["page_save", "page_delete"])
        self.assertEqual(lines[0]["page"], "daily_render")
        page_store.save_page(self.roots, "project", _page(), user="ADAM")
        self.assertTrue((self.tmp / "proj" / "_flux_setup" / "flows" / "history.jsonl").is_file())

    def test_delete_goes_to_trash(self) -> None:
        page_store.save_page(self.roots, "team", _page(), user="ADAM")
        done = page_store.delete_page(self.roots, "team", "daily_render", user="ADAM")
        self.assertTrue(Path(done["trash"]).is_file())
        self.assertIsNone(page_store.resolve(self.roots, "daily_render"))
        with self.assertRaises(FlowStoreError) as gone:
            page_store.delete_page(self.roots, "team", "daily_render", user="ADAM")
        self.assertEqual(gone.exception.status, 404)

    def test_project_wins_and_team_is_shadowed(self) -> None:
        page_store.save_page(self.roots, "team", _page(label="Team"), user="ADAM")
        page_store.save_page(self.roots, "project", _page(label="Projet"), user="ADAM")
        self.assertEqual(page_store.resolve(self.roots, "daily_render"), "project")
        listed = {(e["scope"], e["shadowed"]) for e in page_store.list_pages(self.roots)}
        self.assertEqual(listed, {("project", False), ("team", True)})

    def test_templates_are_read_only_and_apart(self) -> None:
        (self.roots["shipped"] / "daily_render.yml").write_text(pages.dump_page(_page()), encoding="utf-8")
        self.assertEqual(page_store.list_pages(self.roots), [])
        self.assertEqual([t["id"] for t in page_store.list_templates(self.roots)], ["daily_render"])
        with self.assertRaises(FlowStoreError) as ro:
            page_store.save_page(self.roots, "shipped", _page(), user="ADAM")
        self.assertEqual(ro.exception.status, 403)

    def test_traversal_and_bad_scope_are_refused(self) -> None:
        for bad in ("../x", "..", "a/b", "Daily"):
            with self.assertRaises(FlowStoreError):
                page_store.read_page(self.roots, "team", bad)
        with self.assertRaises(FlowStoreError):
            page_store.save_page(self.roots, "perso", _page(), user="ADAM")
        with self.assertRaises(FlowStoreError):
            page_store.save_page({**self.roots, "project": None}, "project", _page(), user="ADAM")

    def test_broken_file_is_listed_with_its_error(self) -> None:
        self.roots["team"].mkdir(parents=True)
        (self.roots["team"] / "broken.yml").write_text("page: 1\nid: broken\nlayout: 3\n", encoding="utf-8")
        entry = page_store.list_pages(self.roots)[0]
        self.assertEqual(entry["id"], "broken")
        self.assertTrue(entry["error"])
        with self.assertRaises(FlowStoreError) as bad:
            page_store.read_page(self.roots, "team", "broken")
        self.assertEqual(bad.exception.status, 422)


if __name__ == "__main__":
    unittest.main()
