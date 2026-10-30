# test_bot_failover.py - ADR 0082: several PCs hold the token of a project's bot; one hosts
# it (project lock on the share, core.host_lock), the others wait and take over when it leaves.
# No real Discord: the Gateway session is replaced by a stub that stays "online".

from __future__ import annotations

import asyncio
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from core.host_lock import HostLock
from features.notify import discord_bot, store

NOW = 1_800_000_000.0


async def _nosleep(_s: float) -> None:
    return None


class _Runner(discord_bot.BotRunner):
    """A BotRunner whose Gateway is a stub: online until the task is cancelled."""
    beat_s = 0.05
    sessions = 0

    async def _session(self) -> None:
        type(self).sessions += 1
        self.online = True
        try:
            await asyncio.Event().wait()
        finally:
            self.online = False


def _wait_for(cond, timeout: float = 5.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class Failover(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.cfg = {"discord_bot": {"app_id": "9", "name": "FLUXBOT", "host": "PC_A"}}
        for p in (mock.patch.object(store, "_setup_file", side_effect=lambda p, n: self.tmp / n),
                  mock.patch.object(store, "read_project", side_effect=lambda p: self.cfg)):
            p.start()
            self.addCleanup(p.stop)
        self.path = self.tmp / "discord_bot_host.lock"

    def _runner(self, host: str) -> _Runner:
        lock = HostLock(self.path, host=host, sleep=_nosleep, settle=(0.0, 0.0), confirm_s=0.0)
        r = _Runner("P", "TOK", lock=lock)
        self.addCleanup(r.stop)
        return r

    def test_one_host_then_the_other_takes_over(self):
        a = self._runner("PC_A")
        a.start()
        self.assertTrue(_wait_for(lambda: a.online))
        b = self._runner("PC_B")
        b.start()
        self.assertTrue(_wait_for(lambda: "PC_B" in store.bot_candidates("P", time.time())))
        time.sleep(0.3)
        self.assertFalse(b.online)                       # never two Gateways
        self.assertFalse(b.lock.holder)
        a.stop()
        a._thread.join(2.0)
        self.assertFalse(a.online)
        self.assertTrue(_wait_for(lambda: b.online))     # a clean stop releases at once
        self.assertTrue(b.lock.holder)

    def test_no_way_back_to_the_first_pc(self):
        a = self._runner("PC_A")
        a.start()
        self.assertTrue(_wait_for(lambda: a.online))
        a.stop()
        a._thread.join(2.0)
        b = self._runner("PC_B")
        b.start()
        self.assertTrue(_wait_for(lambda: b.online))
        a2 = self._runner("PC_A")
        a2.start()
        time.sleep(0.4)
        self.assertTrue(b.online)
        self.assertFalse(a2.online)

    def test_a_lost_lock_closes_the_gateway(self):
        a = self._runner("PC_A")
        a.start()
        self.assertTrue(_wait_for(lambda: a.online))
        # Another backend writes its own valid record (as after a share cut on A).
        self.path.write_text('{"host": "PC_Z", "nonce": "z", "expires": %f, "beat": 1}' % (time.time() + 60),
                             encoding="utf-8")
        self.assertTrue(_wait_for(lambda: not a.online))
        self.assertFalse(a.lock.holder)

    def test_waiting_pc_stops_when_the_bot_is_removed(self):
        a = self._runner("PC_A")
        a.start()
        self.assertTrue(_wait_for(lambda: a.online))
        b = self._runner("PC_B")
        b.start()
        self.assertTrue(_wait_for(lambda: "PC_B" in store.bot_candidates("P", time.time())))
        self.cfg = {"discord_bot": {}}
        with mock.patch.object(discord_bot, "CANDIDATE_EVERY_S", 0.0):
            self.assertTrue(_wait_for(lambda: not b._thread.is_alive()))


class Status(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        p = mock.patch.object(store, "_setup_file", side_effect=lambda p, n: self.tmp / n)
        p.start()
        self.addCleanup(p.stop)

    def test_candidates_expire_and_can_be_dropped(self):
        store.write_candidate("P", "PC_A", NOW)
        store.write_candidate("P", "PC_B", NOW + 10)
        self.assertEqual(store.bot_candidates("P", NOW + 20), ["PC_A", "PC_B"])
        self.assertEqual(store.bot_candidates("P", NOW + store.CANDIDATE_S + 5), ["PC_B"])
        store.drop_candidate("P", "PC_B")
        self.assertEqual(store.bot_candidates("P", NOW + 20), ["PC_A"])

    def test_host_now_from_the_heartbeat(self):
        self.assertEqual(store.bot_host_now("P", NOW), "")
        store.write_alive("P", "PC_A (adam)", NOW)
        self.assertEqual(store.bot_host_now("P", NOW + 1), "PC_A (adam)")
        self.assertTrue(store.bot_alive("P", NOW + 1))
        self.assertEqual(store.bot_host_now("P", NOW + store.BOT_ALIVE_S + 1), "")

    def test_hosted_token_only_while_online(self):
        r = discord_bot.BotRunner("P", "TOK")
        with mock.patch.dict(discord_bot._runners, {"P": r}):
            self.assertEqual(discord_bot.hosted_token("P"), "")     # waiting PC: the DM goes to the queue
            r.online = True
            self.assertEqual(discord_bot.hosted_token("P"), "TOK")


class Routes(unittest.TestCase):
    """PUT / DELETE /notify/project/{p}/bot with a bot already registered by another PC."""

    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from features.notify import bot_secret
        from routers import notify as notify_router

        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.cfg = {"discord_bot": {"app_id": "9", "name": "FLUXBOT", "host": "PC_A (adam)"}}
        self.tokens: dict = {}
        self.set_bot = mock.Mock(side_effect=lambda p, info, by: self.cfg)
        patches = [
            mock.patch.object(store, "_setup_file", side_effect=lambda p, n: self.tmp / n),
            mock.patch.object(store, "read_project", side_effect=lambda p: self.cfg),
            mock.patch.object(store, "set_bot", self.set_bot),
            mock.patch.object(notify_router, "_ensure_project"),
            mock.patch.object(notify_router, "_require_role"),
            mock.patch.object(notify_router, "_user", return_value="LEA"),
            mock.patch.object(bot_secret, "save_token", side_effect=lambda p, t: self.tokens.__setitem__(p, t)),
            mock.patch.object(bot_secret, "delete_token", side_effect=lambda p: self.tokens.pop(p, None)),
            mock.patch.object(bot_secret, "hosted_projects", side_effect=lambda: sorted(self.tokens)),
            mock.patch.object(discord_bot, "start", return_value=True),
            mock.patch.object(discord_bot, "stop"),
            mock.patch.object(discord_bot, "host_name", return_value="PC_B (lea)"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        app = FastAPI()
        app.include_router(notify_router.router, prefix="/notify")
        self.client = TestClient(app)

    def test_token_of_another_bot_is_refused(self):
        with mock.patch.object(discord_bot, "check_token", return_value={"app_id": "7", "name": "OTHER"}):
            r = self.client.put("/notify/project/P/bot", json={"token": "x"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.tokens, {})

    def test_second_pc_becomes_a_candidate(self):
        with mock.patch.object(discord_bot, "check_token", return_value={"app_id": "9", "name": "FLUXBOT"}):
            r = self.client.put("/notify/project/P/bot", json={"token": "x"})
        self.assertEqual(r.status_code, 200, r.text)
        self.set_bot.assert_not_called()                 # the registered bot is kept as is
        self.assertEqual(self.tokens, {"P": "x"})
        bot = r.json()["bot"]
        self.assertTrue(bot["hosted_here"])
        self.assertEqual(bot["this_pc"], "PC_B (lea)")
        discord_bot.start.assert_called_once_with("P")

    def test_remove_this_pc_only_keeps_the_bot(self):
        self.tokens["P"] = "x"
        store.write_candidate("P", "PC_B (lea)", time.time())
        r = self.client.delete("/notify/project/P/bot", params={"this_pc_only": True})
        self.assertEqual(r.status_code, 200, r.text)
        self.set_bot.assert_not_called()
        self.assertEqual(self.tokens, {})
        self.assertEqual(store.bot_candidates("P", time.time()), [])
        self.assertTrue(r.json()["bot"]["configured"])


if __name__ == "__main__":
    unittest.main()
