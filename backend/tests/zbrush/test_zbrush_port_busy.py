# Port 9876 busy when ZBrush loads the plugin: the FLUX buttons must still be
# registered, and the first click must retry the bind once the port is free.
from __future__ import annotations

import importlib.util
import os
import socket
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

_PLUGIN = Path(__file__).resolve().parents[2] / "dcc" / "zbrush" / "zbrush_bridge_plugin.py"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class PortBusyAtStartupTest(unittest.TestCase):
    def setUp(self):
        self.port = _free_port()
        self.blocker = socket.socket()
        self.blocker.bind(("127.0.0.1", self.port))
        self.blocker.listen(1)
        self.zbc = mock.MagicMock()
        zbrush_pkg = types.ModuleType("zbrush")
        zbrush_pkg.commands = self.zbc
        self._patches = [
            mock.patch.dict(sys.modules, {"zbrush": zbrush_pkg, "zbrush.commands": self.zbc}),
            mock.patch.dict(os.environ, {"FLUX_ZBRUSH_PORT": str(self.port)}),
            mock.patch("time.sleep"),
        ]
        for p in self._patches:
            p.start()
        for attr in ("_flux_zbrush_sock", "_flux_zbrush_bg_started"):
            if hasattr(sys, attr):
                self.addCleanup(setattr, sys, attr, getattr(sys, attr))
                delattr(sys, attr)
        spec = importlib.util.spec_from_file_location("flux_zb_plugin_under_test", _PLUGIN)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        self.blocker.close()
        sock = getattr(sys, "_flux_zbrush_sock", None)
        if sock is not None:
            sock.close()
            del sys._flux_zbrush_sock
        if hasattr(sys, "_flux_zbrush_bg_started"):
            del sys._flux_zbrush_bg_started

    def test_buttons_registered_and_bind_retried_on_click(self):
        self.assertIsNone(self.mod._server_sock)
        self.zbc.add_subpalette.assert_any_call("ZPlugin:FLUX Bridge", title_mode=0)

        with mock.patch.object(self.mod, "_start_bg_responder"), \
             mock.patch.object(self.mod, "_autosave_ztl"), \
             mock.patch.object(self.mod, "_focus_flux_window"), \
             mock.patch.object(self.mod, "_focus_zbrush_window"):
            # Still busy: a clear note, no freeze.
            self.mod._on_publish_click()
            self.zbc.show_note.assert_called_once()
            self.zbc.freeze.assert_not_called()

            # Port released: the click binds and starts the publish.
            self.blocker.close()
            self.mod._on_publish_click()
            self.assertIsNotNone(self.mod._server_sock)
            self.zbc.freeze.assert_called_once()

    def test_answers_reach_client_and_ping_says_publishing(self):
        # Freeze-loop handler: the answer must arrive (graceful close, no RST), and a
        # ping says "publishing" so FLUX opens its Publisher page.
        import json
        import tempfile
        tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        out = os.path.join(tmp, "a_FLUX_TMP.ztl")
        # ZBrush writes the tool to its *tool path*, whatever set_next_filename says.
        tool = {"path": "C:/art/John_Sculpt_v003.ztl"}
        self.zbc.get_tool_path.side_effect = lambda tid: tool["path"]
        self.zbc.set_tool_path.side_effect = lambda tid, p: tool.__setitem__("path", p)
        self.zbc.press.side_effect = lambda item: (
            open(tool["path"], "wb").close() if item == "Tool:Save" and tool["path"].startswith(tmp) else None)
        for payload, expected in (
            ({"action": "ping"}, {"status": "ok", "version": "ZBrush 2026", "publishing": True}),
            ({"action": "export_ztl", "path": out}, {"status": "ok", "path": out}),
        ):
            server, client = socket.socketpair()
            client.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            self.assertFalse(self.mod._recv_and_dispatch(server))
            client.settimeout(2.0)
            data = b""
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                data += chunk
            client.close()
            self.assertEqual(json.loads(data.split(b"\n")[0]), expected)
        # The artist's own tool path is restored after the export.
        self.assertEqual(tool["path"], "C:/art/John_Sculpt_v003.ztl")

    def test_fbx_export_uses_zplugin_palette_and_checks_the_file(self):
        self.zbc.exists.side_effect = lambda item: item == "Zplugin:FBX ExportImport:Export"
        resp = self.mod._dispatch({"action": "export_fbx", "path": "C:/nowhere/x.fbx", "options": {}})
        self.zbc.press.assert_any_call("Zplugin:FBX ExportImport:Export")
        self.assertEqual(resp["status"], "error")      # nothing written -> clear error
        self.assertIn("FBX", resp["msg"])


if __name__ == "__main__":
    unittest.main()
