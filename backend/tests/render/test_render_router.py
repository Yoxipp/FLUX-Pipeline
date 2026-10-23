# test_render_router.py - render router: settings, submit (dry run), follow-up, finish notification.

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import render


class RenderRouter(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.project_dir = self.tmp / "proj"
        self.project_dir.mkdir()
        self.render_json = self.tmp / "render.json"
        # Simulation is opt-in since 2026-10-23: these tests run in it unless they say otherwise.
        self.render_json.write_text('{"dry_run": true}', encoding="utf-8")
        render._running.clear()
        self.addCleanup(render._running.clear)
        app = FastAPI()
        app.include_router(render.router, prefix="/render")
        self.client = TestClient(app)
        patches = [
            mock.patch.object(render.project_utils, "project_exists", return_value=True),
            mock.patch.object(render.project_utils, "get_project_path", return_value=str(self.project_dir)),
            mock.patch("core.paths.get_project_render_path", return_value=self.render_json),
            mock.patch.object(render.config, "get_current_user", return_value="adam"),
            mock.patch.object(render.farm_paths, "_unc_of_drive", return_value=None),
            # Hermetic: never reach the school machine's real Tractor client and engine.
            mock.patch.object(render.team_settings, "TRACTOR_PYTHON_CANDIDATES", ()),
            mock.patch.dict("os.environ", {"TRACTOR_ENGINE": ""}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _usda(self) -> Path:
        d = self.tmp / "asset"
        d.mkdir()
        f = d / "thing.usda"
        f.write_text('#usda 1.0\n\ndef Xform "Root"\n{\n}\n', encoding="utf-8")
        return f

    # settings
    def test_settings_defaults_and_priority_warning(self):
        r = self.client.get("/render/settings", params={"project": "P"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["settings"]["tractor_project"], "P")
        self.assertIsNone(body["warning"])

        r = self.client.put("/render/settings", params={"project": "P"}, json={"priority": 500})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["settings"]["priority"], 500)
        self.assertTrue(r.json()["warning"])

    def test_settings_unknown_key_is_400(self):
        r = self.client.put("/render/settings", params={"project": "P"}, json={"nope": 1})
        self.assertEqual(r.status_code, 400)

    # frame range detection
    def test_usd_range_reads_root_layer_time_codes(self):
        usd = self._usda()
        r = self.client.get("/render/usd_range", params={"project": "P", "path": str(usd)})
        self.assertEqual(r.json(), {"frame_start": None, "frame_end": None})
        usd.write_text('#usda 1.0\n(\n    startTimeCode = 1001\n    endTimeCode = 1048\n)\n', encoding="utf-8")
        r = self.client.get("/render/usd_range", params={"project": "P", "path": str(usd)})
        self.assertEqual(r.json(), {"frame_start": 1001, "frame_end": 1048})

    def test_submit_usd_without_range_uses_the_usd_range(self):
        usd = self._usda()
        usd.write_text('#usda 1.0\n(\n    startTimeCode = 1001\n    endTimeCode = 1010\n)\n', encoding="utf-8")
        r = self.client.post("/render/submit", json={"project": "P", "usd_path": str(usd)})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["frames"], [1001, 1010])

    # submit
    def test_submit_usd_dry_run_writes_job_files(self):
        usd = self._usda()
        r = self.client.post("/render/submit", json={
            "project": "P", "usd_path": str(usd), "frame_start": 1, "frame_end": 5})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body["dry_run"])
        self.assertIsNone(body["jid"])
        self.assertEqual(body["frames"], [1, 5])
        self.assertTrue(body["output"].replace("\\", "/").endswith("render/v001"))
        job_dir = usd.parent / "render" / "v001" / "_job"
        self.assertTrue(list(job_dir.glob("*.alf")))
        self.assertTrue(list(job_dir.glob("*.json")))

    def test_submit_usd_without_frames_is_400(self):
        r = self.client.post("/render/submit", json={"project": "P", "usd_path": str(self._usda())})
        self.assertEqual(r.status_code, 400)

    def test_submit_needs_shot_or_usd(self):
        r = self.client.post("/render/submit", json={"project": "P", "frame_start": 1, "frame_end": 2})
        self.assertEqual(r.status_code, 400)

    def test_submit_missing_usd_is_404(self):
        r = self.client.post("/render/submit", json={
            "project": "P", "usd_path": str(self.tmp / "missing.usda"), "frame_start": 1, "frame_end": 2})
        self.assertEqual(r.status_code, 404)

    def test_submit_real_run_on_local_disk_is_400(self):
        self.render_json.write_text(json.dumps({"dry_run": False}), encoding="utf-8")
        r = self.client.post("/render/submit", json={
            "project": "P", "usd_path": str(self._usda()), "frame_start": 1, "frame_end": 2})
        self.assertEqual(r.status_code, 400)
        self.assertIn("disque local", r.json()["detail"])

    def test_submit_shot_uses_production_frame_range(self):
        stage = self._usda()
        shot_folder = self.tmp / "shot"
        shot_folder.mkdir()
        from features.usd_assembler import shot_stage
        with mock.patch("features.render.freeze.freeze_shot", return_value={
                "usd": str(stage), "frozen": True, "warnings": [], "version": "v002"}), \
             mock.patch.object(shot_stage, "load_project_production", return_value=({}, False)), \
             mock.patch.object(shot_stage, "read_frame_range", return_value=(1001, 1010)), \
             mock.patch.object(shot_stage, "shot_dir", return_value=shot_folder), \
             mock.patch.object(shot_stage, "entity", return_value="SQ01_SH010"):
            r = self.client.post("/render/submit", json={"project": "P", "seq": "sq01", "shot": "sh010"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["frames"], [1001, 1010])
        self.assertIn("SQ01_SH010", body["title"])
        self.assertTrue(body["frozen"])

    # follow-up
    def test_jobs_and_farm_in_dry_run(self):
        r = self.client.get("/render/jobs", params={"project": "P"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["dry_run"])
        self.assertEqual(r.json()["jobs"], [])
        self.assertEqual(r.json()["finished"], [])

        r = self.client.get("/render/farm", params={"project": "P"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body["dry_run"])
        self.assertEqual(body["blades"], [])
        self.assertIn("schedule", body)

    def test_kill_in_dry_run_is_502(self):
        r = self.client.post("/render/jobs/12/kill", params={"project": "P"})
        self.assertEqual(r.status_code, 502)
        self.assertIn("Mode simulation", r.json()["detail"])

    def test_unknown_action_is_400(self):
        r = self.client.post("/render/jobs/12/explode", params={"project": "P"})
        self.assertEqual(r.status_code, 400)

    def test_jobs_scope_and_days_reach_the_bridge(self):
        with mock.patch.object(render.tractor_bridge, "jobs", return_value={"jobs": []}) as jobs:
            r = self.client.get("/render/jobs", params={"project": "P", "scope": "team", "days": 900})
            self.assertEqual(r.status_code, 200, r.text)
            _, kwargs = jobs.call_args
            self.assertEqual((kwargs["mine"], kwargs["project"], kwargs["days"]), (False, "P", 365))
            self.client.get("/render/jobs", params={"project": "P", "scope": "mine"})
            self.assertEqual((jobs.call_args[1]["mine"], jobs.call_args[1]["project"]), (True, None))
        r = self.client.get("/render/jobs", params={"project": "P", "scope": "boss"})
        self.assertEqual(r.status_code, 400)

    def test_tasks_and_log_endpoints(self):
        with mock.patch.object(render.tractor_bridge, "tasks", return_value={"tasks": [{"tid": 4}]}) as tasks, \
                mock.patch.object(render.tractor_bridge, "task_log", return_value={"log": "boom"}) as tlog:
            r = self.client.get("/render/jobs/34025/tasks", params={"project": "P"})
            self.assertEqual(r.json(), {"tasks": [{"tid": 4}]})
            self.assertEqual(tasks.call_args[0][1:], ("adam", 34025))
            r = self.client.get("/render/jobs/34025/tasks/4/log", params={"project": "P"})
            self.assertEqual(r.json(), {"log": "boom"})
            self.assertEqual(tlog.call_args[0][1:], ("adam", 34025, 4))

    # notification
    def test_notify_finished_once(self):
        running = {"jid": 5, "title": "t", "flux_user": "adam", "state": "active"}
        with mock.patch("features.activity.activity_writer.log_event") as log_event:
            self.assertEqual(render._notify_finished([running], "adam"), [])
            # Finished jobs now stay in the list: the final state triggers the notification.
            second = render._notify_finished([{**running, "state": "done"}], "adam")
            self.assertEqual([j["jid"] for j in second], [5])
            self.assertEqual(render._notify_finished([{**running, "state": "done"}], "adam"), [])
            log_event.assert_called_once()

    def test_notify_ignores_other_users_and_old_jobs(self):
        with mock.patch("features.activity.activity_writer.log_event") as log_event:
            render._notify_finished([{"jid": 6, "flux_user": "tom", "state": "active"},
                                     {"jid": 7, "flux_user": "adam", "state": "error"}], "adam")
            self.assertEqual(render._notify_finished([], "adam"), [])
            log_event.assert_not_called()


if __name__ == "__main__":
    unittest.main()
