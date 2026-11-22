# test_discord_bot.py - Discord bot step 1 (ADR 0073): link codes, account mapping,
# /mentions, DMs, shared queue, local token. No real Discord: FakeRelay or mocks.

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from features.notify import bot_secret, discord_bot, dispatch, store
from features.notify.channels import SendResult
from tests.notify._relay import FakeRelay

NOW = 1_800_000_000.0


class _SharedFolder(unittest.TestCase):
    """A temp _flux_setup and in-memory User.json documents."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.users: dict[str, dict] = {"LEA": {}, "TOM": {}}
        patches = [
            mock.patch.object(store, "_setup_file", side_effect=lambda p, n: self.tmp / n),
            mock.patch.object(store, "read_user_data", side_effect=lambda n: json.loads(json.dumps(self.users.get(n, {})))),
            mock.patch.object(store, "write_user_data", side_effect=lambda n, d: self.users.__setitem__(n, d) or True),
            mock.patch("utils.user_utils.list_users", side_effect=lambda: sorted(self.users)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)


class LinkTests(_SharedFolder):
    def test_code_is_stored_hashed_and_links_once(self):
        self.assertTrue(store.add_link_code("P", "ABCD2345", "111", NOW))
        raw = (self.tmp / "discord_links.json").read_text(encoding="utf-8")
        self.assertNotIn("ABCD2345", raw)
        prefs = store.link_discord("P", "LEA", "abcd2345", NOW + 1)
        self.assertEqual(prefs["discord_id"], "111")
        self.assertTrue(store.is_linked(prefs))
        self.assertEqual(store.user_for_discord("111"), "LEA")
        store.drop_link_codes("P", {"111"}, NOW + 2)      # host: a used code is removed
        with self.assertRaises(ValueError):
            store.link_discord("P", "TOM", "ABCD2345", NOW + 3)

    def test_link_keeps_discord_name_and_unlink_clears_it(self):
        store.add_link_code("P", "ABCD2345", "111", NOW, "lea_d")
        prefs = store.link_discord("P", "LEA", "ABCD2345", NOW)
        self.assertEqual(prefs["discord_name"], "lea_d")
        self.assertEqual(store.read_user("LEA")["discord_name"], "lea_d")
        prefs = store.write_user("LEA", {"discord_id": ""})      # Delier
        self.assertFalse(store.is_linked(prefs))
        self.assertEqual(prefs["discord_name"], "")

    def test_link_command_passes_the_discord_name(self):
        discord_bot.answer("P", "link", "111", NOW, {}, "lea_d")
        raw = json.loads((self.tmp / "discord_links.json").read_text(encoding="utf-8"))
        self.assertEqual([c["discord_name"] for c in raw["codes"].values()], ["lea_d"])

    def test_expired_code_refused(self):
        store.add_link_code("P", "ABCD2345", "111", NOW)
        with self.assertRaises(ValueError):
            store.link_discord("P", "LEA", "ABCD2345", NOW + store.LINK_TTL_S + 1)

    def test_one_discord_account_for_one_flux_account(self):
        store.add_link_code("P", "AAAA2222", "111", NOW)
        store.add_link_code("P", "BBBB3333", "111", NOW)
        store.link_discord("P", "LEA", "AAAA2222", NOW)
        with self.assertRaises(ValueError):
            store.link_discord("P", "TOM", "BBBB3333", NOW)

    def test_typed_id_is_never_trusted(self):
        store.add_link_code("P", "ABCD2345", "111", NOW)
        store.link_discord("P", "LEA", "ABCD2345", NOW)
        prefs = store.write_user("LEA", {"discord_id": "222"})
        self.assertFalse(store.is_linked(prefs))
        self.assertIsNone(store.user_for_discord("222"))

    def test_bot_counts_as_channel_only_when_linked(self):
        cfg = {**store.PROJECT_DEFAULTS, "discord_bot": {"app_id": "9"}}
        typed = {"channel": "discord", "discord_id": "111", "discord_linked_at": ""}
        self.assertFalse(store.has_channel(typed, cfg))
        self.assertTrue(store.has_channel({**typed, "discord_linked_at": "x"}, cfg))


class CommandTests(_SharedFolder):
    def test_link_answer_gives_a_code(self):
        text = discord_bot.cmd_link("P", "111", NOW)
        code = text.split("**")[1]
        self.assertEqual(len(code), 8)
        store.link_discord("P", "LEA", code, NOW)
        self.assertEqual(store.user_for_discord("111"), "LEA")

    def test_mentions_refused_when_not_linked(self):
        self.assertIn("/link", discord_bot.cmd_mentions("P", "999"))

    def test_mentions_of_this_project_only(self):
        store.add_link_code("P", "ABCD2345", "111", NOW)
        store.link_discord("P", "LEA", "ABCD2345", NOW)
        rows = [{"project": "P", "from_user": "TOM", "text": "@lea check\nça", "date": "2026-10-30", "time": "10:00"},
                {"project": "OTHER", "from_user": "TOM", "text": "pas ici", "date": "2026-10-30", "time": "09:00"}]
        with mock.patch("features.activity.chat_manager.get_mentions", return_value=rows) as get:
            text = discord_bot.cmd_mentions("P", "111")
        get.assert_called_once_with("LEA", unread_only=True)
        self.assertIn("**TOM** : @lea check ça", text)
        self.assertNotIn("pas ici", text)


class Step2Tests(_SharedFolder):
    """/calendar (ADR 0073 step 2; /chat removed by ADR 0091)."""

    def _link(self, user="LEA", discord_id="111"):
        store.add_link_code("P", "ABCD2345", discord_id, NOW)
        store.link_discord("P", user, "ABCD2345", NOW)

    def test_commands_are_registered(self):
        names = {c["name"]: c for c in discord_bot.COMMANDS}
        self.assertEqual({"link", "mentions", "calendar"}, set(names))      # /chat removed (ADR 0091)

    def test_calendar_refused_when_not_linked(self):
        self.assertEqual(discord_bot.cmd_calendar("P", "999", "2026-10-30"), discord_bot.NOT_LINKED)
        prefs = store.write_user("LEA", {"discord_id": "222"})    # typed by hand, never linked
        self.assertFalse(store.is_linked(prefs))
        self.assertEqual(discord_bot.cmd_calendar("P", "222", "2026-10-30"), discord_bot.NOT_LINKED)

    def test_calendar_mine_and_proposals(self):
        self._link()
        items = [
            {"id": "a", "title": "Rig Lea", "owner": "LEA", "created_by": "TOM", "start": "2026-11-02",
             "end": "2026-11-05", "status": "proposed"},
            {"id": "b", "title": "Skin", "owner": "LEA", "created_by": "LEA", "start": "2026-10-20",
             "end": "2026-10-25", "status": "accepted"},
            {"id": "c", "title": "Anim", "owner": "LEA", "created_by": "LEA", "start": "2026-10-30",
             "end": "2026-10-30", "status": "in_progress"},
            {"id": "d", "title": "Fini", "owner": "LEA", "created_by": "LEA", "start": "2026-10-01",
             "end": "2026-10-01", "status": "done"},
            {"id": "e", "title": "Refuse", "owner": "LEA", "created_by": "TOM", "start": "2026-10-01",
             "end": "2026-10-01", "status": "declined"},
            {"id": "f", "title": "Pas a moi", "owner": "TOM", "created_by": "LEA", "start": "2026-10-30",
             "end": "2026-10-30", "status": "proposed"},
        ]
        with mock.patch("features.calendar.calendar_store.load", return_value={"items": items}) as load:
            text = discord_bot.cmd_calendar("P", "111", "2026-10-30")
        load.assert_called_once_with("P")
        self.assertIn("1 proposition(s) a valider", text)
        self.assertIn("2026-11-02 > 2026-11-05 **Rig Lea** (de TOM)", text)
        self.assertIn("**Skin** (pas commence, en retard)", text)
        self.assertIn("2026-10-30 **Anim** (en cours)", text)
        for absent in ("Fini", "Refuse", "Pas a moi"):
            self.assertNotIn(absent, text)

    def test_calendar_empty_and_long(self):
        self._link()
        with mock.patch("features.calendar.calendar_store.load", return_value={"items": []}):
            self.assertIn("Rien pour toi", discord_bot.cmd_calendar("P", "111", "2026-10-30"))
        many = [{"id": str(i), "title": "t" * 200, "owner": "LEA", "created_by": "TOM", "start": "2026-11-01",
                 "end": "2026-11-01", "status": "proposed"} for i in range(30)]
        with mock.patch("features.calendar.calendar_store.load", return_value={"items": many}):
            text = discord_bot.cmd_calendar("P", "111", "2026-10-30")
        self.assertLessEqual(len(text), discord_bot.MAX_CHARS)
        self.assertTrue(text.endswith("- (suite dans FLUX)"))       # whole lines only
        self.assertTrue(all(line.endswith(")") for line in text.splitlines()[1:]))


class ViaBotTests(_SharedFolder):
    def setUp(self):
        super().setUp()
        self.cfg = {**store.PROJECT_DEFAULTS, "discord_bot": {"app_id": "9"}, "discord_webhook": ""}
        self.prefs = {"channel": "discord", "discord_id": "111", "discord_linked_at": "x"}

    def test_host_sends_the_dm_itself(self):
        with mock.patch.object(discord_bot, "hosted_token", return_value="TOK"), \
             mock.patch.object(discord_bot, "send_dm", return_value=SendResult(True, 200)) as dm:
            result = dispatch._via_bot("P", self.cfg, self.prefs, "hello", NOW)
        self.assertTrue(result.ok)
        dm.assert_called_once_with("TOK", "111", "hello", None)

    def test_other_pc_leaves_it_in_the_shared_queue(self):
        store.write_alive("P", "HOST", NOW)
        with mock.patch.object(discord_bot, "hosted_token", return_value=""), \
             mock.patch("core.config.get_current_user", return_value="TOM"):
            result = dispatch._via_bot("P", self.cfg, self.prefs, "hello", NOW + 1)
        self.assertTrue(result.ok)
        items = store.bot_queue_items("P", NOW + 2)
        self.assertEqual([(i["discord_id"], i["text"]) for i in items], [("111", "hello")])
        self.assertTrue((self.tmp / "notify_bot" / "TOM.json").exists())

    def test_offline_bot_falls_back_to_webhook_or_waits(self):
        with mock.patch.object(discord_bot, "hosted_token", return_value=""):
            waiting = dispatch._via_bot("P", self.cfg, self.prefs, "hello", NOW)
            fallback = dispatch._via_bot("P", {**self.cfg, "discord_webhook": "https://x"}, self.prefs, "hello", NOW)
        self.assertFalse(waiting.ok)
        self.assertFalse(waiting.permanent)
        self.assertIsNone(fallback)

    def test_not_linked_uses_the_webhook_path(self):
        self.assertIsNone(dispatch._via_bot("P", self.cfg, {**self.prefs, "discord_linked_at": ""}, "x", NOW))

    def test_pump_sends_each_queued_dm_once(self):
        store.bot_queue_add("P", "TOM", {"id": "a1", "discord_id": "111", "text": "t", "created": NOW}, NOW)
        sent = discord_bot._Sent.__new__(discord_bot._Sent)
        sent.path, sent.ids = self.tmp / "sent.json", {}
        with mock.patch.object(discord_bot, "send_dm", return_value=SendResult(True, 200)) as dm:
            self.assertEqual(discord_bot.pump("P", "TOK", sent, NOW + 1), 1)
            self.assertEqual(discord_bot.pump("P", "TOK", sent, NOW + 2), 0)
        dm.assert_called_once()


class RestTests(unittest.TestCase):
    def setUp(self):
        self.relay = FakeRelay()
        self.addCleanup(self.relay.close)
        self.relay.status = 200
        self.relay.body = b'{"id": "c1"}'
        p = mock.patch.object(discord_bot, "API", self.relay.url)
        p.start()
        self.addCleanup(p.stop)
        discord_bot._dm_channels.clear()

    def test_dm_opens_the_channel_then_posts_without_pings(self):
        result = discord_bot.send_dm("TOK", "111", "hello")
        self.assertTrue(result.ok)
        paths = [r["path"] for r in self.relay.requests]
        self.assertEqual(paths, ["/users/@me/channels", "/channels/c1/messages"])
        self.assertEqual(self.relay.requests[1]["json"]["allowed_mentions"], {"parse": []})

    def test_bad_discord_id_is_permanent(self):
        self.assertTrue(discord_bot.send_dm("TOK", "not-an-id", "x").permanent)
        self.assertEqual(self.relay.requests, [])

    def test_invite_url_asks_no_permission(self):
        # ADR 0091: DMs, slash commands and buttons need no channel permission.
        url = discord_bot.invite_url("9")
        self.assertTrue(url.endswith("permissions=0"))
        self.assertIn("client_id=9", url)


@unittest.skipUnless(sys.platform == "win32", "DPAPI is Windows only")
class SecretTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        bot_secret.PATH_OVERRIDE = self.tmp / "tokens.json"
        self.addCleanup(setattr, bot_secret, "PATH_OVERRIDE", None)

    def test_token_encrypted_on_disk_and_round_trips(self):
        bot_secret.save_token("P", "MTIz.secret-token")
        self.assertNotIn("secret-token", bot_secret.PATH_OVERRIDE.read_text(encoding="utf-8"))
        self.assertEqual(bot_secret.load_token("P"), "MTIz.secret-token")
        self.assertEqual(bot_secret.hosted_projects(), ["P"])
        bot_secret.delete_token("P")
        self.assertEqual(bot_secret.load_token("P"), "")


class ManagerTests(unittest.TestCase):
    def test_disabled_by_env(self):
        with mock.patch.dict(os.environ, {"FLUX_NOTIFY": "1", "FLUX_DISCORD_BOT": "0"}):
            self.assertFalse(discord_bot.start("P"))

    def test_no_token_on_this_pc_means_no_bot(self):
        with mock.patch.dict(os.environ, {"FLUX_NOTIFY": "1", "FLUX_DISCORD_BOT": "1"}), \
             mock.patch.object(bot_secret, "load_token", return_value=""):
            self.assertFalse(discord_bot.start("P"))


if __name__ == "__main__":
    unittest.main()
