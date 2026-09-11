# test_feeds_via_repository.py - the append-only feeds route through the repository.
#
# End-to-end: chat_manager / activity_reader / activity_writer no longer touch
# json_manager - their JSONL logs go through get_repository()'s log ops. These
# tests seed a log with the repository and read it back through the store (and
# vice-versa), proving the reroute keeps the on-disk JSONL format, the read/write
# paths, the `sig=` cache hint and the fresh read used by mark-as-read.
#
# Feeds are addressed by their own path (transitional doc_id) in distinct
# collections, so we just inject `path=` - no factory patch needed.

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import core.json_manager as jm
from core.repository_factory import get_repository
from features.activity import activity_reader as ar
from features.activity import chat_manager as cm


def _ev(i: int) -> dict:
    return {"id": f"e{i}", "user": "A", "action": "publish", "project": "P",
            "date": "2026-09-01", "time": f"10:0{i}", "read": False}


class FeedsViaRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())
        jm.invalidate_cache()

    # ── activity ──────────────────────────────────────────────────────────────
    def test_activity_repo_write_read_through_store(self):
        log = self._tmp / "activite.json"
        repo = get_repository()
        self.assertTrue(repo.append_log("activity_log", str(log), [_ev(0), _ev(1)]))
        events, unread = ar.get_events_and_unread(limit=50, path=log)
        self.assertEqual({e["id"] for e in events}, {"e0", "e1"})
        self.assertEqual(unread, 2)

    def test_activity_store_write_is_jsonl_on_disk(self):
        from features.activity import activity_writer as aw
        log = self._tmp / "activite.json"
        self.assertTrue(aw.log_event("A", "publish", "P", filename="x.ma", path=log))
        raw = log.read_text(encoding="utf-8")
        self.assertFalse(raw.lstrip().startswith("["))          # JSONL, not an array
        lines = [l for l in raw.splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["action"], "publish")

    def test_mark_as_read_uses_fresh_repo_read(self):
        log = self._tmp / "activite.json"
        get_repository().append_log("activity_log", str(log), [_ev(0)])
        # Unknown id -> False (fresh read sees the live ids); known id -> True.
        self.assertFalse(ar.mark_as_read("nope", path=log))
        self.assertTrue(ar.mark_as_read("e0", path=log))
        _, unread = ar.get_events_and_unread(limit=50, path=log)
        self.assertEqual(unread, 0)

    # ── chat ──────────────────────────────────────────────────────────────────
    def test_chat_send_then_get_through_repo(self):
        chat = self._tmp / "teamChat.json"
        self.assertTrue(cm.send_message("BOB", "hello team", path=chat))
        msgs = cm.get_messages(limit=10, path=chat)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["message"], "hello team")
        # On disk: one JSONL line, not a JSON array.
        raw = chat.read_text(encoding="utf-8")
        self.assertFalse(raw.lstrip().startswith("["))
        self.assertEqual(len([l for l in raw.splitlines() if l.strip()]), 1)

    # ── mentions ──────────────────────────────────────────────────────────────
    def test_mentions_repo_seed_read_and_mark(self):
        mpath = self._tmp / "chatMentions.json"
        get_repository().append_log("mentions_log", str(mpath), [
            {"id": "m1", "to_user": "ADAM", "from_user": "BOB", "text": "@adam hi",
             "date": "2026-09-01", "time": "10:00", "read": False},
        ])
        mentions, unread = cm.get_mentions_and_unread("ADAM", path=mpath)
        self.assertEqual(unread, 1)
        self.assertEqual(mentions[0]["id"], "m1")
        self.assertTrue(cm.mark_mentions_read("ADAM", path=mpath))
        _, unread = cm.get_mentions_and_unread("ADAM", path=mpath)
        self.assertEqual(unread, 0)


if __name__ == "__main__":
    unittest.main()
