# P5 (2026-10-23): activation gate (01 §8): 0 error, warnings acknowledged, dry run
# passed on the frozen version `current`; a new version keeps active_version; legacy_* refused.

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from flux_flows import locations, rights, runs, scheduler
from routers import flows as flows_router
from tests.test_flux_flows import _flow_helpers as h

setUpModule = h.setUpModule        # noqa: N816
tearDownModule = h.tearDownModule  # noqa: N816


def _doc(label: str = "Daily", isolated: bool = True) -> dict:
    nodes = {"ev": {"type": "event.manual"}, "rec": {"type": "action.t_record", "params": {"value": label}}}
    if isolated:
        nodes["lone"] = {"type": "data.value", "params": {"value": 1}}   # W_ISOLATED_NODE
    return {"flux_flow": 2, "name": "daily", "label": label, "nodes": nodes,
            "links": [{"from": "ev.then", "to": "rec.exec"}]}


class Activation(unittest.TestCase):
    def setUp(self) -> None:
        h.reset()
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_activation_"))
        self.roots = {"shipped": locations.shipped_dir(), "team": self.tmp / "ext" / "flows",
                      "project": None, "perso": None}
        app = FastAPI()
        app.include_router(flows_router.router, prefix="/flows")
        self._patches = [
            mock.patch.object(locations, "roots_for", side_effect=lambda **_: dict(self.roots)),
            mock.patch.object(rights, "current_rights",
                              side_effect=lambda: rights.rights_from_data("ADAM", {"flows_team_td": True})),
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

    def _save_and_freeze(self, doc: dict, base: int = None) -> None:
        r = self.client.post("/flows/daily/increment", json={"flow": doc, "scope": "team", "base_revision": base})
        self.assertEqual(r.status_code, 200, r.text)

    def _dry(self, **extra) -> dict:
        r = self.client.post("/flows/daily/run", json={"scope": "team", "dry_run": True, **extra})
        run_id = r.json()["run_id"]
        for _ in range(200):
            rec = self.client.get(f"/flows/runs/{run_id}").json()
            gate = self.gate()
            if rec["status"] not in ("queued", "running") and (gate["dry_run"]["ok"] or rec["status"] != "ok"):
                return gate
            time.sleep(0.01)
        self.fail("dry run never ended")

    def gate(self) -> dict:
        return self.client.get("/flows/daily/activation", params={"scope": "team"}).json()

    def _acks(self, gate: dict) -> list:
        return [{k: w[k] for k in ("code", "node", "port")} for w in gate["warnings"]]

    def test_activation_needs_a_dry_run_and_the_warnings_read(self) -> None:
        self._save_and_freeze(_doc())
        gate = self.gate()
        self.assertEqual((gate["version"], gate["errors"], gate["dry_run"]["ok"], gate["ready"]), (1, [], False, False))
        self.assertIn("W_ISOLATED_NODE", [w["code"] for w in gate["warnings"]])
        r = self.client.post("/flows/daily/activate", json={"scope": "team", "acked": self._acks(gate)})
        self.assertEqual(r.status_code, 409)
        self.assertIn("essai a blanc", r.json()["detail"]["message"])
        gate = self._dry(version=1)
        self.assertTrue(gate["dry_run"]["ok"])
        self.assertEqual(h.CALLS, [])                               # the dry run simulated t_record
        r = self.client.post("/flows/daily/activate", json={"scope": "team"})
        self.assertEqual(r.status_code, 409)
        self.assertIn("avertissement", r.json()["detail"]["message"])
        r = self.client.post("/flows/daily/activate", json={"scope": "team", "acked": self._acks(gate)})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["active"], r.json()["active_version"]), (True, 1))
        self.assertTrue(self.gate()["warnings"][0]["acked"])

    def test_dry_run_of_the_saved_file_counts_when_equal_to_current(self) -> None:
        self._save_and_freeze(_doc(isolated=False))
        self.assertTrue(self._dry()["dry_run"]["ok"])
        self.assertTrue(self.gate()["ready"])

    def test_a_new_version_keeps_the_active_one(self) -> None:
        self._save_and_freeze(_doc(isolated=False))
        self._dry(version=1)
        self.assertEqual(self.client.post("/flows/daily/activate", json={"scope": "team"}).status_code, 200)
        self._save_and_freeze(_doc("B", isolated=False), base=2)
        gate = self.gate()
        self.assertEqual((gate["version"], gate["active_version"], gate["dry_run"]["ok"]), (2, 1, False))
        r = self.client.post("/flows/daily/run", json={"scope": "team"})   # runs active_version 1
        rec = self._wait(r.json()["run_id"])
        self.assertEqual((rec["version"], rec["status"]), (1, "ok"))
        self.assertEqual([v for _n, v in h.CALLS], ["Daily"])

    def test_legacy_never_activates(self) -> None:
        r = self.client.post("/flows/legacy_publish/copy", json={"from_scope": "shipped", "to_scope": "team"})
        self.assertEqual(r.status_code, 200)
        r = self.client.post("/flows/legacy_publish/activate", json={"scope": "team"})
        self.assertEqual(r.status_code, 409)
        self.assertIn("legacy", r.json()["detail"]["message"])

    def _wait(self, run_id: str) -> dict:
        for _ in range(200):
            rec = self.client.get(f"/flows/runs/{run_id}").json()
            if rec["status"] not in ("queued", "running"):
                return rec
            time.sleep(0.01)
        self.fail("run never ended")


if __name__ == "__main__":
    unittest.main()
