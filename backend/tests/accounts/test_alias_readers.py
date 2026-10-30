# test_alias_readers.py - readers show / compare a renamed artist under the current name.
#
# Logs are never rewritten on rename: chat, mentions, activity, calendar and production
# readers map stored names through features.accounts.aliases. Runs on a temp FLUX_ROOT.

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import core.json_manager as jm
from features.accounts import aliases
from features.accounts.alias_views import resolve_production_doc
from features.activity import activity_reader as ar
from features.activity import activity_writer as aw
from features.activity import chat_manager as cm
from features.calendar import calendar_store as cal

from tests.repository._backend import setUpModule, tearDownModule  # noqa: E402,F401


class AliasReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())
        self.users = self._tmp / "USER"
        self.users.mkdir()
        self.projects = self._tmp / "DOSSIER_PROJETS"
        (self.projects / "ALPHA").mkdir(parents=True)
        (self._tmp / "CONFIG").mkdir()
        self.mentions = self._tmp / "CONFIG" / "chatMentions.json"
        self.activity = self._tmp / "CONFIG" / "activite.json"
        jm.invalidate_cache()
        patches = [
            mock.patch("core.paths.get_users_dir", return_value=self.users),
            mock.patch.object(cm, "get_project_chat_path",
                              lambda name: self.projects / name / "teamChat.json"),
            mock.patch.object(cm, "get_mentions_path", lambda: self.mentions),
            mock.patch.object(cm, "get_user_list", lambda: ["NEW", "BOB"]),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        aliases.record_rename("OLD", "NEW")

    def test_chat_message_by_old_shows_new(self):
        cm.send_message("OLD", "hello", project="ALPHA")
        self.assertEqual([m["user"] for m in cm.get_messages(project="ALPHA")], ["NEW"])

    def test_mention_to_old_is_found_by_new(self):
        # @OLD is typed after the rename: it reaches the current name.
        cm.send_message("BOB", "ping @OLD", project="ALPHA")
        mentions = cm.get_mentions("NEW", path=self.mentions)
        self.assertEqual(len(mentions), 1)
        self.assertEqual(mentions[0]["to_user"], "NEW")
        # A mention stored under the old name before the rename is found too.
        cm.get_repository().append_log("mentions_log", str(self.mentions), [
            {"id": "x1", "to_user": "OLD", "from_user": "BOB", "text": "t",
             "date": "2026-01-01", "time": "10:00", "project": "ALPHA"}])
        jm.invalidate_cache()
        found = cm.get_mentions("NEW", path=self.mentions)
        self.assertEqual(len(found), 2)
        self.assertTrue(all(m["to_user"] == "NEW" for m in found))

    def test_activity_filter_by_new_returns_old_events(self):
        aw.log_event("OLD", "publish", "ALPHA", "a.ma", path=self.activity)
        aw.log_event("BOB", "publish", "ALPHA", "b.ma", path=self.activity)
        events = ar.get_all_events(user="NEW", path=self.activity)
        self.assertEqual([e["user"] for e in events], ["NEW"])
        shown, _ = ar.get_events_and_unread(user="NEW", path=self.activity)
        self.assertEqual([e["user"] for e in shown], ["NEW"])
        # the cached log objects were not mutated
        raw = ar._load(self.activity)
        self.assertIn("OLD", [e.get("user") for e in raw])

    def test_calendar_same_resolves_aliases(self):
        self.assertTrue(cal._same("OLD", "NEW"))
        self.assertTrue(cal._same("old", "New"))
        self.assertFalse(cal._same("OLD", "BOB"))

    def test_production_assignee_resolved_on_a_copy(self):
        doc = {"shots": [{"locked": {"by": "OLD"}, "task_details": {
            "ANIM": {"assignee": "OLD, BOB",
                     "comments": [{"author": "OLD"}], "retakes": [{"author": "OLD"}]}}}],
               "assets": []}
        out = resolve_production_doc(doc)
        detail = out["shots"][0]["task_details"]["ANIM"]
        self.assertEqual(detail["assignee"], "NEW, BOB")
        self.assertEqual(detail["comments"][0]["author"], "NEW")
        self.assertEqual(detail["retakes"][0]["author"], "NEW")
        self.assertEqual(out["shots"][0]["locked"]["by"], "NEW")
        self.assertEqual(doc["shots"][0]["task_details"]["ANIM"]["assignee"], "OLD, BOB")


if __name__ == "__main__":
    unittest.main()
