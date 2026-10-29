# P7 (2026-10-24): shared page data, one journal per author merged on read (ADR 0066 n°3, n°4).

from __future__ import annotations

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from flux_flows import locations, page_data, page_store, pages, rights
from flux_flows.store import FlowStoreError
from routers import flows as flows_router

PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8cfc0f01f0005000201"
                    "a5d6f0e60000000049454e44ae426082")


def _page(write: str = "all", per: str = "project") -> pages.Page:
    return pages.parse_page({"page": 1, "id": "team", "label": "Team", "icon": "users",
                             "data": [{"id": "messages", "per": per, "write": write,
                                       "fields": [{"id": "text", "type": "text", "required": True},
                                                  {"id": "channel", "type": "select", "options": [{"value": "general"}]},
                                                  {"id": "when", "type": "datetime"}]},
                                      {"id": "wall", "kind": "board", "per": per, "write": write}],
                             "layout": [{"row": [{"id": "chat", "kind": "feed", "source": {"data": "messages"}}]},
                                        {"row": [{"id": "board", "kind": "board", "source": {"data": "wall"}}]}]})


class Journal(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_page_data_"))
        self.folder = self.tmp / "messages"
        self.spec = _page().data[0]
        self.board = _page().data[1]

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_two_authors_merge_and_last_write_wins_per_field(self) -> None:
        rid = page_data.write_ops(self.folder, self.board, [{"op": "put", "fields": {"type": "card", "x": 0, "y": 0, "text": "a"}}],
                                  user="ADAM")["rids"][0]
        time.sleep(0.002)
        page_data.write_ops(self.folder, self.board, [{"op": "put", "rid": rid, "fields": {"x": 50, "y": 60}}], user="BOB")
        time.sleep(0.002)
        page_data.write_ops(self.folder, self.board, [{"op": "put", "rid": rid, "fields": {"text": "b"}}], user="ADAM")
        self.assertEqual(sorted(p.name for p in self.folder.glob("*.jsonl")), ["ADAM.jsonl", "BOB.jsonl"])
        rec = page_data.read_records(self.folder)["records"][0]
        self.assertEqual((rec["x"], rec["y"], rec["text"], rec["_created_by"], rec["_by"]), (50.0, 60.0, "b", "ADAM", "ADAM"))

    def test_del_and_unknown_rid(self) -> None:
        rid = page_data.write_ops(self.folder, self.spec, [{"op": "put", "fields": {"text": "hi"}}], user="ADAM")["rids"][0]
        page_data.write_ops(self.folder, self.spec, [{"op": "del", "rid": rid}], user="BOB")
        self.assertEqual(page_data.read_records(self.folder)["records"], [])
        with self.assertRaises(FlowStoreError) as gone:
            page_data.write_ops(self.folder, self.spec, [{"op": "put", "rid": rid, "fields": {"text": "x"}}], user="ADAM")
        self.assertEqual(gone.exception.status, 404)

    def test_types_and_required(self) -> None:
        for fields in ({"text": 3}, {"text": "a", "channel": "random"}, {"text": "a", "when": "demain"},
                       {"text": "a", "nope": 1}, {"channel": "general"}):
            with self.assertRaises(FlowStoreError):
                page_data.write_ops(self.folder, self.spec, [{"op": "put", "fields": fields}], user="ADAM")
        with self.assertRaises(FlowStoreError):
            page_data.write_ops(self.folder, self.board, [{"op": "put", "fields": {"type": "circle"}}], user="ADAM")
        with self.assertRaises(FlowStoreError):
            page_data.write_ops(self.folder, self.board, [{"op": "put", "fields": {"image": "../x.png"}}], user="ADAM")

    def test_etag(self) -> None:
        first = page_data.read_records(self.folder)
        self.assertTrue(page_data.read_records(self.folder, first["etag"])["unchanged"])
        page_data.write_ops(self.folder, self.spec, [{"op": "put", "fields": {"text": "hi"}}], user="ADAM")
        again = page_data.read_records(self.folder, first["etag"])
        self.assertFalse(again["unchanged"])
        self.assertEqual(len(again["records"]), 1)

    def test_broken_line_is_skipped(self) -> None:
        page_data.write_ops(self.folder, self.spec, [{"op": "put", "fields": {"text": "hi"}}], user="ADAM")
        with open(self.folder / "BOB.jsonl", "w", encoding="utf-8") as fh:
            fh.write('{"op": "put", "rid": "x1", "fields": {"text": "ok"}, "at": "2026"}\n{"op": "pu')
        self.assertEqual(len(page_data.read_records(self.folder)["records"]), 2)

    def test_author_comes_from_the_file(self) -> None:
        self.folder.mkdir(parents=True)
        (self.folder / "BOB.jsonl").write_text(json.dumps({"op": "put", "rid": "r1", "fields": {"text": "x"},
                                                           "at": "2026", "user": "ADAM"}) + "\n", encoding="utf-8")
        self.assertEqual(page_data.read_records(self.folder)["records"][0]["_by"], "BOB")

    def test_bad_user_and_ops(self) -> None:
        with self.assertRaises(FlowStoreError):
            page_data.write_ops(self.folder, self.spec, [{"op": "put", "fields": {"text": "a"}}], user="../ADAM")
        with self.assertRaises(FlowStoreError):
            page_data.write_ops(self.folder, self.spec, [], user="ADAM")
        with self.assertRaises(FlowStoreError):
            page_data.write_ops(self.folder, self.spec, [{"op": "put", "rid": "a/b", "fields": {}}], user="ADAM")

    def test_image_is_copied_by_hash(self) -> None:
        src = self.tmp / "ref.PNG"
        src.write_bytes(PNG)
        name = page_data.add_image(self.folder, str(src))
        self.assertRegex(name, r"^media/[0-9a-f]{20}\.png$")
        self.assertEqual(page_data.add_image(self.folder, str(src)), name)
        self.assertEqual(page_data.media_file(self.folder, name.split("/")[1]).read_bytes(), PNG)
        bad = self.tmp / "notes.txt"
        bad.write_text("x")
        with self.assertRaises(FlowStoreError):
            page_data.add_image(self.folder, str(bad))
        with self.assertRaises(FlowStoreError):
            page_data.media_file(self.folder, "../../secret.png")

    def test_where_the_data_lives(self) -> None:
        roots = {"team": self.tmp / "ext" / "pages", "project": self.tmp / "proj" / "_flux_setup" / "pages"}
        spec = _page(per="team").data[0]
        self.assertEqual(page_data.collection_dir(roots, "team", "team", spec), self.tmp / "ext" / "pages_data" / "team" / "messages")
        spec = _page().data[0]
        self.assertEqual(page_data.collection_dir(roots, "team", "team", spec),
                         self.tmp / "proj" / "_flux_setup" / "pages_data" / "team" / "messages")
        with self.assertRaises(FlowStoreError) as no:
            page_data.collection_dir({**roots, "project": None}, "team", "team", spec)
        self.assertEqual(no.exception.status, 409)


class DataRouter(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_page_data_router_"))
        self.roots = {"shipped": locations.shipped_dir(), "team": self.tmp / "ext" / "flows",
                      "project": self.tmp / "proj" / "flows", "perso": None}
        self.boxes: dict = {}
        app = FastAPI()
        app.include_router(flows_router.router, prefix="/flows")
        self.client = TestClient(app)
        self._patches = [
            mock.patch.object(locations, "roots_for", side_effect=lambda **_: dict(self.roots)),
            mock.patch.object(rights, "current_rights", side_effect=lambda: rights.rights_from_data("BOB", self.boxes)),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _save(self, page: pages.Page) -> None:
        page_store.save_page(locations.page_roots("demo"), "team", page, user="ADAM")

    def test_artist_posts_and_reads(self) -> None:
        self._save(_page())
        r = self.client.post("/flows/pages/team/data/messages", json={"project": "demo", "ops": [
            {"op": "put", "fields": {"text": "Salut", "channel": "general"}}]})
        self.assertEqual(r.status_code, 200, r.text)
        got = self.client.get("/flows/pages/team/data/messages", params={"project": "demo"}).json()
        self.assertEqual([(x["text"], x["_by"]) for x in got["records"]], [("Salut", "BOB")])
        same = self.client.get("/flows/pages/team/data/messages", params={"project": "demo", "etag": got["etag"]}).json()
        self.assertTrue(same["unchanged"])
        self.assertEqual(self.client.get("/flows/pages/team/data/nothing", params={"project": "demo"}).status_code, 404)
        bad = self.client.post("/flows/pages/team/data/messages", json={"project": "demo", "ops": [{"op": "put", "fields": {"x": 1}}]})
        self.assertEqual(bad.status_code, 422)

    def test_team_td_collection(self) -> None:
        self._save(_page(write="team_td"))
        r = self.client.post("/flows/pages/team/data/messages", json={"project": "demo", "ops": [{"op": "put", "fields": {"text": "x"}}]})
        self.assertEqual(r.status_code, 403)
        self.boxes = {"flows_team_td": True}
        r = self.client.post("/flows/pages/team/data/messages", json={"project": "demo", "ops": [{"op": "put", "fields": {"text": "x"}}]})
        self.assertEqual(r.status_code, 200)

    def test_media_route(self) -> None:
        self._save(_page())
        src = self.tmp / "ref.png"
        src.write_bytes(PNG)
        r = self.client.post("/flows/pages/team/data/wall/media", json={"project": "demo", "path": str(src)})
        self.assertEqual(r.status_code, 200, r.text)
        name = r.json()["image"].split("/")[1]
        img = self.client.get(f"/flows/pages/team/data/wall/media/{name}", params={"project": "demo"})
        self.assertEqual((img.status_code, img.headers["content-type"], img.content), (200, "image/png", PNG))


if __name__ == "__main__":
    unittest.main()
