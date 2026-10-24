# P7 (2026-10-24): a page button runs the active flow by button_id, for an artist without the TD box (01 §7, A7).

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from flux_flows import engine, locations, rights, runs, scheduler, store
from flux_flows.model import parse_flow
from routers import flows as flows_router


def _flow():
    return parse_flow({"flux_flow": 2, "name": "daily_render",
                       "interface": [{"id": "dest_folder", "type": "dir", "default": "$FLUX/DAILY"}],
                       "nodes": {"m": {"type": "event.manual"},
                                 "b": {"type": "event.button", "params": {"button_id": "render"}}}})


class PageRun(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_page_run_"))
        self.roots = {"shipped": locations.shipped_dir(), "team": self.tmp / "ext" / "flows",
                      "project": None, "perso": None}
        app = FastAPI()
        app.include_router(flows_router.router, prefix="/flows")
        self._patches = [
            mock.patch.object(locations, "roots_for", side_effect=lambda **_: dict(self.roots)),
            mock.patch.object(rights, "current_rights", side_effect=lambda: rights.rights_from_data("BOB", {})),
            mock.patch.object(runs, "runs_dir", side_effect=lambda scope, **_: self.tmp / scope / "runs"),
            mock.patch.object(scheduler, "_SCHEDULER", None),
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
        for _ in range(300):
            rec = self.client.get(f"/flows/runs/{run_id}").json()
            if rec["status"] not in ("queued", "running"):
                return rec
            time.sleep(0.01)
        self.fail("run never ended")

    def test_artist_runs_the_active_flow_by_button_id(self) -> None:
        store.increment_flow(self.roots, "team", "daily_render", user="ADAM", flow=_flow())
        r = self.client.post("/flows/daily_render/run", json={"event": "render", "values": {"dest_folder": "D:/x"}})
        self.assertEqual(r.status_code, 409)                       # not active: the button is greyed out
        store.set_active(self.roots, "team", "daily_render", True, user="ADAM")
        r = self.client.post("/flows/daily_render/run", json={"event": "render", "values": {"dest_folder": "D:/x"}})
        self.assertEqual(r.status_code, 200, r.text)
        rec = self._wait(r.json()["run_id"])
        self.assertEqual(rec["status"], "ok", rec)
        self.assertEqual(rec["trigger"]["event"], "b")
        self.assertEqual(rec["trigger"]["values"], {"dest_folder": "D:/x"})

    def test_unknown_button_is_refused(self) -> None:
        store.increment_flow(self.roots, "team", "daily_render", user="ADAM", flow=_flow())
        store.set_active(self.roots, "team", "daily_render", True, user="ADAM")
        r = self.client.post("/flows/daily_render/run", json={"event": "nothing"})
        self.assertEqual(r.status_code, 409)


class StartNode(unittest.TestCase):
    def test_start_node_for(self) -> None:
        flow = parse_flow({"flux_flow": 2, "name": "pub", "nodes": {
            "a": {"type": "event.button", "params": {"button_id": "go"}}, "r": {"type": "event.publish_request"}}})
        self.assertEqual(engine.start_node_for(flow, "go"), "a")
        self.assertEqual(engine.start_node_for(flow, "publish_request"), "r")
        self.assertIsNone(engine.start_node_for(flow, "x"))


if __name__ == "__main__":
    unittest.main()
