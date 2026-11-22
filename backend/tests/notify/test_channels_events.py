# test_channels_events.py - relays (against a local fake server) and minimal message text.

from __future__ import annotations

import unittest

from features.notify import relay_secrets
from features.notify.channels import discord
from features.notify.events import format_digest, format_text, make_event, production_changes
from tests.notify._relay import FakeRelay, dead_url


class ChannelTests(unittest.TestCase):
    def setUp(self):
        self.relay = FakeRelay()
        self.addCleanup(self.relay.close)

    def test_discord_pings_only_the_recipient(self):
        result = discord.send(self.relay.url + "/hook", "Retake SQ010/SH010 par TOM", ["1234"])
        self.assertTrue(result.ok)
        payload = self.relay.requests[0]["json"]
        self.assertEqual(payload["content"], "<@1234> Retake SQ010/SH010 par TOM")
        self.assertEqual(payload["allowed_mentions"], {"parse": [], "users": ["1234"]})

    def test_discord_bad_id_dropped_and_2000_chars(self):
        payload = discord.build_payload("x" * 5000, ["@everyone", "42"])
        self.assertEqual(payload["allowed_mentions"]["users"], ["42"])
        self.assertLessEqual(len(payload["content"]), discord.MAX_CHARS)

    def test_rate_limit_is_retried_with_retry_after(self):
        self.relay.status, self.relay.headers = 429, {"Retry-After": "7"}
        result = discord.send(self.relay.url, "t", [])
        self.assertFalse(result.ok)
        self.assertFalse(result.permanent)
        self.assertEqual(result.retry_after, 7.0)

    def test_deleted_webhook_is_permanent(self):
        self.relay.status = 404
        self.assertTrue(discord.send(self.relay.url, "t", []).permanent)

    def test_relay_down_is_retried(self):
        result = discord.send(dead_url(), "t", [])
        self.assertEqual((result.ok, result.status, result.permanent), (False, 0, False))


class SecretTests(unittest.TestCase):
    def test_mask_keeps_last_four(self):
        self.assertEqual(relay_secrets.mask("https://discord.com/api/webhooks/1/abcdWXYZ"), "****WXYZ")
        self.assertEqual(relay_secrets.mask(""), "")
        self.assertTrue(relay_secrets.is_masked("****WXYZ"))


class TextTests(unittest.TestCase):
    def test_minimal_text_without_project_by_default(self):
        e = make_event("retake", "PROJ", "tom", "SQ010/SH010", "ANIM", ["LEA"])
        self.assertEqual(format_text(e), "Retake SQ010/SH010 ANIM par TOM")
        self.assertEqual(format_text(e, include_project=True), "[PROJ] Retake SQ010/SH010 ANIM par TOM")

    def test_mention_text_only_when_allowed(self):
        e = make_event("mention", "PROJ", "TOM", "chat", "", ["LEA"], text="@lea tu\npeux checker ?")
        self.assertEqual(format_text(e), "Mention par TOM dans le chat")
        self.assertEqual(format_text(e, include_text=True), "TOM dans le chat : @lea tu peux checker ?")

    def test_mention_without_text_keeps_the_short_form(self):
        e = make_event("mention", "PROJ", "TOM", "chat", "", ["LEA"])
        self.assertEqual(format_text(e, include_text=True), "Mention par TOM dans le chat")

    def test_calendar_title_and_span(self):
        e = make_event("calendar", "PROJ", "TOM", "2026-11-02", "proposal", ["LEA"], text="Review anim")
        self.assertEqual(format_text(e, include_text=True), "TOM te propose un creneau : Review anim (2026-11-02)")
        self.assertEqual(format_text(e), "TOM te propose un creneau (2026-11-02)")

    def test_long_text_is_clipped(self):
        e = make_event("mention", "PROJ", "TOM", "chat", "", ["LEA"], text="x" * 1000)
        self.assertEqual(len(e["text"]), 300)
        self.assertTrue(e["text"].endswith("..."))

    def test_digest_passes_include_text(self):
        events = [make_event("mention", "P", "TOM", "chat", "", ["LEA"], text=f"msg {i}") for i in range(2)]
        self.assertIn("TOM dans le chat : msg 1", format_digest(events, include_text=True))
        self.assertNotIn("msg 1", format_digest(events))

    def test_digest_counts_overflow(self):
        events = [make_event("publish", "P", "TOM", f"SQ/SH{i:03d}", "ANIM") for i in range(20)]
        text = format_digest(events, max_lines=15)
        self.assertTrue(text.startswith("20 notifications FLUX"))
        self.assertIn("et 5 autres", text)
        self.assertNotIn("/DOSSIER_PROJETS", text)

    def test_unknown_type_refused(self):
        with self.assertRaises(ValueError):
            make_event("spam", "P", "A")


def _prod(assignee="", retakes=()):
    return {"sequences": [{"id": "seq1", "name": "sq010"}],
            "shots": [{"id": "s1", "seq_id": "seq1", "name": "sh010",
                       "task_details": {"ANIM": {"assignee": assignee, "retakes": list(retakes)}}}],
            "assets": []}


class ProductionDiffTests(unittest.TestCase):
    def test_new_assignee_gives_a_task_event(self):
        events = production_changes(_prod("LEA"), _prod("LEA, tom"), project="P", author="ADAM")
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0]["type"], events[0]["entity"], events[0]["recipients"]),
                         ("task", "SQ010/SH010", ["TOM"]))

    def test_new_retake_goes_to_assignees(self):
        events = production_changes(_prod("LEA", [{"id": "r1"}]), _prod("LEA", [{"id": "r1"}, {"id": "r2"}]),
                                    project="P", author="ADAM")
        self.assertEqual([(e["type"], e["recipients"]) for e in events], [("retake", ["LEA"])])

    def test_unchanged_document_gives_nothing(self):
        self.assertEqual(production_changes(_prod("LEA", [{"id": "r1"}]), _prod("LEA", [{"id": "r1"}]),
                                            project="P", author="ADAM"), [])


if __name__ == "__main__":
    unittest.main()
