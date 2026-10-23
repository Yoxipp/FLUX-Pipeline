# P2 (2026-10-22): WS /flows/ws (01 §10) and the run routes: draft run pushed live,
# history, cancel rights; the WS is covered by the X-Flux-Token guard (model test_api_auth).

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from flux_flows import locations, rights, runs
from routers import flows as flows_router
from tests.test_flux_flows import _flow_helpers as h
from tests.test_flux_flows._flow_helpers import setUpModule, tearDownModule  # noqa: F401


def _draft(seconds: float = 0) -> dict:
    nodes = {"n1": {"type": "event.manual"},
             "v": {"type": "data.value", "params": {"type": "int", "value": 7}},
             "a": {"type": "action.t_record"},
             "t": {"type": "flux.notify", "params": {"text": "fini", "level": "info"}}}
    links = [{"from": "n1.then", "to": "a.exec"}, {"from": "v.value", "to": "a.value"},
             {"from": "a.then", "to": "t.exec"}]
    if seconds:
        nodes["s"] = {"type": "action.t_block", "params": {"seconds": seconds}}
        links = [{"from": "n1.then", "to": "s.exec"}, {"from": "s.then", "to": "a.exec"}] + links[1:]
    return {"flux_flow": 2, "name": "daily", "nodes": nodes, "links": links}


class FlowsWs(unittest.TestCase):
    def setUp(self) -> None:
        h.reset()
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_flows_ws_"))
        self.roots = {"shipped": locations.shipped_dir(), "team": self.tmp / "ext" / "flows",
                      "project": None, "perso": self.tmp / "user" / "flows"}
        self.user, self.boxes = "ADAM", {"flows_td": True}
        app = FastAPI()
        app.include_router(flows_router.router, prefix="/flows")
        self._patches = [
            mock.patch.object(locations, "roots_for", side_effect=lambda **_: dict(self.roots)),
            mock.patch.object(rights, "current_rights",
                              side_effect=lambda: rights.rights_from_data(self.user, self.boxes)),
            mock.patch.object(runs, "runs_dir", side_effect=lambda scope, **_: self.tmp / scope / "runs"),
        ]
        for p in self._patches:
            p.start()
        self.client = TestClient(app).__enter__()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _wait(self, run_id: str) -> dict:
        for _ in range(200):
            rec = self.client.get(f"/flows/runs/{run_id}").json()
            if rec["status"] not in ("queued", "running"):
                return rec
            time.sleep(0.05)
        self.fail("run never finished")

    def test_draft_run_is_pushed_live_then_listed(self) -> None:
        with self.client.websocket_connect("/flows/ws") as ws:
            hello = ws.receive_json()
            self.assertEqual((hello["type"], hello["running"]), ("hello", []))
            r = self.client.post("/flows/daily/run", json={"scope": "perso", "draft": _draft()})
            self.assertEqual(r.status_code, 200, r.text)
            run_id = r.json()["run_id"]
            seen = []
            while True:
                msg = ws.receive_json()
                seen.append(msg)
                if msg["type"] == "run_finished":
                    break
        kinds = [m["type"] for m in seen]
        self.assertEqual(kinds[0], "run_started")
        self.assertIn("notify", kinds)
        self.assertEqual(seen[-1]["status"], "ok")
        self.assertTrue(all(m.get("run_id") == run_id for m in seen))
        states = {(m["node"], m["state"]) for m in seen if m["type"] == "node_state"}
        self.assertIn(("a", "ok"), states)
        self.assertIn(("v.value->a.value", "7"), {(m["link"], m["preview"]) for m in seen if m["type"] == "link_value"})
        rec = self._wait(run_id)
        self.assertEqual((rec["draft"], rec["version"], rec["status"]), (True, None, "ok"))
        listed = self.client.get("/flows/runs", params={"flow": "daily"}).json()
        self.assertEqual([x["run_id"] for x in listed], [run_id])
        self.assertTrue((self.tmp / "perso" / "runs" / "daily" / f"{run_id}.json").is_file())
        self.assertEqual(self.client.get("/flows/runs/nope").status_code, 404)

    def test_subscribe_filter(self) -> None:
        with self.client.websocket_connect("/flows/ws") as ws:
            ws.receive_json()
            ws.send_json({"type": "subscribe", "flow": "other"})
            time.sleep(0.05)
            r = self.client.post("/flows/daily/run", json={"scope": "perso", "draft": _draft()})
            self._wait(r.json()["run_id"])
            ws.send_json({"type": "subscribe"})
            time.sleep(0.05)
            r = self.client.post("/flows/daily/run", json={"scope": "perso", "draft": _draft()})
            msg = ws.receive_json()
        self.assertEqual((msg["type"], msg["run_id"]), ("run_started", r.json()["run_id"]))

    def test_draft_needs_td_and_cancel_rights(self) -> None:
        self.boxes = {}
        r = self.client.post("/flows/daily/run", json={"scope": "perso", "draft": _draft()})
        self.assertEqual(r.status_code, 403)
        self.boxes = {"flows_td": True}
        run_id = self.client.post("/flows/daily/run", json={"scope": "perso", "draft": _draft(5)}).json()["run_id"]
        time.sleep(0.1)
        self.user, self.boxes = "BOB", {}
        self.assertEqual(self.client.post(f"/flows/runs/{run_id}/cancel").status_code, 403)
        self.user = "ADAM"   # the launcher may cancel without the box
        self.assertEqual(self.client.post(f"/flows/runs/{run_id}/cancel").json()["status"], "cancelling")
        self.assertEqual(self._wait(run_id)["status"], "cancelled")
        self.assertEqual(self.client.post(f"/flows/runs/{run_id}/cancel").status_code, 409)

    def test_refused_draft_is_409_with_issues(self) -> None:
        doc = {"flux_flow": 2, "name": "daily", "nodes": {"a": {"type": "action.t_record"}}}
        r = self.client.post("/flows/daily/run", json={"scope": "perso", "draft": doc})
        self.assertEqual((r.status_code, r.json()["detail"]["status"]), (409, "refused"))
        self.assertEqual(r.json()["detail"]["issues"][0]["code"], "E_NO_EVENT")


class FlowsWsAuth(unittest.TestCase):
    def test_websocket_from_browser_without_token_is_closed(self) -> None:
        import main
        from starlette.websockets import WebSocketDisconnect

        client = TestClient(main.app)
        with self.assertRaises(WebSocketDisconnect):
            with client.websocket_connect("/flows/ws", headers={"Origin": "https://evil.example"}) as ws:
                ws.receive_json()


if __name__ == "__main__":
    unittest.main()
