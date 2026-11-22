# test_dm_actions.py - ADR 0091: buttons and menus under a bot DM (Valider, Refuser, Decaler,
# Donner a), per type opt-out, retake comments as events. No real Discord: mocks, FakeRelay.

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from features.notify import discord_bot, dispatch, dm_actions, outbox, store
from features.notify.channels import SendResult
from features.notify.events import make_event, production_changes
from tests.notify._relay import FakeRelay

T0 = 1_800_000_000.0


def _production() -> dict:
    return {"sequences": [{"id": "q_1", "name": "sq010"}],
            "shots": [{"id": "s_1", "seq_id": "q_1", "name": "sh010",
                       "task_details": {"ANIM": {"assignee": "LEA", "status": "WFA"}}}],
            "assets": []}


def _task_event(type_="retake", key="ANIM") -> dict:
    return make_event(type_, "PROJ", "TOM", "SQ010/SH010", key, ["LEA"], ref={"id": "s_1", "task": key})


class ComponentsTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch("utils.user_utils.list_users", return_value=["TOM", "lea", "MAX"])
        p.start()
        self.addCleanup(p.stop)

    def test_task_dm_has_valider_refuser_and_donner_a(self):
        rows = dm_actions.components_for([_task_event()], "LEA")
        buttons = rows[0]["components"]
        self.assertEqual([b["label"] for b in buttons], ["Valider", "Refuser"])
        self.assertEqual(dm_actions.parse_id(buttons[0]["custom_id"])["op"], "ok")
        menu = rows[1]["components"][0]
        self.assertEqual(menu["placeholder"], "Donner a...")
        self.assertEqual([o["value"] for o in menu["options"]], ["lea", "MAX", "TOM"])
        for comp in (*buttons, menu):
            self.assertLessEqual(len(comp["custom_id"]), dm_actions.MAX_ID)

    def test_no_buttons_for_a_digest_a_mention_or_a_publish(self):
        self.assertEqual(dm_actions.components_for([_task_event(), _task_event()], "LEA"), [])
        for kind in ("mention", "publish"):
            self.assertEqual(dm_actions.components_for([make_event(kind, "PROJ", "TOM", "x", "", ["LEA"])], "LEA"), [])
        self.assertEqual(dm_actions.components_for([make_event("task", "PROJ", "TOM", "x", "ANIM", ["LEA"])], "LEA"), [])

    def test_too_long_task_key_gets_no_buttons(self):
        self.assertEqual(dm_actions.components_for([_task_event(key="X" * 90)], "LEA"), [])

    def test_calendar_proposal_finds_its_item(self):
        items = [{"id": "cal_old", "title": "Review", "owner": "LEA", "created_by": "TOM", "start": "2026-11-02",
                  "end": "2026-11-02", "status": "accepted", "created_at": "1"},
                 {"id": "cal_new", "title": "Review", "owner": "LEA", "created_by": "TOM", "start": "2026-11-02",
                  "end": "2026-11-02", "status": "proposed", "created_at": "2"}]
        event = make_event("calendar", "PROJ", "TOM", "2026-11-02", "proposal", ["LEA"], text="Review")
        with mock.patch("features.calendar.calendar_store.load", return_value={"items": items}), \
             mock.patch("features.accounts.aliases.load_aliases", return_value={}):
            rows = dm_actions.components_for([event], "LEA")
            self.assertEqual(dm_actions.parse_id(rows[0]["components"][0]["custom_id"])["a"], "cal_new")
            self.assertEqual([o["value"] for o in rows[1]["components"][0]["options"]], ["1", "2", "7", "14"])
            answer = make_event("calendar", "PROJ", "LEA", "2026-11-02", "accept", ["TOM"], text="Review")
            self.assertEqual(dm_actions.components_for([answer], "TOM"), [])


class HandleTests(unittest.TestCase):
    def setUp(self):
        self.prod = _production()
        self.saved: list[dict] = []
        patches = [
            mock.patch.object(store, "user_for_discord", side_effect=lambda d: {"111": "LEA"}.get(d)),
            mock.patch("features.production.production_store.load_production", side_effect=lambda p: copy.deepcopy(self.prod)),
            mock.patch("features.production.production_store.save_production",
                       side_effect=lambda p, d: self.saved.append(d) or True),
            mock.patch("features.roles.project_roles.role_of", return_value="artist"),
            mock.patch("utils.user_utils.list_users", return_value=["LEA", "TOM", "MAX"]),
            mock.patch("features.notify.hooks.on_production"),
        ]
        self.mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)

    def _id(self, op, a="s_1", b="ANIM", project="PROJ"):
        return dm_actions.make_id(op, project, a, b)

    def test_valider_and_refuser_write_existing_statuses(self):
        text, done = dm_actions.handle("PROJ", "111", self._id("ok"))
        self.assertTrue(done)
        self.assertEqual(self.saved[-1]["shots"][0]["task_details"]["ANIM"]["status"], "APPROVED")
        self.assertIn("Valide par LEA", text)
        dm_actions.handle("PROJ", "111", self._id("no"))
        self.assertEqual(self.saved[-1]["shots"][0]["task_details"]["ANIM"]["status"], "RTK")
        self.mocks[-1].assert_called()            # notify hooks, as a save in the app

    def test_donner_a_changes_the_assignee(self):
        text, done = dm_actions.handle("PROJ", "111", self._id("give"), ["max"])
        self.assertTrue(done)
        self.assertEqual(self.saved[-1]["shots"][0]["task_details"]["ANIM"]["assignee"], "MAX")
        _, done = dm_actions.handle("PROJ", "111", self._id("give"), ["NOBODY"])
        self.assertFalse(done)

    def test_refused_cases_write_nothing(self):
        self.assertEqual(dm_actions.handle("PROJ", "999", self._id("ok")), (dm_actions.NOT_LINKED, False))
        self.assertFalse(dm_actions.handle("PROJ", "111", self._id("ok", project="OTHER"))[1])
        self.assertFalse(dm_actions.handle("PROJ", "111", self._id("ok", b="LIGHT"))[1])
        self.assertFalse(dm_actions.handle("PROJ", "111", self._id("ok", a="s_gone"))[1])
        self.assertFalse(dm_actions.handle("PROJ", "111", "fx|rm|x|y|z")[1])
        self.assertEqual(self.saved, [])

    def test_calendar_decaler_postpones_by_the_chosen_days(self):
        data = {"items": [{"id": "cal_1", "title": "Review", "owner": "LEA", "created_by": "TOM",
                           "start": "2026-11-02", "end": "2026-11-03", "status": "proposed"}]}
        with mock.patch("features.calendar.calendar_store.load", return_value=data), \
             mock.patch("features.calendar.calendar_store.save") as save, \
             mock.patch("features.accounts.aliases.load_aliases", return_value={}), \
             mock.patch("features.activity.chat_manager._record_mentions") as ping:
            text, done = dm_actions.handle("PROJ", "111", dm_actions.make_id("post", "PROJ", "cal_1"), ["7"])
            self.assertTrue(done)
            item = data["items"][0]
            self.assertEqual((item["start"], item["end"], item["status"]), ("2026-11-09", "2026-11-10", "accepted"))
            save.assert_called_once()
            self.assertEqual(ping.call_args.kwargs["notify_detail"], "postpone")     # the author hears back
            _, done = dm_actions.handle("PROJ", "111", dm_actions.make_id("post", "PROJ", "cal_1"), ["3"])
            self.assertFalse(done)
            data["items"][0]["status"] = "proposed"
            dm_actions.handle("PROJ", "111", dm_actions.make_id("dec", "PROJ", "cal_1"))
            self.assertEqual(data["items"][0]["status"], "declined")

    def test_only_the_owner_answers_a_proposal(self):
        data = {"items": [{"id": "cal_1", "title": "R", "owner": "TOM", "created_by": "MAX",
                           "start": "2026-11-02", "end": "2026-11-02", "status": "proposed"}]}
        with mock.patch("features.calendar.calendar_store.load", return_value=data), \
             mock.patch("features.calendar.calendar_store.save") as save, \
             mock.patch("features.accounts.aliases.load_aliases", return_value={}):
            text, done = dm_actions.handle("PROJ", "111", dm_actions.make_id("acc", "PROJ", "cal_1"))
        self.assertFalse(done)
        self.assertIn("FLUX a refuse", text)
        save.assert_not_called()


class RetakeEventTests(unittest.TestCase):
    def test_retake_comment_is_an_event_with_its_ref(self):
        before = _production()
        after = copy.deepcopy(before)
        after["shots"][0]["task_details"]["ANIM"]["comments"] = [{"id": "c_1", "kind": "retake", "text": "x"}]
        events = production_changes(before, after, project="PROJ", author="TOM")
        self.assertEqual([(e["type"], e["recipients"], e["ref"]) for e in events],
                         [("retake", ["LEA"], {"id": "s_1", "task": "ANIM"})])
        after["shots"][0]["task_details"]["ANIM"]["comments"].append({"id": "c_2", "text": "note"})
        self.assertEqual(production_changes(after, after, project="PROJ", author="TOM"), [])

    def test_parent_task_retake_reaches_the_subtask_artists(self):
        before = {"sequences": [], "assets": [{"id": "a_1", "class": "char", "name": "hero", "task_details": {
            "RIG": {}, "RIG|FACE": {"assignee": "MAX"}}}], "shots": []}
        after = copy.deepcopy(before)
        after["assets"][0]["task_details"]["RIG"]["comments"] = [{"id": "c_1", "kind": "retake"}]
        events = production_changes(before, after, project="PROJ", author="TOM")
        self.assertEqual([(e["type"], e["recipients"]) for e in events], [("retake", ["MAX"])])


class OptOutAndSendTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        outbox.QUEUE_OVERRIDE = Path(self._tmp.name) / "notify_queue.jsonl"
        self.addCleanup(setattr, outbox, "QUEUE_OVERRIDE", None)
        self.cfg = {**store.PROJECT_DEFAULTS, "discord_bot": {"app_id": "9"}}
        self.users = {"LEA": {"channel": "discord", "discord_id": "111", "discord_linked_at": "x", "muted": ["publish"]}}
        patches = [
            mock.patch.dict(os.environ, {"FLUX_NOTIFY": "1"}),
            mock.patch.object(store, "read_project", side_effect=lambda p: dict(self.cfg)),
            mock.patch.object(store, "read_user", side_effect=lambda n: dict(self.users.get(n, store.USER_DEFAULTS))),
            mock.patch.object(dispatch, "load_aliases", return_value={}),
            mock.patch.object(dispatch, "kick"),
            mock.patch("utils.user_utils.list_users", return_value=["LEA", "TOM"]),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_muted_type_is_not_queued(self):
        publish = make_event("publish", "PROJ", "TOM", "SQ010/SH010", "ANIM", ["LEA"])
        self.assertEqual(dispatch.enqueue(publish, now=T0, start_worker=False), 0)
        self.assertEqual(dispatch.enqueue(_task_event(), now=T0, start_worker=False), 1)

    def test_host_sends_the_buttons_with_the_dm(self):
        dispatch.enqueue(_task_event(), now=T0, start_worker=False)
        with mock.patch.object(discord_bot, "hosted_token", return_value="TOK"), \
             mock.patch.object(discord_bot, "send_dm", return_value=SendResult(True, 200)) as dm:
            self.assertEqual(dispatch.flush(now=T0)["sent"], 1)
        components = dm.call_args.args[3]
        self.assertEqual(components[0]["components"][0]["label"], "Valider")

    def test_shared_queue_keeps_the_buttons_for_the_host(self):
        dispatch.enqueue(_task_event(), now=T0, start_worker=False)
        with mock.patch.object(discord_bot, "hosted_token", return_value=""), \
             mock.patch.object(store, "bot_alive", return_value=True), \
             mock.patch.object(store, "bot_queue_add", return_value=True) as add:
            dispatch.flush(now=T0)
        self.assertEqual(add.call_args.args[2]["components"][0]["components"][1]["label"], "Refuser")


class StoreOptOutTests(unittest.TestCase):
    def test_muted_types_are_cleaned_and_validated(self):
        blob: dict = {"notify": {"channel": "discord", "muted": ["publish", "bogus", "mention"]}}
        with mock.patch.object(store, "read_user_data", side_effect=lambda n: json.loads(json.dumps(blob))), \
             mock.patch.object(store, "write_user_data", side_effect=lambda n, d: blob.update(d) or True):
            self.assertEqual(store.read_user("LEA")["muted"], ["mention", "publish"])
            self.assertEqual(store.write_user("LEA", {"muted": ["calendar"]})["muted"], ["calendar"])
            with self.assertRaises(ValueError):
                store.write_user("LEA", {"muted": ["bogus"]})
        self.assertFalse(store.wants({"muted": ["calendar"]}, "calendar"))
        self.assertTrue(store.wants({}, "calendar"))


class BotRestTests(unittest.TestCase):
    def setUp(self):
        self.relay = FakeRelay()
        self.addCleanup(self.relay.close)
        self.relay.status, self.relay.body = 200, b'{"id": "c1"}'
        p = mock.patch.object(discord_bot, "API", self.relay.url)
        p.start()
        self.addCleanup(p.stop)
        discord_bot._dm_channels.clear()

    def test_dm_payload_carries_the_components(self):
        rows = [{"type": 1, "components": [{"type": 2, "style": 3, "label": "Valider", "custom_id": "fx|ok|k|a|b"}]}]
        self.assertTrue(discord_bot.send_dm("TOK", "111", "hello", rows).ok)
        self.assertEqual(self.relay.requests[1]["json"]["components"], rows)

    def test_result_line_fits_2000_chars(self):
        text = discord_bot._with_result("x" * 3000, "Valide par LEA")
        self.assertLessEqual(len(text), discord_bot.MAX_CHARS)
        self.assertTrue(text.endswith("> Valide par LEA"))


if __name__ == "__main__":
    unittest.main()
