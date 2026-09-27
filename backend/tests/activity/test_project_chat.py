# test_project_chat.py - the team chat is per project (DOSSIER_PROJETS/<project>/teamChat.json).

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import core.json_manager as jm
from features.activity import chat_manager as cm

# Pin the JSON backend so a dev config flipped to sqlite does not fail these tests.
from tests.repository._backend import setUpModule, tearDownModule  # noqa: E402,F401


class ProjectChatTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())
        self.projects = self._tmp / "DOSSIER_PROJETS"
        for name in ("ALPHA", "BETA"):
            (self.projects / name).mkdir(parents=True)
        self.mentions = self._tmp / "CONFIG" / "chatMentions.json"
        self.mentions.parent.mkdir()
        jm.invalidate_cache()
        patches = [
            mock.patch.object(cm, "get_project_chat_path",
                              lambda name: self.projects / name / "teamChat.json"),
            mock.patch.object(cm, "get_mentions_path", lambda: self.mentions),
            mock.patch.object(cm, "get_user_list", lambda: ["ALICE", "BOB"]),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_messages_stay_in_their_project(self):
        self.assertTrue(cm.send_message("BOB", "alpha only", project="ALPHA"))
        self.assertTrue(cm.send_message("BOB", "beta only", project="BETA"))
        self.assertEqual([m["message"] for m in cm.get_messages(project="ALPHA")], ["alpha only"])
        self.assertEqual([m["message"] for m in cm.get_messages(project="BETA")], ["beta only"])
        self.assertTrue((self.projects / "ALPHA" / "teamChat.json").exists())

    def test_invalid_or_unknown_project_is_refused(self):
        for bad in ("", None, "..", "../CONFIG", "ALPHA/sub", "C:x"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                cm.resolve_chat_path(bad)
        with self.assertRaises(FileNotFoundError):
            cm.resolve_chat_path("GAMMA")
        with self.assertRaises(FileNotFoundError):
            cm.send_message("BOB", "lost", project="GAMMA")
        self.assertFalse((self.projects / "GAMMA").exists())

    def test_mention_carries_its_project(self):
        cm.send_message("BOB", "hey @alice", project="BETA")
        mentions = cm.get_mentions("ALICE", path=self.mentions)
        self.assertEqual(len(mentions), 1)
        self.assertEqual(mentions[0]["project"], "BETA")


if __name__ == "__main__":
    unittest.main()
