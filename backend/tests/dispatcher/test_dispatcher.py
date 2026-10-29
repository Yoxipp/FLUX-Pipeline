# ADR 0067: the dispatcher (features/dispatcher) and the Dispatcher nodes.
# The local backend runs real subprocesses (this Python, declared as program "py");
# the tractor backend is tested in simulation (render.json dry_run) and through to_alf only:
# nothing reaches a Tractor engine. The pipe config is a temp file, never the real CONFIG.

from __future__ import annotations

import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from features.dispatcher import api, config, local_backend, render_shot, tractor_backend
from features.dispatcher.jobs import DispatchError, DispatchJob, DispatchTask


def _write(path: Path, data: dict) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class _Case(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.pipe = self.tmp / "CONFIG" / "dispatcher.json"
        _write(self.pipe, {"backend": "local", "local": {"max_parallel": 2},
                           "programs": {"py": {"local": sys.executable, "tractor": "python"}}})
        self.patch = mock.patch.object(config, "pipe_path", return_value=self.pipe)
        self.patch.start()
        local_backend.reset()

    def tearDown(self) -> None:
        self.patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def wait_final(self, job_id: str, limit: float = 20.0) -> dict:
        t0 = time.monotonic()
        while time.monotonic() - t0 < limit:
            st = api.status(job_id)
            if st["state"] in ("done", "error", "cancelled"):
                return st
            time.sleep(0.05)
        self.fail(f"{job_id} not finished")


class ConfigTest(_Case):
    def test_defaults_without_files(self) -> None:
        with mock.patch.object(config, "pipe_path", return_value=self.tmp / "none.json"):
            cfg = config.load(None)
        self.assertEqual(cfg["backend"], "local")
        self.assertIn("husk", cfg["programs"])

    def test_project_overrides_the_pipe_key_by_key(self) -> None:
        project = self.tmp / "PROJ"
        _write(project / "_flux_setup" / "dispatcher.json",
               {"backend": "tractor", "programs": {"py": {"tractor": "//srv/python.exe"}}, "priority": 50})
        cfg = config.load(project)
        self.assertEqual((cfg["backend"], cfg["priority"], cfg["local"]["max_parallel"]), ("tractor", 50, 2))
        self.assertEqual(cfg["programs"]["py"], {"local": sys.executable, "tractor": "//srv/python.exe"})
        self.assertIn("husk", cfg["programs"])               # defaults kept

    def test_unknown_backend_and_undeclared_program(self) -> None:
        _write(self.pipe, {"backend": "deadline"})
        with self.assertRaises(config.ConfigError):
            config.load(None)
        with self.assertRaises(config.ConfigError):
            config.program(config.DEFAULTS, "bash", "local")


class LocalBackendTest(_Case):
    def _job(self, *codes: str) -> DispatchJob:
        return DispatchJob(title="t", user="ADAM", project="", tasks=[DispatchTask(f"t{i}", "py", ["-c", c])
                                                                     for i, c in enumerate(codes)])

    def test_tasks_run_and_job_is_done(self) -> None:
        out = self.tmp / "out"
        out.mkdir()
        res = api.submit(self._job(*[f"open(r'{out / str(i)}', 'w').write('x')" for i in range(3)]), None)
        self.assertEqual((res["backend"], res["tasks"]), ("local", 3))
        self.assertTrue(res["job_id"].startswith("local:"))
        st = self.wait_final(res["job_id"])
        self.assertEqual((st["state"], st["done"], st["total"], st["errors"]), ("done", 3, 3, 0))
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["0", "1", "2"])

    def test_failing_task_makes_the_job_error(self) -> None:
        res = api.submit(self._job("print('ok')", "import sys; print('boom'); sys.exit(3)"), None)
        st = self.wait_final(res["job_id"])
        self.assertEqual((st["state"], st["errors"]), ("error", 1))
        bad = [t for t in st["tasks"] if t["state"] == "error"][0]
        self.assertEqual(bad["returncode"], 3)
        self.assertIn("boom", bad["log"])

    def test_cancel_stops_running_and_waiting_tasks(self) -> None:
        res = api.submit(self._job(*["import time; time.sleep(30)"] * 4), None)
        time.sleep(0.5)
        api.cancel(res["job_id"])
        st = self.wait_final(res["job_id"])
        self.assertEqual(st["state"], "cancelled")
        self.assertTrue(all(t["state"] == "cancelled" for t in st["tasks"]))

    def test_refusals(self) -> None:
        job = DispatchJob(title="t", user="ADAM", project="", tasks=[DispatchTask("x", "bash", ["-c", "rm"])])
        with self.assertRaises(DispatchError):
            api.submit(job, None)                            # not in programs
        with self.assertRaises(DispatchError):
            api.submit(DispatchJob(title="t", user="ADAM", project=""), None)   # no task
        with self.assertRaises(DispatchError):
            api.status("nobackend")
        with self.assertRaises(DispatchError):
            api.status("local:unknown")


class TractorBackendTest(_Case):
    SETTINGS = {"dry_run": True, "tractor_project": "DEMO", "maxactive": 0, "envkeys": ["houdini20"],
                "service_karma": "karma", "service_renderman": "rman"}

    def _job(self, arg: str = "//srv/a.hip") -> DispatchJob:
        return DispatchJob(title="cache SH010", user="ADAM", project="DEMO",
                           tasks=[DispatchTask("t1", "py", ["-c", "x", arg])], record_dir=str(self.tmp / "rec"))

    def test_alf_has_one_task_per_dispatcher_task(self) -> None:
        job = self._job()
        job.tasks.append(DispatchTask("t2", "py", ["two words"]))
        alf = tractor_backend.to_alf(job, [["python", "-c", "x", "//srv/a.hip"], ["python", "two words"]],
                                     self.SETTINGS, strict=True)
        self.assertTrue(alf.startswith("##AlfredToDo 3.0"))
        self.assertIn("-projects {DEMO}", alf)
        self.assertIn("-envkey {houdini20}", alf)
        self.assertEqual(alf.count("RemoteCmd"), 2)
        self.assertIn("{two words}", alf)

    def test_strict_refuses_drive_letters_and_tcl(self) -> None:
        with self.assertRaises(DispatchError):
            tractor_backend.to_alf(self._job(), [["python", "D:/proj/a.hip"]], self.SETTINGS, strict=True)
        tractor_backend.to_alf(self._job(), [["python", "D:/proj/a.hip"]], self.SETTINGS, strict=False)
        with self.assertRaises(DispatchError):
            tractor_backend.to_alf(self._job(), [["python", "[exec rm]"]], self.SETTINGS, strict=False)

    def test_simulated_submit_writes_the_job_and_spools_nothing(self) -> None:
        _write(self.pipe, {"backend": "tractor", "programs": {"py": {"local": sys.executable, "tractor": "python"}}})
        with mock.patch("features.render.team_settings.effective_settings", return_value=dict(self.SETTINGS)), \
                mock.patch("features.render.tractor_bridge.call") as call:
            res = api.submit(self._job(), None)
            st = api.status(res["job_id"], "DEMO", "ADAM")
        call.assert_not_called()
        self.assertTrue(res["dry_run"])
        self.assertEqual(st["state"], "simulated")
        self.assertTrue(Path(res["files"]["alf"]).is_file())
        self.assertIn('"user": "ADAM"', Path(res["files"]["alf"]).read_text(encoding="utf-8"))

    def test_status_maps_tractor_states(self) -> None:
        job = {"jid": 12, "numTasks": 4, "numDone": 4, "numError": 0, "numActive": 0}
        settings = {**self.SETTINGS, "dry_run": False}
        with mock.patch("features.render.team_settings.effective_settings", return_value=settings), \
                mock.patch("features.render.tractor_bridge.call", return_value={"jobs": [job]}):
            st = api.status("tractor:12", "DEMO", "ADAM")
        self.assertEqual((st["state"], st["done"], st["total"]), ("done", 4, 4))


class RenderShotPlanTest(_Case):
    def test_usd_plan_one_task_per_chunk(self) -> None:
        usd = self.tmp / "PROJ" / "shot" / "light_LAST.usd"
        usd.parent.mkdir(parents=True)
        usd.write_text("#usda 1.0\n", encoding="utf-8")
        frozen = {"usd": str(usd.with_name("light_v002.usd")), "frozen": True, "warnings": []}
        with mock.patch("features.render.freeze.freeze_usd", return_value=frozen), \
                mock.patch.object(render_shot, "_usd_range", return_value=(1001, 1012)):
            job, info = render_shot.plan(project="PROJ", project_path=self.tmp / "PROJ", user="ADAM", usd=str(usd),
                                         renderer="karma", chunk_size=5, dry=True)
        self.assertEqual([t.title for t in job.tasks], ["frames 1001-1005", "frames 1006-1010", "frames 1011-1012"])
        self.assertTrue(all(t.program == "husk" for t in job.tasks))
        args = job.tasks[0].args
        self.assertIn("BRAY_HdKarma", args)
        self.assertTrue(args[-1].endswith("light_v002.usd"))
        self.assertIn("render/v001/light.$F4.exr", args[args.index("--output") + 1].replace("\\", "/"))
        self.assertEqual((info["frames"], info["backend"]), ([1001, 1012], "local"))
        self.assertFalse((usd.parent / "render").exists())     # the plan writes nothing

    def test_missing_range_and_renderer(self) -> None:
        with self.assertRaises(DispatchError):
            render_shot.plan(project="P", project_path=self.tmp, user="A", usd=str(self.tmp / "none.usd"), dry=True)
        with self.assertRaises(DispatchError):
            render_shot.plan(project="P", project_path=self.tmp, user="A", seq="SEQ010", shot="SH010",
                             renderer="arnold", dry=True)


if __name__ == "__main__":
    unittest.main()
