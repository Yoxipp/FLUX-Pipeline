# test_houdini_bridge_browser_guard.py — S2: the Houdini bridge refuses browser requests.

from __future__ import annotations

import http.client
import json
import sys
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

_SERVER_SRC = Path(__file__).resolve().parents[2] / "dcc" / "houdini" / "flux_houdini_server.py"


def _load_server_module() -> types.ModuleType:
    """Load the bridge without its trailing auto start() and with a fake `hou`."""
    source = _SERVER_SRC.read_text(encoding="utf-8-sig")
    source = source.rstrip()
    assert source.endswith("start()")
    source = source[: -len("start()")]
    module = types.ModuleType("flux_houdini_server_under_test")
    with mock.patch.dict(sys.modules, {"hou": mock.MagicMock()}):
        exec(compile(source, str(_SERVER_SRC), "exec"), module.__dict__)
    return module


class HoudiniBridgeBrowserGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_server_module()
        cls.dispatched = []

        def fake_dispatch(self, kind, payload=None, timeout=10.0):
            cls.dispatched.append((kind, payload))
            return {"ok": True}

        cls.mod._Handler._dispatch = fake_dispatch
        cls.httpd = cls.mod._ThreadedHTTPServer(("127.0.0.1", 0), cls.mod._Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.dispatched.clear()

    def _request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        return resp.status

    def test_backend_style_run_is_accepted(self):
        status = self._request("POST", "/run", json.dumps({"code": "result = 1"}),
                               {"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertEqual(len(self.dispatched), 1)

    def test_run_with_origin_is_refused(self):
        status = self._request("POST", "/run", json.dumps({"code": "x"}),
                               {"Content-Type": "application/json", "Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        self.assertEqual(self.dispatched, [])

    def test_run_with_sec_fetch_site_is_refused(self):
        status = self._request("POST", "/run", json.dumps({"code": "x"}),
                               {"Content-Type": "text/plain", "Sec-Fetch-Site": "cross-site"})
        self.assertEqual(status, 403)
        self.assertEqual(self.dispatched, [])

    def test_run_without_json_content_type_is_refused(self):
        status = self._request("POST", "/run", json.dumps({"code": "x"}), {"Content-Type": "text/plain"})
        self.assertEqual(status, 415)
        self.assertEqual(self.dispatched, [])

    def test_state_from_browser_is_refused(self):
        self.assertEqual(self._request("GET", "/state", headers={"Sec-Fetch-Site": "same-origin"}), 403)


if __name__ == "__main__":
    unittest.main()
