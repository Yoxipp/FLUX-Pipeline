# Exit codes of failed FLUX renders: recorded once per execution (husk only), proposed for retry.
from __future__ import annotations

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from features.render import exit_codes, tractor_bridge

_SCRIPT = Path(__file__).resolve().parents[2] / "features" / "render" / "bridge" / "flux_tractor_bridge.py"


def _job(jid, errors, flux="P", team="P", title="P SH v001"):
    return {"jid": jid, "numError": errors, "projects": [team], "title": title,
            "metadata": {"flux_project": flux} if flux else {}}


def _inv(jid, rcode, program="husk.exe", cid=1, stop="2026-10-23 13:00:00"):
    return {"jid": jid, "tid": 1, "cid": cid, "rcode": rcode, "stoptime": stop, "program": program}


class Store(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = self.tmp / "render_exit_codes.json"

    def test_only_team_flux_jobs_with_new_errors(self):
        jobs = [_job(1, 2), _job(2, 0), _job(3, 1, flux="OTHER"), _job(4, 1, team="NUKE_TEAM"), _job(5, 1, flux="")]
        self.assertEqual([j["jid"] for j in exit_codes.jobs_to_check("P", jobs, "P", self.path)], [1])
        exit_codes.record("P", [jobs[0]], [], self.path)
        self.assertEqual(exit_codes.jobs_to_check("P", jobs, "P", self.path), [])   # same error count
        jobs[0]["numError"] = 3
        self.assertEqual([j["jid"] for j in exit_codes.jobs_to_check("P", jobs, "P", self.path)], [1])

    def test_each_execution_counted_once_husk_only(self):
        job = _job(7, 2)
        invs = [_inv(7, 3), _inv(7, 3, cid=2), _inv(7, 1, program="flux_freeze_at_start.py"),
                _inv(7, 211, program="rmanpy.exe"), _inv(7, 10111, program="C:/Houdini/bin/husk.exe", cid=3)]
        self.assertEqual(exit_codes.record("P", [job], invs, self.path), 3)
        self.assertEqual(exit_codes.record("P", [job], invs, self.path), 0)   # polled again: nothing new
        codes = {s["code"]: s for s in exit_codes.suggestions("P", [], self.path)}
        self.assertEqual(sorted(codes), [3, 10111])
        self.assertEqual(codes[3]["count"], 2)
        self.assertEqual(codes[3]["last_title"], "P SH v001")
        self.assertTrue(codes[3]["proposed"])
        self.assertFalse(codes[10111]["proposed"])           # a timeout kill is never proposed
        self.assertIn("duree max", codes[10111]["label"])

    def test_active_codes_are_not_proposed_again(self):
        exit_codes.record("P", [_job(7, 1)], [_inv(7, 3)], self.path)
        (s,) = exit_codes.suggestions("P", [3], self.path)
        self.assertTrue(s["active"])
        self.assertFalse(s["proposed"])

    def test_bad_store_reads_empty(self):
        self.path.write_text("not json", encoding="utf-8")
        self.assertEqual(exit_codes.suggestions("P", [], self.path), [])


class BridgeVerb(unittest.TestCase):
    def test_exit_codes_reads_programs_and_codes(self):
        spec = importlib.util.spec_from_file_location("flux_tractor_bridge_codes", _SCRIPT)
        bridge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bridge)

        class FakeTq:
            def __init__(self):
                self.clauses = []

            def commands(self, clause, columns=()):
                self.clauses.append(clause)
                return [{"jid": 9, "cid": 1, "argv": ["C:\\Houdini 20.5\\bin\\husk.exe", "-Va1"]},
                        {"jid": 9, "cid": 2, "argv": []}]

            def invocations(self, clause, columns=()):
                self.clauses.append(clause)
                return [{"jid": 9, "tid": 1, "cid": 1, "rcode": 3, "stoptime": "t"},
                        {"jid": 9, "tid": 2, "cid": 2, "rcode": None}]

        fake = FakeTq()
        with mock.patch.object(bridge, "_tq", return_value=fake):
            out = bridge._exit_codes({"jids": [9, 9]})
        self.assertEqual(out, {"invocations": [
            {"jid": 9, "tid": 1, "cid": 1, "rcode": 3, "stoptime": "t", "program": "husk.exe"}]})
        self.assertEqual(fake.clauses, ["jid in [9]", "jid in [9] and rcode != 0"])
        self.assertEqual(bridge._exit_codes({"jids": []}), {"invocations": []})

    def test_backend_side_needs_jids_and_configured_reads(self):
        self.assertEqual(tractor_bridge.exit_codes({"dry_run": True}, "adam", [1]), [])
        self.assertEqual(tractor_bridge.exit_codes({}, "adam", ["x"]), [])


class RouterHook(unittest.TestCase):
    def setUp(self):
        from routers import render

        self.render = render
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = self.tmp / "render_exit_codes.json"
        render._codes_at.clear()
        self.addCleanup(render._codes_at.clear)
        p = mock.patch.object(exit_codes, "store_path", return_value=self.store)
        p.start()
        self.addCleanup(p.stop)

    def test_poll_records_new_errors_once_a_minute(self):
        settings = {"tractor_project": "P"}
        with mock.patch.object(tractor_bridge, "exit_codes", return_value=[_inv(7, 3)]) as read:
            self.render._record_exit_codes("P", settings, "adam", [_job(7, 1)])
            self.render._record_exit_codes("P", settings, "adam", [_job(7, 2)])   # within the minute
        self.assertEqual(read.call_count, 1)
        self.assertEqual([s["code"] for s in exit_codes.suggestions("P", [])], [3])

    def test_a_bridge_failure_never_breaks_the_poll(self):
        with mock.patch.object(tractor_bridge, "exit_codes", side_effect=tractor_bridge.BridgeError("down")):
            self.render._record_exit_codes("P", {"tractor_project": "P"}, "adam", [_job(7, 1)])


if __name__ == "__main__":
    unittest.main()
