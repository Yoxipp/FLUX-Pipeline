# P2 (2026-10-22): run records (01 §6): id, atomic write, listing, retention, interrupted.

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from flux_flows import runs


def _record(folder: Path, n: int, mode: str = "real", status: str = "ok", flow: str = "daily") -> dict:
    rec = runs.new_record(run_id=f"20261022T1000{n:02d}_ADAM_abc{n:03d}", flow=flow, scope="team", project=None,
                          version=None, draft=True, mode=mode, trigger={"event": "n1"}, user="ADAM")
    rec["status"] = status
    runs.write_record(folder, rec)
    return rec


class Runs(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_runs_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_run_id_shape(self) -> None:
        self.assertRegex(runs.make_run_id("ADAM"), r"^\d{8}T\d{6}_ADAM_[0-9a-f]{6}$")
        self.assertTrue(re.match(r"^\d{8}T\d{6}_UNKNOWN_", runs.make_run_id(None)))

    def test_write_list_find(self) -> None:
        _record(self.tmp, 1)
        _record(self.tmp, 2, status="error")
        _record(self.tmp, 3, flow="other")
        listed = runs.list_runs([self.tmp])
        self.assertEqual([r["run_id"][-6:] for r in listed], ["abc003", "abc002", "abc001"])
        self.assertEqual(len(runs.list_runs([self.tmp], flow="daily")), 2)
        self.assertEqual(len(runs.list_runs([self.tmp], status="error")), 1)
        self.assertEqual(runs.find_run([None, self.tmp], listed[1]["run_id"])["status"], "error")
        self.assertIsNone(runs.find_run([self.tmp], "../x"))
        self.assertEqual(list(self.tmp.rglob(".flux_tmp_*")), [])

    def test_retention_keeps_real_and_dry_apart(self) -> None:
        for n in range(6):
            _record(self.tmp, n, mode="dry")
        for n in range(6, 10):
            _record(self.tmp, n)
        removed = runs.purge(self.tmp, "daily", keep_real=3, keep_dry=2)
        self.assertEqual(removed, 5)
        left = runs.list_runs([self.tmp], flow="daily")
        self.assertEqual(sorted(r["mode"] for r in left), ["dry", "dry", "real", "real", "real"])
        self.assertEqual(left[-1]["run_id"][-6:], "abc004")   # the newest dry runs stay

    def test_running_record_of_a_dead_backend_reads_interrupted(self) -> None:
        rec = _record(self.tmp, 1, status="running")
        path = runs.record_path(self.tmp, "daily", rec["run_id"])
        data = json.loads(path.read_text(encoding="utf-8"))
        data["pid"] = os.getpid() + 1
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(runs.find_run([self.tmp], rec["run_id"])["status"], "interrupted")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["status"], "interrupted")

    def test_logs_and_values_are_capped(self) -> None:
        entry: dict = {}
        for i in range(runs.MAX_LOGS_PER_NODE + 10):
            runs.add_log(entry, {"level": "info", "text": str(i)})
        self.assertEqual(len(entry["logs"]), runs.MAX_LOGS_PER_NODE + 1)
        self.assertLessEqual(len(runs.clip_value("x" * 5000)), runs.MAX_VALUE_BYTES)
        self.assertEqual(runs.preview({"a": 1}), '{"a": 1}')


if __name__ == "__main__":
    unittest.main()
