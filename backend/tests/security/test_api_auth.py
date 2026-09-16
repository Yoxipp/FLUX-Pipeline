# test_api_auth.py — S1: browser requests need the per-launch token.

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

import main
from core import api_auth

_BROWSER = {"Origin": "null", "Sec-Fetch-Site": "cross-site"}


class ApiAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def test_health_is_open(self):
        self.assertEqual(self.client.get("/health", headers=_BROWSER).status_code, 200)

    def test_browser_without_token_is_refused(self):
        r = self.client.post("/dcc/execute", json={"dcc": "maya", "command": "x"}, headers=_BROWSER)
        self.assertEqual(r.status_code, 403)

    def test_sec_fetch_site_alone_marks_a_browser(self):
        r = self.client.get("/logs", headers={"Sec-Fetch-Site": "same-origin"})
        self.assertEqual(r.status_code, 403)

    def test_browser_with_token_passes_the_guard(self):
        r = self.client.get("/auth/token-does-not-exist",
                            headers={**_BROWSER, "X-Flux-Token": api_auth.API_TOKEN})
        self.assertEqual(r.status_code, 404)  # reached routing, not blocked

    def test_browser_with_wrong_token_is_refused(self):
        r = self.client.get("/logs", headers={**_BROWSER, "X-Flux-Token": "nope"})
        self.assertEqual(r.status_code, 403)

    def test_non_browser_client_is_allowed(self):
        r = self.client.get("/auth/token-does-not-exist")
        self.assertEqual(r.status_code, 404)

    def test_token_endpoint_non_browser_only(self):
        self.assertEqual(self.client.get("/auth/token").json()["token"], api_auth.API_TOKEN)
        r = self.client.get("/auth/token", headers={**_BROWSER, "X-Flux-Token": api_auth.API_TOKEN})
        self.assertEqual(r.status_code, 403)

    def test_cors_preflight_is_open(self):
        r = self.client.options("/dcc/execute", headers={
            "Origin": "null", "Access-Control-Request-Method": "POST"})
        self.assertNotEqual(r.status_code, 403)

    def test_websocket_from_browser_without_token_is_closed(self):
        from starlette.websockets import WebSocketDisconnect
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect("/dcc/ws/status", headers={"Origin": "https://evil.example"}) as ws:
                ws.receive_text()


if __name__ == "__main__":
    unittest.main()
