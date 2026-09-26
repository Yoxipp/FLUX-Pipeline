# test_marvelous_blocked.py - a Marvelous stuck in a modal window is busy, not gone (2026-09-26).

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from dcc.marvelous import client


def _bridge_copy():
    """The bridge script loaded from its file under its own name: importing
    dcc.marvelous.marvelous_bridge here would leave a copy without the fake export_api
    of test_designer_marvelous_bridge in the package (it re-imports it)."""
    import importlib.util
    path = Path(client.__file__).with_name("marvelous_bridge.py")
    spec = importlib.util.spec_from_file_location("_flux_md_bridge_copy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Blocked(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"FLUX_MD_MAILBOX_ROOT": self.tmp.name})
        self.env.start()
        client.mailbox_dir().mkdir(parents=True)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def _beat(self, age: float, pid: int):
        (client.mailbox_dir() / "alive.json").write_text(
            json.dumps({"pid": pid, "time": time.time() - age, "version": "MD 2024"}), encoding="utf-8")

    def test_fresh_heartbeat_is_connected(self):
        self._beat(0.5, os.getpid())
        self.assertEqual(client.MarvelousClient().ping()["ok"], True)
        self.assertNotIn("busy", client.MarvelousClient().ping())

    def test_stale_heartbeat_of_a_live_marvelous_is_busy(self):
        self._beat(60, os.getpid())
        ping = client.MarvelousClient().ping()
        self.assertTrue(ping["ok"] and ping["busy"])
        res = client.call({"action": "info"}, timeout=1)
        self.assertIn("occupe", res["error"])
        self.assertEqual(list(client.mailbox_dir().glob("*.req")), [], "no request left behind")

    def test_stale_heartbeat_of_a_closed_marvelous_is_gone(self):
        with mock.patch.object(client, "pid_alive", return_value=False):
            self._beat(60, 999999)
            self.assertFalse(client.MarvelousClient().ping()["ok"])
            self.assertIn("non lance", client.call({"action": "info"}, timeout=1)["error"])

    def test_this_process_is_alive(self):
        self.assertTrue(client.pid_alive(os.getpid()))
        self.assertFalse(client.pid_alive(0))


class RequestOrder(unittest.TestCase):
    def test_oldest_request_first(self):
        marvelous_bridge = _bridge_copy()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(marvelous_bridge, "MAILBOX", tmp):
            for i, name in enumerate(("ffff.req", "0000.req")):
                p = Path(tmp, name)
                p.write_text("{}")
                os.utime(p, (1000 + i, 1000 + i))
            self.assertEqual([os.path.basename(p) for p in marvelous_bridge._pending()], ["ffff.req", "0000.req"])


if __name__ == "__main__":
    unittest.main()
