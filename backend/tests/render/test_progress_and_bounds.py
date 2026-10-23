# Render progress (husk -Va1 -> Tractor task progress) and chunk bounds (-maxrunsecs / -retryrc).
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from features.render import job_builder, team_settings, tractor_bridge

_SCRIPT = Path(__file__).resolve().parents[2] / "features" / "render" / "bridge" / "flux_tractor_bridge.py"


def _bridge_module():
    spec = importlib.util.spec_from_file_location("flux_tractor_bridge_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeTq:
    def __init__(self, tasks):
        self._tasks = tasks
        self.clauses = []

    def tasks(self, clause, columns=()):
        self.clauses.append(clause)
        return self._tasks


def _spec(**kw) -> job_builder.RenderJobSpec:
    base = dict(title="P SH v001", project="P", user="adam", usd_path="//srv/p/SH.usda",
                output_pattern="//srv/p/render/v001/SH.$F4.exr", frame_start=1, frame_end=10, chunk_size=5)
    base.update(kw)
    return job_builder.RenderJobSpec(**base)


class Progress(unittest.TestCase):
    def test_husk_prints_alfred_progress(self):
        self.assertIn("-Va1", job_builder.husk_command(_spec(), 1, 5))

    def test_active_progress_sums_running_tasks_only(self):
        bridge = _bridge_module()
        tq = FakeTq([{"jid": 7, "progress": 40.0}, {"jid": 7, "progress": 250}, {"jid": 9, "progress": None},
                     {"jid": 9, "progress": "x"}])
        self.assertEqual(bridge._active_progress(tq, [7, 9, None, 7]), {7: 140.0, 9: 0.0})
        self.assertEqual(tq.clauses, ["jid in [7,9] and state=active"])
        idle = FakeTq([])
        self.assertEqual(bridge._active_progress(idle, []), {})
        self.assertEqual(idle.clauses, [])  # no query when nothing runs

    def test_job_percent(self):
        cases = [({"numTasks": 4, "numDone": 1, "activeProgress": 150}, 62),
                 ({"numTasks": 4, "numDone": 4}, 100), ({"numTasks": 0}, 0),
                 ({"numTasks": 2, "numDone": 1, "activeProgress": 999}, 100),
                 ({"numTasks": 3, "numDone": 0, "activeProgress": "bad"}, 0)]
        for job, pct in cases:
            self.assertEqual(tractor_bridge.job_percent(job), pct, job)
        self.assertEqual(tractor_bridge._normalize({"numTasks": 2, "numDone": 1, "activeProgress": 50})["percent"], 75)


class ChunkBounds(unittest.TestCase):
    def test_render_commands_get_the_bounds(self):
        alf = job_builder.to_alf(_spec(max_task_minutes=90, retry_exit_codes=[3, -1073741819],
                                       freeze_source="//srv/p/SH_src.usda", freeze_script="//srv/x.py",
                                       freeze_python="C:/rmanpy.exe", freeze_houdini="C:/H"))
        husk_lines = [l for l in alf.splitlines() if "husk" in l]
        self.assertEqual(len(husk_lines), 2)
        for line in husk_lines:
            self.assertTrue(line.endswith("-maxrunsecs 5400 -retryrc {-1073741819 3}") or
                            line.endswith("-maxrunsecs 5400 -retryrc {3 -1073741819}"), line)
        freeze_line = next(l for l in alf.splitlines() if "x.py" in l)
        self.assertNotIn("maxrunsecs", freeze_line)
        self.assertNotIn("retryrc", freeze_line)

    def test_no_bounds_by_default(self):
        alf = job_builder.to_alf(_spec())
        self.assertNotIn("maxrunsecs", alf)
        self.assertNotIn("retryrc", alf)

    def test_bad_bounds_are_refused(self):
        for kw in ({"max_task_minutes": -1}, {"retry_exit_codes": [0]}, {"retry_exit_codes": [True]}):
            with self.assertRaises(job_builder.JobValidationError, msg=kw):
                job_builder.to_alf(_spec(**kw))

    def test_team_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "render.json"
            s = team_settings.read_settings("P", path)
            self.assertEqual((s["max_task_minutes"], s["retry_exit_codes"]), (0, []))
            s = team_settings.write_settings("P", {"max_task_minutes": 120, "retry_exit_codes": [5, 3, 5]}, path)
            self.assertEqual((s["max_task_minutes"], s["retry_exit_codes"]), (120, [3, 5]))
            for bad in ({"max_task_minutes": -5}, {"retry_exit_codes": [0]}, {"retry_exit_codes": "3"}):
                with self.assertRaises(ValueError, msg=bad):
                    team_settings.write_settings("P", bad, path)


if __name__ == "__main__":
    unittest.main()
