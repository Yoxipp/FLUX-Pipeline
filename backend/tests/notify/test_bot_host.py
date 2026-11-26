# test_bot_host.py - one bot host per PC, headless mode, Startup shortcut (ADR 0076).
# No real Discord, no real Startup folder, no process started.

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from features.notify import bot_host, bot_secret, discord_bot

BACKEND = Path(__file__).resolve().parents[2]


class _Local(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for name, value in (("PATH_OVERRIDE", self.tmp / "tokens.json"),):
            p = mock.patch.object(bot_secret, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(bot_host, "STARTUP_OVERRIDE", self.tmp / "Startup")
        p.start()
        self.addCleanup(p.stop)

    def _write_lock(self, pid: int, mode: str = "app", at: float | None = None):
        data = {"pid": pid, "mode": mode, "at": time.time() if at is None else at}
        bot_host.lock_path().write_text(json.dumps(data), encoding="utf-8")


class LockTests(_Local):
    def test_claim_then_release(self):
        self.assertTrue(bot_host.claim())
        self.assertEqual(bot_host.holder()["pid"], os.getpid())
        self.assertTrue(bot_host.claim())                 # kept
        bot_host.release()
        self.assertIsNone(bot_host.holder())

    def test_live_other_process_wins(self):
        self._write_lock(os.getppid())                     # the test runner's parent is alive
        self.assertFalse(bot_host.claim())
        bot_host.release()                                 # not ours: left alone
        self.assertEqual(bot_host.holder()["pid"], os.getppid())

    def test_dead_process_lock_is_taken_over(self):
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        self._write_lock(dead.pid)
        self.assertIsNone(bot_host.holder())
        self.assertTrue(bot_host.claim())

    def test_bad_lock_file_is_free(self):
        bot_host.lock_path().write_text("{oops", encoding="utf-8")
        self.assertIsNone(bot_host.holder())

    def test_app_does_not_start_a_bot_held_elsewhere(self):
        self._write_lock(os.getppid(), "headless")
        with mock.patch.object(bot_secret, "load_token", return_value="tok"), \
                mock.patch.object(discord_bot.store, "read_project", return_value={"discord_bot": {"app_id": "1"}}), \
                mock.patch.object(discord_bot.BotRunner, "start") as start, \
                mock.patch.object(discord_bot, "enabled", return_value=True):
            self.assertFalse(discord_bot.start("P"))
        start.assert_not_called()
        self.assertNotIn("P", discord_bot._runners)

    def test_stop_headless_only_kills_the_headless_holder(self):
        self._write_lock(os.getppid(), "app")
        with mock.patch.object(bot_host.os, "kill") as kill:
            self.assertFalse(bot_host.stop_headless())
            self._write_lock(os.getppid(), "headless")
            self.assertTrue(bot_host.stop_headless())
        kill.assert_called_once_with(os.getppid(), 15)
        self.assertFalse(bot_host.lock_path().exists())


    @unittest.skipUnless(os.name == "nt", "Windows only")
    def test_reused_pid_is_never_terminated(self):
        # A stale headless lock whose PID now belongs to a younger process (e.g. a local render).
        self._write_lock(os.getppid(), "headless", at=bot_host.pid_started(os.getppid()) - 60)
        self.assertIsNone(bot_host.holder())
        with mock.patch.object(bot_host.os, "kill") as kill:
            self.assertFalse(bot_host.stop_headless())
        kill.assert_not_called()


class StartupTests(_Local):
    def test_dev_command_runs_main_with_the_flag(self):
        exe, args, cwd = bot_host.command()
        self.assertEqual(args, [str(BACKEND / "main.py"), bot_host.FLAG])
        self.assertEqual(Path(cwd), BACKEND)
        self.assertTrue(Path(exe).is_file())

    @unittest.skipUnless(os.name == "nt", "Windows only")
    def test_shortcut_paths_go_through_env_not_the_script(self):
        with mock.patch.object(bot_host, "_powershell") as ps:
            path = bot_host.install_startup()
        script, env = ps.call_args.args
        self.assertEqual(path, self.tmp / "Startup" / bot_host.SHORTCUT_NAME)
        self.assertEqual(env["FLUX_LNK"], str(path))
        self.assertIn(bot_host.FLAG, env["FLUX_ARGS"])
        self.assertNotIn(str(self.tmp), script)

    def test_enabled_follows_the_shortcut(self):
        self.assertFalse(bot_host.background_enabled())
        bot_host.shortcut_path().parent.mkdir(parents=True)
        bot_host.shortcut_path().write_bytes(b"x")
        self.assertTrue(bot_host.background_enabled())
        bot_host.remove_startup()
        bot_host.remove_startup()                          # twice: no error
        self.assertFalse(bot_host.background_enabled())

    def test_spawn_leaves_the_process_tree(self):
        with mock.patch.object(bot_host.subprocess, "Popen") as popen:
            bot_host.spawn()
        cmd = popen.call_args.args[0]
        self.assertEqual(cmd[:4], ["cmd", "/c", "start", ""])
        self.assertIn(bot_host.FLAG, cmd)


class HeadlessTests(_Local):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(discord_bot, "enabled", return_value=True)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(setattr, bot_host, "MODE", "app")

    def test_waits_while_flux_hosts(self):
        self._write_lock(os.getppid(), "app")
        with mock.patch.object(bot_secret, "hosted_projects", return_value=["P"]), \
                mock.patch.object(discord_bot, "refresh") as refresh:
            self.assertEqual(bot_host.run_headless(stop_after=0.15), 0)
        refresh.assert_not_called()

    def test_hosts_when_free_and_marks_the_lock_headless(self):
        with mock.patch.object(bot_secret, "hosted_projects", return_value=["P"]), \
                mock.patch.object(discord_bot, "refresh") as refresh:
            bot_host.run_headless(stop_after=0.15)
        self.assertGreater(refresh.call_count, 0)
        self.assertIsNone(bot_host.holder())               # released by stop_all at the end

    def test_exits_without_token(self):
        with mock.patch.object(bot_secret, "hosted_projects", return_value=[]), \
                mock.patch.object(discord_bot, "refresh") as refresh:
            self.assertEqual(bot_host.run_headless(), 0)
        refresh.assert_not_called()

    def test_refresh_restarts_a_bot_whose_token_changed(self):
        old = discord_bot.BotRunner("P", "old")
        discord_bot._runners["P"] = old
        self.addCleanup(discord_bot._runners.clear)
        with mock.patch.object(bot_secret, "load_token", return_value="new"), \
                mock.patch.object(old._thread, "is_alive", return_value=True), \
                mock.patch.object(discord_bot, "start_all", return_value=["P"]) as start_all:
            discord_bot.refresh()
        self.assertTrue(old._stop.is_set())
        self.assertNotIn("P", discord_bot._runners)
        start_all.assert_called_once()

    def test_main_flag_exits_without_starting_the_server(self):
        env = {**os.environ, "FLUX_NOTIFY": "0", "FLUX_PORT": "1"}
        out = subprocess.run([sys.executable, str(BACKEND / "main.py"), bot_host.FLAG], cwd=str(BACKEND),
                             env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        self.assertNotIn("Uvicorn running", out.stderr + out.stdout)
