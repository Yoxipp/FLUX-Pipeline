# FLUX Work opened from Production (ADR 0090 point 3 + addendum): the scene goes to the
# Houdini already on it, else a blank one, else the first that answers, through /run;
# no Houdini -> a new one. The code sent only schedules the opening (the artist's
# dialog never holds /run). "Nouvelle instance" only launches FLUX Work scenes.

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dcc.houdini import work_open as wo
from features.houdini_work import work_store as ws
from routers import houdini_work


class FakeClient:
    def __init__(self, port, states, sent, scheduled=True):
        self.port, self.states, self.sent, self.scheduled = port, states, sent, scheduled

    def run(self, code, timeout=0):
        if code == wo.STATE_CODE:
            st = self.states.get(self.port)
            return {"ok": True, "result": st} if st is not None else {"error": "no answer"}
        self.sent.append((self.port, code))
        return {"ok": True, "result": {"scheduled": self.scheduled}}


class PickAndSend(unittest.TestCase):
    PATH = "C:/P/shot/SEQ010/SH020/cfx/work/houdini/CFX/w002.hip"

    def _open(self, states, scheduled=True):
        sent, launched = [], []
        res = wo.open_in_houdini(
            self.PATH, ports=lambda: sorted(states),
            client_factory=lambda port: FakeClient(port, states, sent, scheduled),
            launch=lambda scene: launched.append(scene) or True)
        return res, sent, launched

    def test_instance_already_on_the_scene_wins_then_blank_then_first(self) -> None:
        busy = {"path": "C:/x/other.hip", "new": False, "dirty": True}
        blank = {"path": "C:/x/untitled.hip", "new": True, "dirty": False}
        same = {"path": self.PATH.replace("/", "\\"), "new": False, "dirty": False}
        self.assertEqual(wo.pick_instance([(1, busy), (2, blank), (3, same)], self.PATH), 3)
        self.assertEqual(wo.pick_instance([(1, busy), (2, blank)], self.PATH), 2)
        self.assertEqual(wo.pick_instance([(1, busy), (2, None)], self.PATH), 1)
        self.assertIsNone(wo.pick_instance([(2, None)], self.PATH))

    def test_running_houdini_gets_a_deferred_opening(self) -> None:
        res, sent, launched = self._open({48884: {"path": "C:/x/a.hip", "new": False, "dirty": True}})
        self.assertEqual((res["mode"], res["port"], launched), ("sent", 48884, []))
        code = sent[0][1]
        compile(code, "<work open>", "exec")
        self.assertIn(repr(self.PATH), code)
        self.assertIn("hdefereval.executeDeferred(_flux_open)", code)
        for choice in ("Sauver puis ouvrir", "Nouvelle instance", "Annuler"):
            self.assertIn(choice, code)
        self.assertIn("hou.hipFile.load(_FLUX_PATH, suppress_save_prompt=True)", code)
        self.assertNotIn("merge", code)

    def test_no_houdini_or_a_refusal_launches_a_new_one(self) -> None:
        res, sent, launched = self._open({})
        self.assertEqual((res["mode"], launched), ("launched", [self.PATH]))
        res, sent, launched = self._open({48884: {"path": "C:/x/a.hip", "new": True, "dirty": False}},
                                         scheduled=False)
        self.assertEqual((res["mode"], launched), ("launched", [self.PATH]))


class Routes(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.project = root / "PROJ"
        self.project.mkdir()
        bundled = root / "bundled"
        bundled.mkdir()
        (bundled / "DEFAULT_SOP.hip").write_bytes(b"sop")
        for patcher in (mock.patch("core.paths.get_project_path", return_value=self.project),
                        mock.patch.object(ws, "BUNDLED_TEMPLATES", bundled)):
            patcher.start()
            self.addCleanup(patcher.stop)
        app = FastAPI()
        app.include_router(houdini_work.router, prefix="/dcc/houdini/work")
        self.client = TestClient(app)
        self.ref = {"project": "PROJ", "seq": "SEQ010", "shot": "SH020", "task": "CFX"}

    def test_open_starts_the_task_then_hands_the_scene_to_houdini(self) -> None:
        calls = []
        with mock.patch.object(wo, "open_in_houdini",
                               side_effect=lambda hip: calls.append(hip) or {"ok": True, "mode": "sent", "port": 1, "hip": hip}):
            got = self.client.post("/dcc/houdini/work/open", json=self.ref).json()
        self.assertEqual((got["mode"], got["version"], got["created_template"]), ("sent", "w000", True))
        self.assertTrue(calls[0].endswith("/CFX/w000.hip"))
        manifest = json.loads(Path(calls[0]).with_suffix(".json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["project"], "PROJ")

    def test_launch_only_accepts_work_scenes(self) -> None:
        with mock.patch.object(wo, "open_in_houdini", side_effect=lambda hip: {"ok": True, "hip": hip}):
            hip = self.client.post("/dcc/houdini/work/open", json=self.ref).json()["hip"]
        launched = []
        with mock.patch.object(wo, "launch_work",
                               side_effect=lambda path: launched.append(path) or {"ok": True, "mode": "launched"}):
            ok = self.client.post("/dcc/houdini/work/launch", json={"path": hip})
            bad = self.client.post("/dcc/houdini/work/launch", json={"path": str(self.project / "evil.hip")})
        self.assertEqual((ok.status_code, bad.status_code), (200, 400))
        self.assertEqual(launched, [hip])


if __name__ == "__main__":
    unittest.main()
