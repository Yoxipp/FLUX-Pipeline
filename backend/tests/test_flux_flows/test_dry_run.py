# P2 (2026-10-22): dry run (01 §5): effect nodes simulated, nothing written but the run
# record, reads for real; the route runs the saved file (never a draft), TD only.

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from flux_flows import locations, rights, runs
from routers import flows as flows_router
from tests.test_flux_flows import _flow_helpers as h
from tests.test_flux_flows._flow_helpers import flow, run_flow, setUpModule, tearDownModule  # noqa: F401


def _doc() -> dict:
    return {"flux_flow": 2, "name": "daily", "variables": [{"name": "n", "type": "int", "default": 0}],
            "nodes": {"n1": {"type": "event.manual"},
                      "s": {"type": "data.set_variable", "params": {"name": "n", "value": 3}},
                      "a": {"type": "action.t_record"},
                      "g": {"type": "data.get_variable", "params": {"name": "n"}},
                      "t": {"type": "flux.notify", "params": {"text": "fini", "where": "both"}},
                      "l": {"type": "flux.legacy_command", "params": {"command": "conform_texture"}}},
            "links": [{"from": "n1.then", "to": "s.exec"}, {"from": "s.then", "to": "a.exec"},
                      {"from": "g.value", "to": "a.value"}, {"from": "a.then", "to": "t.exec"},
                      {"from": "t.then", "to": "l.exec"}]}


class DryRun(unittest.TestCase):
    def setUp(self) -> None:
        h.reset()
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_dry_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_effects_are_simulated_reads_are_real(self) -> None:
        from flux_flows.model import parse_flow

        with mock.patch("features.activity.activity_writer.log_event") as log_event:
            rec = run_flow(parse_flow(_doc()), mode="dry", folder=self.tmp / "runs")
        self.assertEqual(rec["status"], "ok")
        self.assertEqual(h.CALLS, [])                 # effect body never called
        log_event.assert_not_called()
        self.assertEqual(rec["nodes_simulated"], ["a", "t", "l"])
        texts = [line["text_fr"] for line in rec["report"]]
        self.assertTrue(texts[0].startswith("Essai a blanc"))
        self.assertIn("enregistrerait 3", texts)        # the variable really changed (no effect)
        self.assertIn("afficherait : fini", texts)
        self.assertTrue(any("conform_texture" in t for t in texts))
        written = [p.relative_to(self.tmp).as_posix() for p in self.tmp.rglob("*") if p.is_file()]
        self.assertEqual(written, [f"runs/daily/{rec['run_id']}.json"])   # only the record


class DryRunRoute(unittest.TestCase):
    def setUp(self) -> None:
        h.reset()
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_dry_route_"))
        self.roots = {"shipped": locations.shipped_dir(), "team": self.tmp / "ext" / "flows",
                      "project": None, "perso": self.tmp / "user" / "flows"}
        self.boxes: dict = {}
        app = FastAPI()
        app.include_router(flows_router.router, prefix="/flows")
        self._patches = [
            mock.patch.object(locations, "roots_for", side_effect=lambda **_: dict(self.roots)),
            mock.patch.object(rights, "current_rights", side_effect=lambda: rights.rights_from_data("ADAM", self.boxes)),
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

    def test_dry_run_needs_td_and_a_saved_file(self) -> None:
        body = {"scope": "perso", "dry_run": True}
        self.assertEqual(self.client.post("/flows/daily/run", json=body).status_code, 403)
        self.boxes = {"flows_td": True}
        self.assertEqual(self.client.post("/flows/daily/run", json=body).status_code, 404)
        r = self.client.post("/flows/daily/run", json={**body, "draft": _doc()})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.put("/flows/daily", json={"flow": _doc(), "scope": "perso"}).status_code, 200)
        with mock.patch("features.activity.activity_writer.log_event"):
            r = self.client.post("/flows/daily/run", json=body)
            self.assertEqual(r.json()["mode"], "dry")
            rec = self._wait(r.json()["run_id"])
        self.assertEqual((rec["mode"], rec["status"], rec["base_revision"]), ("dry", "ok", 1))
        self.assertEqual(h.CALLS, [])

    def test_real_run_needs_an_active_flow(self) -> None:
        self.boxes = {"flows_td": True}
        self.client.put("/flows/daily", json={"flow": _doc(), "scope": "perso"})
        r = self.client.post("/flows/daily/run", json={"scope": "perso"})
        self.assertEqual((r.status_code, r.json()["detail"]["message"]), (409, "flow non actif"))

    def _wait(self, run_id: str) -> dict:
        import time

        for _ in range(100):
            rec = self.client.get(f"/flows/runs/{run_id}").json()
            if rec["status"] not in ("queued", "running"):
                return rec
            time.sleep(0.05)
        self.fail("run never finished")


if __name__ == "__main__":
    unittest.main()
