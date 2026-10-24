# ADR 0068 (2026-10-24): the InputsPageReader node, the flow picks its page. A click runs
# every active flow listening to that button; another start reads the page defaults.

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from flux_flows import locations, page_inputs, page_store, pages, rights, runs, scheduler, store, validate
from flux_flows.model import parse_flow
from routers import flows as flows_router


def _page() -> dict:
    return {"page": 1, "id": "daily_render", "label": "Daily render", "icon": "film",
            "layout": [{"row": [{"id": "dest_folder", "kind": "dir", "label": "Dossier", "default": "$FLUX/DAILY"}]},
                       {"row": [{"id": "render", "kind": "button", "label": "Lancer"},
                                {"id": "clean", "kind": "button", "label": "Nettoyer"}]}]}


def _flow(name: str = "daily_render", button: str = "render") -> dict:
    ports = page_inputs.ports_of(pages.parse_page(_page()))
    return {"flux_flow": 2, "name": name,
            "interface": {"inputs": [], "outputs": [{"id": "dir", "type": "dir"}]},
            "nodes": {"p": {"type": "event.page_inputs", "params": {"page": "daily_render", "ports": ports}},
                      "m": {"type": "event.manual"},
                      "o": {"type": "subflow.flow_output", "params": {"id": "dir"}}},
            "links": [{"from": f"p.{button}", "to": "o.exec"}, {"from": "m.then", "to": "o.exec"},
                      {"from": "p.dest_folder", "to": "o.value"}]}


class Ports(unittest.TestCase):
    def test_one_exec_per_button_one_output_per_field(self) -> None:
        got = page_inputs.ports_of(pages.parse_page(_page()))
        self.assertEqual(got["outputs"], {"dest_folder": "dir", "render": "exec", "clean": "exec"})
        self.assertEqual(got["labels"]["render"], "Lancer")

    def test_validation(self) -> None:
        flow = parse_flow(_flow())
        page = pages.parse_page(_page())
        env = validate.Env(page_lookup=lambda pid: page if pid == "daily_render" else None)
        codes = [i.code for i in validate.validate(flow, env)]
        self.assertNotIn("E_PAGE_NOT_FOUND", codes)
        self.assertNotIn("W_PAGE_LINK_BROKEN", codes)
        gone = pages.parse_page({**_page(), "layout": [_page()["layout"][1]]})   # no dest_folder any more
        codes = [i.code for i in validate.validate(flow, validate.Env(page_lookup=lambda pid: gone))]
        self.assertIn("W_PAGE_LINK_BROKEN", codes)
        codes = [i.code for i in validate.validate(flow, validate.Env(page_lookup=lambda pid: None))]
        self.assertIn("E_PAGE_NOT_FOUND", codes)


class Click(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_page_inputs_"))
        self.roots = {"shipped": locations.shipped_dir(), "team": self.tmp / "ext" / "flows",
                      "project": None, "perso": self.tmp / "user" / "flows"}
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
        page_store.save_page(locations.page_roots(None), "team", pages.parse_page(_page()), user="ADAM")
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

    def _active(self, scope: str, doc: dict) -> None:
        store.increment_flow(self.roots, scope, doc["name"], user="ADAM", flow=parse_flow(doc))
        store.set_active(self.roots, scope, doc["name"], True, user="ADAM")

    def test_ports_route(self) -> None:
        got = self.client.get("/flows/pages/daily_render/ports").json()
        self.assertEqual(got["defaults"], {"dest_folder": "$FLUX/DAILY"})
        self.assertEqual(self.client.get("/flows/pages/nothing/ports").status_code, 404)

    def test_click_runs_every_active_listener(self) -> None:
        r = self.client.post("/flows/pages/daily_render/click", json={"button": "render"})
        self.assertEqual(r.status_code, 409)                          # nobody listens yet
        self._active("team", _flow())
        self._active("perso", _flow("my_copy"))
        store.increment_flow(self.roots, "team", "not_active", user="ADAM", flow=parse_flow(_flow("not_active")))
        self._active("team", _flow("other_button", button="clean"))
        flows = self.client.get("/flows/pages/daily_render/flows").json()
        self.assertEqual(sorted(l["flow"] for l in flows["listeners"]["render"]), ["daily_render", "my_copy"])
        self.assertIn("not_active", [u["flow"] for u in flows["uses"]])
        r = self.client.post("/flows/pages/daily_render/click",
                             json={"button": "render", "values": {"dest_folder": "D:/x"}})
        self.assertEqual(r.status_code, 200, r.text)
        done = [self._wait(x["run_id"]) for x in r.json()["runs"]]
        self.assertEqual(sorted(d["flow"] for d in done), ["daily_render", "my_copy"])
        for rec in done:
            self.assertEqual(rec["status"], "ok", rec)
            self.assertEqual(rec["outputs"]["dir"], "D:/x")
            self.assertEqual(rec["trigger"]["page_button"], "daily_render/render")
        last = self.client.get("/flows/runs", params={"flow": "daily_render", "event": "daily_render/render"}).json()
        self.assertEqual(len(last), 1)

    def test_another_start_reads_the_page_defaults(self) -> None:
        self._active("team", _flow())
        r = self.client.post("/flows/daily_render/run", json={"event": "m"})
        self.assertEqual(r.status_code, 200, r.text)
        rec = self._wait(r.json()["run_id"])
        self.assertEqual((rec["status"], rec["outputs"]["dir"]), ("ok", "$FLUX/DAILY"), rec)
