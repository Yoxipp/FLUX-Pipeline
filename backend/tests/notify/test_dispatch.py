# test_dispatch.py - queue, grouping, retries, 24 h expiry, ntfy quota, secrets out of logs,
# publish recipients (ADR 0045 filter), settings store and router roles. No real network:
# the relay is tests/notify/_relay.FakeRelay; accounts and settings are patched.

from __future__ import annotations

import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from features.notify import dispatch, hooks, outbox, store
from features.notify.channels import ntfy
from features.notify.events import make_event
from tests.notify._relay import FakeRelay, dead_url

T0 = 1_800_000_000.0


class _Queue(unittest.TestCase):
    """Temp queue, FLUX_NOTIFY on, settings and accounts in memory."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        outbox.QUEUE_OVERRIDE = Path(self._tmp.name) / "notify_queue.jsonl"
        self.addCleanup(setattr, outbox, "QUEUE_OVERRIDE", None)
        dispatch._discord_cooldown.clear()
        self.relay = FakeRelay()
        self.addCleanup(self.relay.close)
        self.project_cfg = {**store.PROJECT_DEFAULTS, "discord_webhook": self.relay.url + "/api/webhooks/1/SECRETabcd",
                            "ntfy_server": self.relay.url}
        self.users = {"LEA": {"channel": "discord", "discord_id": "111", "ntfy_topic": ""},
                      "TOM": {"channel": "ntfy", "discord_id": "", "ntfy_topic": "flux_topicTHEO"},
                      "NOCHAN": dict(store.USER_DEFAULTS)}
        patches = [
            mock.patch.dict(os.environ, {"FLUX_NOTIFY": "1"}),
            mock.patch.object(store, "read_project", side_effect=lambda p: dict(self.project_cfg)),
            mock.patch.object(store, "read_user", side_effect=lambda n: dict(self.users.get(n, store.USER_DEFAULTS))),
            mock.patch.object(dispatch, "load_aliases", return_value={"OLDLEA": "LEA"}),
            mock.patch.object(dispatch, "kick"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def enqueue(self, type_, recipients, author="ADAM", at=T0):
        return dispatch.enqueue(make_event(type_, "PROJ", author, "SQ010/SH010", "ANIM", recipients, at=at),
                                now=at, start_worker=False)


class EnqueueTests(_Queue):
    def test_author_never_notified_and_alias_resolved(self):
        self.assertEqual(self.enqueue("mention", ["ADAM", "oldlea", "LEA"]), 1)
        self.assertEqual([i["recipient"] for i in outbox.load()], ["LEA"])

    def test_mention_immediate_publish_grouped(self):
        self.enqueue("mention", ["LEA"])
        self.enqueue("publish", ["TOM"])
        due = {i["event"]["type"]: i["due"] for i in outbox.load()}
        self.assertEqual(due["mention"], T0)
        self.assertEqual(due["publish"], T0 + 5 * 60)

    def test_disabled_switch_queues_nothing(self):
        with mock.patch.dict(os.environ, {"FLUX_NOTIFY": "0"}):
            self.assertEqual(self.enqueue("mention", ["LEA"]), 0)
        self.assertEqual(outbox.load(), [])

    def test_queue_error_never_raises(self):
        with mock.patch.object(outbox, "add", side_effect=OSError("disk full")):
            self.assertEqual(self.enqueue("mention", ["LEA"]), 0)


class FlushTests(_Queue):
    def test_one_message_per_person_and_queue_emptied(self):
        self.enqueue("publish", ["TOM"])
        self.enqueue("publish", ["TOM"], author="LEA")
        stats = dispatch.flush(now=T0 + 301)
        self.assertEqual(stats["sent"], 2)
        self.assertEqual(len(self.relay.requests), 1)
        self.assertTrue(self.relay.requests[0]["json"]["message"].startswith("2 notifications FLUX"))
        self.assertEqual(outbox.load(), [])

    def test_digest_waits_its_delay(self):
        self.enqueue("publish", ["TOM"])
        self.assertEqual(dispatch.flush(now=T0 + 10)["waiting"], 1)
        self.assertEqual(self.relay.requests, [])

    def test_relay_down_keeps_item_then_retries(self):
        self.project_cfg["discord_webhook"] = dead_url() + "/hook"
        self.enqueue("mention", ["LEA"])
        self.assertEqual(dispatch.flush(now=T0)["retry"], 1)
        item = outbox.load()[0]
        self.assertEqual(item["attempts"], 1)
        self.assertGreater(item["next_try"], T0)
        self.project_cfg["discord_webhook"] = self.relay.url + "/hook"
        self.assertEqual(dispatch.flush(now=item["next_try"])["sent"], 1)
        self.assertEqual(outbox.load(), [])

    def test_expired_after_24h(self):
        self.project_cfg["discord_webhook"] = dead_url() + "/hook"
        self.enqueue("mention", ["LEA"])
        dispatch.flush(now=T0)
        self.assertEqual(dispatch.flush(now=T0 + outbox.MAX_AGE_S + 1)["expired"], 1)
        self.assertEqual(outbox.load(), [])

    def test_no_channel_dropped_silently(self):
        self.enqueue("mention", ["NOCHAN"])
        self.assertEqual(dispatch.flush(now=T0)["no_channel"], 1)
        self.assertEqual(outbox.load(), [])

    def test_permanent_error_dropped(self):
        self.relay.status = 404
        self.enqueue("mention", ["LEA"])
        self.assertEqual(dispatch.flush(now=T0)["dropped"], 1)

    def test_secrets_never_logged(self):
        self.relay.status = 500
        self.enqueue("mention", ["LEA", "TOM"])
        with self.assertLogs("flux.features.notify", level=logging.DEBUG) as logs:
            dispatch.flush(now=T0)
        text = "\n".join(logs.output)
        self.assertNotIn("SECRETabcd", text)
        self.assertNotIn("flux_topicTHEO", text)
        self.assertNotIn(self.relay.url, text)


class QuotaTests(_Queue):
    def test_limit_holds_until_tomorrow(self):
        with mock.patch.object(dispatch, "ntfy_count", return_value=ntfy.DAILY_LIMIT):
            self.enqueue("mention", ["TOM"])
            self.assertEqual(dispatch.flush(now=T0)["held"], 1)
        self.assertEqual(self.relay.requests, [])
        self.assertGreater(outbox.load()[0]["next_try"], T0 + 60)

    def test_near_limit_degrades_immediate_to_digest(self):
        with mock.patch.object(dispatch, "ntfy_count", return_value=dispatch.WARN_AT):
            self.enqueue("mention", ["TOM"])
            self.assertEqual(dispatch.flush(now=T0)["held"], 1)
            self.assertEqual(dispatch.flush(now=T0 + 301)["sent"], 1)

    def test_counter_counts_sends(self):
        self.enqueue("mention", ["TOM"])
        dispatch.flush(now=T0)
        self.assertEqual(dispatch.ntfy_count(), 1)


class PublishRecipientsTests(unittest.TestCase):
    def test_followers_with_a_channel_only(self):
        data = {
            "LEA": {"notify": {"channel": "discord"}, "production": {"favorites": ["PROJ|SQ010/SH010|*"]}},
            "TOM": {"notify": {"channel": "ntfy"}, "production": {"favorites": []}},
            "MAX": {"notify": {"channel": "none"}, "production": {"favorites": ["PROJ|SQ010/SH010|*"]}},
        }
        with mock.patch("utils.user_utils.list_users", return_value=list(data)), \
             mock.patch("utils.user_utils.read_user_data", side_effect=lambda n: data[n]), \
             mock.patch("features.production.production_store.load_production", return_value={}), \
             mock.patch("features.production.reconcile.parse_publish_event",
                        return_value={"is_shot": True, "SEQ": "SQ010", "SHOT": "SH010", "TASK": "ANIM"}), \
             mock.patch("features.activity.notifications.reason_for",
                        side_effect=lambda ev, **kw: "followed_shot" if kw["favorites"] else None):
            event, names = hooks.publish_recipients("ADAM", "SQ010_SH010_ANIM_v001.usd", "PROJ")
        self.assertEqual(names, ["LEA"])
        self.assertEqual((event["entity"], event["detail"]), ("SQ010/SH010", "ANIM"))


class MentionHookTests(unittest.TestCase):
    def test_chat_mentions_reach_notify_without_the_text(self):
        from features.activity import chat_manager
        with mock.patch.object(chat_manager, "get_user_list", return_value=["LEA", "ADAM"]), \
             mock.patch.object(chat_manager, "load_aliases", return_value={}), \
             mock.patch.object(chat_manager, "append_events", return_value=True), \
             mock.patch.object(hooks, "on_mentions") as on_mentions:
            chat_manager._record_mentions("ADAM", "m1", "@lea secret plan @adam", "2026-10-30", "10:00", "PROJ")
        on_mentions.assert_called_once_with("ADAM", ["LEA"], "PROJ", "mention", "", "")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "collab.json"
        p = mock.patch.object(store, "collab_path", return_value=self.path)
        p.start()
        self.addCleanup(p.stop)

    def test_masked_webhook_kept_and_hidden(self):
        store.write_project("P", {"discord_webhook": "https://discord.com/api/webhooks/1/abcdWXYZ"}, "ADAM")
        cfg = store.write_project("P", {"discord_webhook": "****WXYZ", "digest_minutes": 999}, "ADAM")
        self.assertEqual(cfg["discord_webhook"], "https://discord.com/api/webhooks/1/abcdWXYZ")
        self.assertEqual(cfg["digest_minutes"], store.DIGEST_MAX)
        self.assertEqual(store.public_project(cfg)["discord_webhook"], "****WXYZ")

    def test_http_webhook_refused(self):
        with self.assertRaises(ValueError):
            store.write_project("P", {"discord_webhook": "http://evil"}, "ADAM")

    def test_user_topic_created_and_regenerated(self):
        blob: dict = {}
        with mock.patch.object(store, "read_user_data", side_effect=lambda n: dict(blob)), \
             mock.patch.object(store, "write_user_data", side_effect=lambda n, d: blob.update(d) or True):
            first = store.write_user("LEA", {"channel": "ntfy"})["ntfy_topic"]
            again = store.write_user("LEA", {"regenerate_topic": True})["ntfy_topic"]
            with self.assertRaises(ValueError):
                store.write_user("LEA", {"discord_id": "abc"})
        self.assertTrue(first.startswith("flux_"))
        self.assertNotEqual(first, again)


class RouterTests(unittest.TestCase):
    def setUp(self):
        from routers import notify as notify_router
        app = FastAPI()
        app.include_router(notify_router.router, prefix="/notify")
        self.client = TestClient(app)
        patches = [
            mock.patch("utils.project_utils.project_exists", return_value=True),
            mock.patch("core.config.get_current_user", return_value="LEA"),
            mock.patch.object(store, "read_project", return_value={**store.PROJECT_DEFAULTS,
                                                                   "discord_webhook": "https://d/x/SECRETabcd"}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_webhook_edit_needs_a_lead(self):
        from features.roles import project_roles
        with mock.patch.object(project_roles, "require", side_effect=project_roles.RoleError("lead requis")), \
             mock.patch.object(store, "write_project") as write:
            res = self.client.put("/notify/project/P", json={"discord_webhook": "https://x"})
        self.assertEqual(res.status_code, 403)
        write.assert_not_called()

    def test_project_answer_masks_the_webhook(self):
        with mock.patch("utils.user_utils.list_users", return_value=["LEA"]), \
             mock.patch.object(store, "read_user", return_value=dict(store.USER_DEFAULTS)), \
             mock.patch("features.roles.project_roles.can", return_value=False):
            res = self.client.get("/notify/project/P")
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("SECRETabcd", res.text)
        self.assertEqual(res.json()["without_channel"], ["LEA"])


if __name__ == "__main__":
    unittest.main()
