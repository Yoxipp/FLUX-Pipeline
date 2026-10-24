# P7 (2026-10-24): generated Publisher panel of an extension software (04_PAGES_TOOL §7).
# Without a real bridge: a test publish flow and a fake extension (live check by the maintainer).

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from flux_flows import locations, pages, rights, runs, scheduler, store
from flux_flows.bridges import extension
from flux_flows.model import parse_flow
from flux_flows.pages import FlowInfo
from routers import flows as flows_router


def _flow(event: str = "event.publish_request"):
    return parse_flow({"flux_flow": 2, "name": "publish_max3d", "interface": {"inputs": [
        {"id": "session", "type": "session[max3d]"},
        {"id": "name", "type": "str", "label": "Nom", "default": ""},
        {"id": "format", "type": "select", "options": ["max", "fbx"], "default": "max"},
        {"id": "frames", "type": "int", "default": 1}]},
        "nodes": {"ev": {"type": event, "params": {"soft": "max3d"} if event == "event.publish_request" else {}}}})


class Generated(unittest.TestCase):
    def test_fields_from_the_interface(self) -> None:
        page, issues = pages.generated_publish_page("max3d", "3ds Max", FlowInfo("team", _flow(), active=True, valid=True))
        widgets = list(pages.iter_widgets(page))
        self.assertEqual([(w.id, w.kind) for w in widgets],
                         [("name", "text"), ("format", "select"), ("frames", "int"), ("publish_request", "button")])
        self.assertEqual([o.value for o in widgets[1].options], ["max", "fbx"])
        self.assertEqual(widgets[3].on_click.flow, "publish_max3d")
        self.assertEqual(issues, [])
        self.assertEqual([i.code for i in pages.validate_page(page) if i.level == "error"], [])

    def test_issues(self) -> None:
        codes = lambda info: [i.code for i in pages.generated_publish_page("max3d", "3ds Max", info)[1]]
        self.assertEqual(codes(None), ["P_FLOW_NOT_FOUND"])
        self.assertEqual(codes(FlowInfo("team", _flow(), active=False)), ["P_FLOW_INACTIVE"])
        self.assertEqual(codes(FlowInfo("team", _flow(), active=True, valid=False)), ["P_FLOW_INVALID"])
        self.assertEqual(codes(FlowInfo("team", _flow("event.manual"), active=True)), ["P_PUBLISH_NO_EVENT"])


class PanelRouter(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_publish_panel_"))
        self.roots = {"shipped": locations.shipped_dir(), "team": self.tmp / "ext" / "flows", "project": None, "perso": None}
        app = FastAPI()
        app.include_router(flows_router.router, prefix="/flows")
        fake = SimpleNamespace(soft="max3d", manifest=SimpleNamespace(label="3ds Max"), ok=True)
        self._patches = [
            mock.patch.object(locations, "roots_for", side_effect=lambda **_: dict(self.roots)),
            mock.patch.object(rights, "current_rights", side_effect=lambda: rights.rights_from_data("BOB", {})),
            mock.patch.object(runs, "runs_dir", side_effect=lambda scope, **_: self.tmp / scope / "runs"),
            mock.patch.object(scheduler, "_SCHEDULER", None),
            mock.patch.object(extension, "get", side_effect=lambda soft: fake if soft == "max3d" else None),
        ]
        for p in self._patches:
            p.start()
        self.client = TestClient(app).__enter__()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_panel_then_publish(self) -> None:
        got = self.client.get("/flows/pages/publish_panel/max3d").json()
        self.assertEqual([i["code"] for i in got["issues"]], ["P_FLOW_NOT_FOUND"])
        self.assertEqual(self.client.get("/flows/pages/publish_panel/blender").status_code, 404)
        store.increment_flow(self.roots, "team", "publish_max3d", user="ADAM", flow=_flow())
        self.assertEqual([i["code"] for i in self.client.get("/flows/pages/publish_panel/max3d").json()["issues"]],
                         ["P_FLOW_INACTIVE"])
        store.set_active(self.roots, "team", "publish_max3d", True, user="ADAM")
        got = self.client.get("/flows/pages/publish_panel/max3d").json()
        self.assertEqual(got["issues"], [])
        r = self.client.post("/flows/publish_max3d/run", json={"event": "publish_request", "values": {"name": "chair", "format": "fbx"}})
        self.assertEqual(r.status_code, 200, r.text)
        for _ in range(300):
            rec = self.client.get(f"/flows/runs/{r.json()['run_id']}").json()
            if rec["status"] not in ("queued", "running"):
                break
            time.sleep(0.01)
        self.assertEqual((rec["status"], rec["trigger"]["event"], rec["trigger"]["button"]), ("ok", "ev", "publish_request"))


if __name__ == "__main__":
    unittest.main()
