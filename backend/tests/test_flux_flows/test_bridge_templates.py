# P6c (2026-10-23): the dcc_side templates (tcp_json_server.py, file_mailbox_server.py) run
# as the "soft" (here: a thread of the test) and FLUX talks to them through the extension
# registry, the primitives and the live sessions, as with a real soft.

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import socket
import threading
import unittest
from pathlib import Path
from unittest import mock

from flux_flows.bridges import primitives, session
from flux_flows.bridges.templates import TEMPLATES_DIR
from tests.test_flux_flows._ext_helpers import MAX_YML, ExtFolder


def _free_base(count: int = 4) -> int:
    for base in range(47100, 48000, count):
        try:
            for port in range(base, base + count):
                with socket.socket() as s:
                    s.bind(("127.0.0.1", port))
            return base
        except OSError:
            continue
    raise unittest.SkipTest("aucun port libre")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TcpTemplate(unittest.TestCase):
    def test_ping_and_run_through_the_registry(self) -> None:
        base = _free_base()
        yml = MAX_YML.format(target="x").replace("[7100, 4]", f"[{base}, 4]")
        # The extension range must not hit DCC_PORT_RANGES: patch them out for the test.
        with ExtFolder() as ext, mock.patch("core.constants.DCC_PORT_RANGES", {}):
            folder = ext.add("max", yml)
            script = folder / "dcc_side" / "tcp_json_server.py"
            shutil.copy(TEMPLATES_DIR / "tcp_json_server.py", script)
            (script.parent / "flux_bridge.json").write_text(json.dumps(
                {"soft": "max", "label": "3ds Max", "port_base": base, "port_count": 4}), encoding="utf-8")
            mod = _load(script, "flux_test_tcp_template")
            bridge = mod.start(extra_globals={"rt": "fake runtime"})
            try:
                self.assertEqual(bridge.port, base)
                self.assertTrue(primitives.ping("max", base)["ok"])
                self.assertEqual(primitives.scan_ports("max")[0]["port"], base)
                found = session.find_instance("max")
                live = session.live_session("max", found["port"])
                self.assertEqual(live.run("result = rt + ' ok'"), {"ok": True, "result": "fake runtime ok"})
                bad = live.run("raise RuntimeError('boom')")
                self.assertFalse(bad["ok"])
                self.assertIn("boom", bad["error"])
                self.assertEqual(live.run("result = object()")["ok"], True)   # not JSON: repr
                second = mod.start()
                try:
                    self.assertEqual(second.port, base + 1)                   # a second instance
                finally:
                    second.stop()
            finally:
                bridge.stop()


class MailboxTemplate(unittest.TestCase):
    def test_poll_answers_a_request(self) -> None:
        yml = MAX_YML.format(target="x").replace("transport: tcp_json", "transport: file_mailbox")
        with ExtFolder() as ext, mock.patch.dict(os.environ):
            os.environ["FLUX_MD_MAILBOX_ROOT"] = str(ext.tmp / "mail")
            folder = ext.add("max", yml)
            script = folder / "dcc_side" / "file_mailbox_server.py"
            shutil.copy(TEMPLATES_DIR / "file_mailbox_server.py", script)
            (script.parent / "flux_bridge.json").write_text(json.dumps(
                {"soft": "max", "label": "3ds Max", "mailbox": "flux_max_bridge"}), encoding="utf-8")
            mod = _load(script, "flux_test_mailbox_template")
            stop = threading.Event()
            loop = threading.Thread(target=mod.serve_forever, kwargs={"interval": 0.02, "should_stop": stop.is_set})
            loop.start()
            try:
                primitives.wait_ready("max", timeout=5, poll=0.05)
                self.assertEqual(len(primitives.scan_ports("max")), 1)
                live = session.live_session("max", None)
                self.assertEqual(live.run("result = 6 * 7", timeout=10)["result"], 42)
                self.assertIn("ZeroDivisionError", live.run("result = 1 / 0", timeout=10)["error"])
            finally:
                stop.set()
                loop.join(5)
            self.assertFalse((ext.tmp / "mail" / "flux_max_bridge" / "alive.json").exists())


if __name__ == "__main__":
    unittest.main()
