# P6a refactor (2026-10-23): the Marvelous mailbox protocol works on any folder
# (bridge.file_mailbox_call, extension bridges); default = flux_marvelous_bridge.

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from dcc.marvelous import client


def _beat(box: Path) -> None:
    tmp = box / "alive.json.tmp"
    tmp.write_text(json.dumps({"time": time.time(), "pid": os.getpid()}), encoding="utf-8")
    os.replace(tmp, box / "alive.json")      # atomic, like the real bridge must be


def _serve_once(box: Path, answer: dict) -> threading.Thread:
    """A fake bridge: beats, answers the first request of *box*."""
    _beat(box)

    def run():
        end = time.monotonic() + 5
        while time.monotonic() < end:
            _beat(box)
            reqs = list(box.glob("*.req"))
            if reqs:
                rid = reqs[0].name[:-4]
                payload = json.loads(reqs[0].read_text(encoding="utf-8"))
                reqs[0].unlink()
                (box / f"{rid}.resp").write_text(json.dumps({**answer, "echo": payload}), encoding="utf-8")
                return
            time.sleep(0.02)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


class MailboxDir(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_mailbox_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_name_and_root(self) -> None:
        with mock.patch.dict(os.environ, {"FLUX_MD_MAILBOX_ROOT": str(self.tmp)}):
            self.assertEqual(client.mailbox_dir(), self.tmp / "flux_marvelous_bridge")
            self.assertEqual(client.mailbox_dir("flux_max_bridge"), self.tmp / "flux_max_bridge")

    def test_call_on_another_box(self) -> None:
        box = self.tmp / "other"
        box.mkdir()
        t = _serve_once(box, {"status": "ok"})
        resp = client.call({"action": "ping"}, timeout=5, box=box)
        t.join()
        self.assertEqual((resp["ok"], resp["echo"]), (True, {"action": "ping"}))

    def test_no_heartbeat_is_not_running(self) -> None:
        resp = client.call({"action": "ping"}, timeout=1, box=self.tmp)
        self.assertFalse(resp["ok"])
        self.assertIn(client.NOT_RUNNING, resp["error"])


if __name__ == "__main__":
    unittest.main()
