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


class BoardV2(unittest.TestCase):
    """P3 (2026-10-30): board schema v2, restore for undo, journal compaction (ADR 0071)."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_board_v2_"))
        self.folder = self.tmp / "wall"
        self.board = _page().data[1]

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _put(self, fields, rid=None, user="ADAM", **extra):
        op = {"op": "put", "fields": fields, **extra}
        if rid:
            op["rid"] = rid
        return page_data.write_ops(self.folder, self.board, [op], user=user)["rids"][0]

    def test_flat_style_fields(self) -> None:
        rid = self._put({"type": "shape", "shape": "diamond", "x": 0, "y": 0, "z": 3, "stroke": "blue", "font_size": 18,
                         "bold": True, "group": "g1", "locked": True})
        link = self._put({"type": "link", "from": rid, "to": rid, "label": "next", "dash": "dashed", "arrow_end": True})
        recs = {r["rid"]: r for r in page_data.read_records(self.folder)["records"]}
        self.assertEqual((recs[rid]["shape"], recs[rid]["font_size"], recs[rid]["locked"]), ("diamond", 18.0, True))
        self.assertEqual((recs[link]["dash"], recs[link]["arrow_end"]), ("dashed", True))
        for bad in ({"shape": "star"}, {"dash": "wavy"}, {"font_size": 2}, {"locked": "yes"}, {"style": {}}):
            with self.assertRaises(FlowStoreError):
                self._put(bad, rid)

    def test_two_authors_style_fields_both_kept(self) -> None:
        rid = self._put({"type": "shape", "x": 0, "y": 0})
        time.sleep(0.002)
        self._put({"stroke": "blue"}, rid, user="BOB")
        time.sleep(0.002)
        self._put({"color": "pink"}, rid, user="ADAM")
        rec = page_data.read_records(self.folder)["records"][0]
        self.assertEqual((rec["stroke"], rec["color"]), ("blue", "pink"))

    def test_restore_a_deleted_record(self) -> None:
        rid = self._put({"type": "note", "x": 1, "y": 2, "text": "hi"})
        page_data.write_ops(self.folder, self.board, [{"op": "del", "rid": rid}], user="BOB")
        with self.assertRaises(FlowStoreError):
            self._put({"text": "lost"}, rid)
        self._put({"type": "note", "x": 1, "y": 2, "text": "hi"}, rid, restore=True)
        rec = page_data.read_records(self.folder)["records"][0]
        self.assertEqual((rec["rid"], rec["text"]), (rid, "hi"))
        with self.assertRaises(FlowStoreError) as never:
            self._put({"text": "x"}, "ADAM_never_seen", restore=True)
        self.assertEqual(never.exception.status, 404)

    def test_compaction_gives_the_same_records(self) -> None:
        import random

        rnd = random.Random(7)
        rids = [self._put({"type": "note", "x": 0, "y": 0, "text": str(i)}) for i in range(6)]
        for step in range(300):
            user = rnd.choice(["ADAM", "BOB"])
            rid = rnd.choice(rids)
            live = {r["rid"] for r in page_data.read_records(self.folder)["records"]}
            if rid not in live:
                self._put({"type": "note", "x": step, "y": 0}, rid, user=user, restore=True)
            elif rnd.random() < 0.08:
                page_data.write_ops(self.folder, self.board, [{"op": "del", "rid": rid}], user=user)
            else:
                self._put(rnd.choice([{"x": step}, {"y": step}, {"text": f"t{step}"}, {"color": rnd.choice("ab")}]), rid, user=user)
        before = page_data.read_records(self.folder)["records"]
        path = self.folder / "ADAM.jsonl"
        lines = len(path.read_text(encoding="utf-8").splitlines())
        dropped = page_data.compact_journal(path)
        self.assertGreater(dropped, 0)
        self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), lines - dropped)
        self.assertEqual(page_data.read_records(self.folder)["records"], before)

    def test_compaction_runs_past_the_size(self) -> None:
        rid = self._put({"type": "note", "x": 0, "y": 0})
        with mock.patch.object(page_data, "COMPACT_BYTES", 2000):
            for i in range(60):
                self._put({"x": i}, rid)
        size = (self.folder / "ADAM.jsonl").stat().st_size
        self.assertLess(size, 2000)
        self.assertEqual(page_data.read_records(self.folder)["records"][0]["x"], 59.0)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir() if p.suffix == ".jsonl"), ["ADAM.jsonl"])


class BoardV3(unittest.TestCase):
    """P3 lot B (2026-10-30): frames, free drawing, FLUX cards, shipped templates (ADR 0074)."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_board_v3_"))
        self.folder = self.tmp / "wall"
        self.board = _page().data[1]

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _put(self, fields):
        return page_data.write_ops(self.folder, self.board, [{"op": "put", "fields": fields}], user="ADAM")["rids"][0]

    def test_frame_ink_and_flux_card(self) -> None:
        self._put({"type": "frame", "x": 0, "y": 0, "w": 400, "h": 300, "text": "Plan 1"})
        self._put({"type": "ink", "x": 10, "y": 10, "points": "0,0 4.5,-2 10,8", "stroke_width": 3, "highlight": True})
        for ref in ("asset:CHAR/bob", "shot:SEQ010/SH020", "publish:asset:CHAR/bob/RIG", "publish:shot:SEQ010/SH020/ANIM"):
            self._put({"type": "flux", "x": 0, "y": 0, "ref": ref})
        self.assertEqual(len(page_data.read_records(self.folder)["records"]), 6)
        for bad in ({"points": "0,0 x"}, {"stroke_width": 200}, {"ref": "asset:a/b/c"}, {"ref": "publish:asset:a/b"},
                    {"ref": "task:a/b"}, {"type": "sticker"}):
            with self.assertRaises(FlowStoreError):
                self._put({"type": "ink", "x": 0, "y": 0, **bad})

    def test_shipped_templates_are_valid(self) -> None:
        from flux_flows import board_templates

        got = {t["id"]: t for t in board_templates.list_templates()}
        self.assertEqual(sorted(got), ["moodboard", "planning", "retro", "shotboard", "storyboard"])
        for tpl in got.values():
            self.assertTrue(tpl["label_en"] and tpl["description"])
            keys = {i["key"] for i in tpl["items"]}
            self.assertEqual(len(keys), len(tpl["items"]))
        self.assertEqual(sum(1 for i in got["storyboard"]["items"] if i.get("type") == "link"), 5)

    def test_bad_template(self) -> None:
        from flux_flows import board_templates

        for data in ({"items": []}, {"board": 1, "items": [{"type": "note"}]},
                     {"board": 1, "items": [{"key": "a", "type": "note"}, {"key": "a", "type": "note"}]},
                     {"board": 1, "items": [{"key": "l", "type": "link", "from": "a", "to": "b"}]},
                     {"board": 1, "items": [{"key": "a", "type": "note", "style": {}}]}):
            with self.assertRaises(FlowStoreError):
                board_templates.parse_template(data)


class BoardV5(unittest.TestCase):
    """Separate move / text locks, shotboard and its shot cells (ADR 0083)."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_board_v5_"))
        self.folder = self.tmp / "wall"
        self.board = _page().data[1]

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _put(self, fields, rid=None):
        op = {"op": "put", "fields": fields, **({"rid": rid} if rid else {})}
        return page_data.write_ops(self.folder, self.board, [op], user="ADAM")["rids"][0]

    def test_text_lock_is_its_own_field(self) -> None:
        rid = self._put({"type": "note", "x": 0, "y": 0, "locked": True})
        self._put({"text_locked": False}, rid)
        rec = page_data.read_records(self.folder)["records"][0]
        self.assertEqual((rec["locked"], rec["text_locked"]), (True, False))
        with self.assertRaises(FlowStoreError):
            self._put({"type": "note", "text_locked": "yes"})

    def test_shotboard_and_shot_cells(self) -> None:
        sb = self._put({"type": "shotboard", "x": 0, "y": 0, "w": 1200, "h": 400})
        self._put({"type": "shot", "target": sb, "ref": "shot:SEQ010/SH020", "frame_at": 0.5, "frame_at2": 1.0,
                   "text": "idea"})
        self.assertEqual(len(page_data.read_records(self.folder)["records"]), 2)
        for bad in ({"frame_at": 1.5}, {"frame_at2": -0.1}, {"frame_at": True}):
            with self.assertRaises(FlowStoreError):
                self._put({"type": "shot", "target": sb, "ref": "shot:SEQ010/SH020", **bad})

    def test_templates_are_not_locked_by_default(self) -> None:
        from flux_flows import board_templates

        for tpl in board_templates.list_templates():
            for item in tpl["items"]:
                self.assertNotIn("locked", item, (tpl["id"], item["key"]))
                self.assertNotIn("text_locked", item, (tpl["id"], item["key"]))
        tpl = board_templates.parse_template({"board": 1, "items": [{"key": "a", "type": "note", "locked": True,
                                                                      "text_locked": False}]})
        self.assertEqual((tpl["items"][0]["locked"], tpl["items"][0]["text_locked"]), (True, False))
        shot = next(t for t in board_templates.list_templates() if t["id"] == "shotboard")
        self.assertEqual([i["type"] for i in shot["items"]], ["text", "shotboard"])


class BoardV4(unittest.TestCase):
    """P3 lot C (2026-10-30): comments, reactions, shared timer, comment mentions (ADR 0075)."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_board_v4_"))
        self.folder = self.tmp / "wall"
        self.board = _page().data[1]

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _put(self, fields, user="ADAM"):
        return page_data.write_ops(self.folder, self.board, [{"op": "put", "fields": fields}], user=user)["rids"][0]

    def test_comment_reaction_timer(self) -> None:
        note = self._put({"type": "note", "x": 0, "y": 0, "text": "idee"})
        self._put({"type": "comment", "target": note, "text": "@BOB tu en penses quoi ?"})
        self._put({"type": "reaction", "target": note, "emoji": "like"}, user="BOB")
        self._put({"type": "reaction", "target": note, "emoji": "like"}, user="ADAM")
        self._put({"type": "timer", "ends_at": "2026-10-30T10:05:00+00:00", "seconds": 300})
        recs = page_data.read_records(self.folder)["records"]
        likes = [r for r in recs if r.get("type") == "reaction"]
        self.assertEqual(sorted(r["_created_by"] for r in likes), ["ADAM", "BOB"])
        for bad in ({"type": "reaction", "target": note, "emoji": "fire"}, {"type": "timer", "seconds": 0},
                    {"type": "timer", "ends_at": "bientot"}, {"type": "comment", "target": "../x"}):
            with self.assertRaises(FlowStoreError):
                self._put(bad)

    def test_comment_mentions_notify(self) -> None:
        from flux_flows import board_mentions

        calls = []
        with mock.patch("features.activity.chat_manager.get_user_list", return_value=["ADAM", "BOB", "CLEO"]), \
             mock.patch("features.accounts.aliases.load_aliases", return_value={}), \
             mock.patch("features.notify.hooks.on_mentions", side_effect=lambda *a: calls.append(a)):
            ops = [{"op": "put", "fields": {"type": "comment", "target": "r1", "text": "@bob @ADAM @nobody voir"}},
                   {"op": "put", "fields": {"type": "note", "text": "@BOB"}},
                   {"op": "put", "rid": "c1", "fields": {"type": "comment", "text": "@CLEO edit"}}]
            self.assertEqual(board_mentions.notify_comments(ops, "ADAM", "demo", "board"), 1)
            self.assertEqual(board_mentions.notify_comments(ops, "ADAM", None, "board"), 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:3], ("ADAM", ["BOB"], "demo"))


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

    def test_board_templates_route(self) -> None:
        r = self.client.get("/flows/board_templates")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["templates"]), 5)

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
