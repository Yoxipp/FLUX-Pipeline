# P6a (2026-10-23): the persistent headless worker (hython / mayapy contract) run by the
# test Python with a fake `hou` module: protocol, scene kept between two calls, errors,
# prints never break the protocol, timeout kills, closed at the end of the run. A fake
# worker never validates Houdini or Maya (live check by the maintainer).

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from flux_flows.bridges import headless
from flux_flows.bridges.primitives import BridgeError
from tests.test_flux_flows import _flow_helpers as h

setUpModule = h.setUpModule        # noqa: N816
tearDownModule = h.tearDownModule  # noqa: N816

FAKE_HOU = '''
class _Hip:
    def __init__(self):
        self.file = "untitled.hip"
    def path(self):
        return self.file
    def load(self, path, **kw):
        self.file = path
    def save(self, path=None, **kw):
        self.file = path or self.file

hipFile = _Hip()

def applicationVersionString():
    return "20.5.fake"
'''


class Worker(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_worker_"))
        (self.tmp / "hou.py").write_text(FAKE_HOU, encoding="utf-8")
        self.env = {**os.environ, "PYTHONPATH": str(self.tmp)}

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def start(self, *extra, **kw) -> headless.WorkerSession:
        cmd = [sys.executable, str(headless.worker_script()), "houdini", *extra]
        return headless.WorkerSession("houdini", cmd, env=self.env, **kw)

    def test_protocol_and_scene_kept_between_calls(self) -> None:
        s = self.start("/p/fx_v001.hip")
        try:
            self.assertEqual((s.version, s.scene, s.mode), ("20.5.fake", "/p/fx_v001.hip", "headless"))
            self.assertEqual(s.run("print('noise')\nhou.hipFile.save('/p/fx_v002.hip')\nresult = 1"),
                             {"id": 1, "ok": True, "result": 1})
            self.assertEqual(s.call("result = hou.hipFile.path()"), "/p/fx_v002.hip")
            bad = s.run("raise ValueError('nope')")
            self.assertFalse(bad["ok"])
            self.assertIn("ValueError: nope", bad["error"])
            self.assertEqual(s.call("result = {1}"), "{1}")          # not JSON: its repr
        finally:
            s.close()
        self.assertIsNotNone(s.proc.poll())
        self.assertIn("noise", s.log_path.read_text(encoding="utf-8"))
        self.assertIn("session headless morte", s.run("result = 1")["error"])

    def test_timeout_kills_the_worker(self) -> None:
        s = self.start()
        try:
            got = s.run("import time\ntime.sleep(5)", timeout=0.5)
            self.assertFalse(got["ok"])
            self.assertIn("timeout", got["error"])
            s.proc.wait(timeout=5)
            self.assertIsNotNone(s.proc.poll())
        finally:
            s.close()

    def test_boot_failure_is_reported(self) -> None:
        cmd = [sys.executable, str(headless.worker_script()), "blender"]
        with self.assertRaisesRegex(BridgeError, "logiciel headless inconnu"):
            headless.WorkerSession("houdini", cmd, env=self.env)

    def test_missing_exe(self) -> None:
        with self.assertRaisesRegex(BridgeError, "hython introuvable"):
            headless.start_worker("houdini", exe_fn=lambda soft: None)
        with self.assertRaisesRegex(BridgeError, "pas de mode headless"):
            headless.start_worker("nuke")

    def _patched_start(self):
        def start(soft, scene="", cancelled=None, **kw):
            return self.start(*([scene] if scene else []))
        return mock.patch.object(headless, "start_worker", side_effect=start)

    def test_instance_headless_closes_at_the_end_of_the_run(self) -> None:
        h.reset()
        flow = h.flow({"ev": "event.manual", "inst": ("session.hou_instance", {"mode": "headless"}),
                       "run": ("dcc.hou_run_script", {"code": "result = hou.hipFile.path()"}),
                       "rec": "action.t_record"},
                      ["ev.then->inst.exec", "inst.then->run.exec", "inst.session->run.session",
                       "run.then->rec.exec", "run.result->rec.value"])
        sessions = []
        real_start = self.start

        def start(soft, scene="", cancelled=None, **kw):
            sessions.append(real_start())
            return sessions[-1]

        with mock.patch.object(headless, "start_worker", side_effect=start):
            rec = h.run_flow(flow)
        self.assertEqual(rec["status"], "ok", rec.get("error"))
        self.assertEqual(h.CALLS[-1][1], "untitled.hip")
        self.assertIsNotNone(sessions[0].proc.poll())             # closed by the run's cleanup

    def test_run_headless_and_batch(self) -> None:
        h.reset()
        script = self.tmp / "job.py"
        script.write_text("result = {'scene': hou.hipFile.path(), 'n': args['n']}\n"
                          "if 'bad' in hou.hipFile.path():\n    raise RuntimeError('bad scene')\n", encoding="utf-8")
        flow = h.flow({"ev": "event.manual",
                       "one": ("action.run_headless", {"script": str(script), "scene": "/p/a.hip", "args": {"n": 3}}),
                       "rec": "action.t_record"},
                      ["ev.then->one.exec", "one.then->rec.exec", "one.result->rec.value"])
        with self._patched_start():
            rec = h.run_flow(flow, checked=False)
            self.assertEqual(h.CALLS[-1][1], {"scene": "/p/a.hip", "n": 3})
            batch = h.flow({"ev": "event.manual",
                            "b": ("action.batch", {"script": str(script), "scenes": ["/p/a.hip", "/p/bad.hip", "/p/c.hip"],
                                                   "args": {"n": 1}, "on_item_error": "continue"}),
                            "rec": "action.t_record"},
                           ["ev.then->b.exec", "b.then->rec.exec", "b.failed->rec.value"])
            rec = h.run_flow(batch, checked=False)
            self.assertEqual((rec["status"], h.CALLS[-1][1]), ("ok", 1))
            stop = h.flow({"ev": "event.manual",
                           "b": ("action.batch", {"script": str(script), "scenes": ["/p/bad.hip", "/p/c.hip"]})},
                          ["ev.then->b.exec"])
            rec = h.run_flow(stop, checked=False)
        self.assertIn("arret a la premiere erreur", rec["nodes"]["b"]["error"])
        dry = h.run_flow(batch, mode="dry", checked=False)
        self.assertTrue(any("3 scene(s), 3 lancement(s) de hython" in r["text_fr"] for r in dry["report"]))


if __name__ == "__main__":
    unittest.main()
