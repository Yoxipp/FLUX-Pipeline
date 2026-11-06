# test_bridge_quiet_disconnect.py - a client hanging up prints nothing in the Houdini console.

from __future__ import annotations

import contextlib
import io
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

_SERVER_SRC = Path(__file__).resolve().parents[2] / "dcc" / "houdini" / "flux_houdini_server.py"


def _load_server_module() -> types.ModuleType:
    """Load the bridge without its trailing auto start() and with a fake `hou`."""
    source = _SERVER_SRC.read_text(encoding="utf-8-sig").rstrip()
    assert source.endswith("start()")
    module = types.ModuleType("flux_houdini_server_under_test")
    with mock.patch.dict(sys.modules, {"hou": mock.MagicMock()}):
        exec(compile(source[: -len("start()")], str(_SERVER_SRC), "exec"), module.__dict__)
    return module


class _HungUpFile:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def write(self, _data: bytes) -> int:
        raise self.exc


def _handler(mod: types.ModuleType, wfile) -> object:
    handler = mod._Handler.__new__(mod._Handler)
    handler.wfile = wfile
    handler.request_version = "HTTP/1.1"
    handler.requestline = "GET /state HTTP/1.1"
    handler.command = "GET"
    handler.client_address = ("127.0.0.1", 0)
    return handler


class BridgeQuietDisconnectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_server_module()
        # The request log is not what is under test.
        cls.mod._Handler.log_message = lambda *_a, **_k: None

    def test_hang_up_prints_nothing_and_does_not_raise(self):
        for exc in (ConnectionAbortedError(10053, "aborted"), ConnectionResetError(), BrokenPipeError()):
            with self.subTest(exc=type(exc).__name__):
                out = io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                    _handler(self.mod, _HungUpFile(exc))._send_json({"ok": True})
                self.assertEqual(out.getvalue(), "")

    def test_answer_still_written_when_the_client_stays(self):
        wfile = io.BytesIO()
        _handler(self.mod, wfile)._send_json({"ok": True})
        self.assertTrue(wfile.getvalue().endswith(json.dumps({"ok": True}).encode()))


if __name__ == "__main__":
    unittest.main()
