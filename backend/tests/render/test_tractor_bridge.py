# Tractor bridge client: subprocess protocol, error mapping, dry run guards (ADR 0015).
from __future__ import annotations

import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from features.render import job_builder as jb
from features.render import tractor_bridge as tb

_OK_BRIDGE = textwrap.dedent("""
    import json, os, sys
    req = json.load(sys.stdin)
    verb = req["verb"]
    if verb == "spool":
        res = {"jid": 42, "output": "spooled " + req["alf_path"]}
    elif verb == "jobs":
        res = {"jobs": [
            {"jid": 7, "user": "3d1", "projects": ["team_a"], "numTasks": 4, "numDone": 4,
             "metadata": json.dumps({"user": "adam"}), "echo": req},
            {"jid": 8, "user": "3d1", "projects": ["FIE"], "numTasks": 6, "numError": 2,
             "metadata": "", "echo": req},
        ]}
    elif verb == "blades":
        res = {"blades": [{"name": "b1"}], "active_by_project": {"team_a": 2}}
    elif verb == "ping":
        res = {"version": "3.0", "pythonpath": os.environ.get("PYTHONPATH", ""),
               "has_home": "PYTHONHOME" in os.environ, "engine": req["engine"]}
    else:
        res = {"jid": req["jid"]}
    print(json.dumps({"ok": True, "result": res}))
""")
_GARBAGE_BRIDGE = "import sys\nsys.stderr.write('Traceback boom')\nprint('not json')\n"
_SLEEP_BRIDGE = "import time\ntime.sleep(20)\n"
_FAIL_BRIDGE = "import json\nprint(json.dumps({'ok': False, 'error': 'no such job'}))\n"


def _spec(**over):
    base = dict(
        title="PROJ sh010 v003",
        project="team_a",
        user="adam",
        usd_path="//srv/flux/PROJ/shot/SQ01/SH010/usd/SQ01_SH010_v003.usda",
        output_pattern="//srv/flux/PROJ/shot/SQ01/SH010/render/v003/SQ01_SH010.$F4.exr",
        frame_start=1001,
        frame_end=1012,
        chunk_size=5,
    )
    base.update(over)
    return jb.RenderJobSpec(**base)


class BridgeTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def settings(self, source=_OK_BRIDGE, **over):
        script = self.tmp / "bridge.py"
        script.write_text(source, encoding="utf-8")
        base = {"bridge_python": sys.executable, "bridge_script": str(script),
                "engine": "tractor:5600", "dry_run": False}
        base.update(over)
        return base


class CallTests(BridgeTestCase):
    def test_not_configured(self):
        for over in ({"bridge_python": ""}, {"bridge_script": ""}, {"bridge_script": str(self.tmp / "nope.py")}):
            with self.assertRaises(tb.BridgeError) as ctx:
                tb.call("ping", self.settings(**over), "adam")
            self.assertIn("non configure", str(ctx.exception))

    def test_ping_ok_and_engine_passed(self):
        res = tb.call("ping", self.settings(), "adam")
        self.assertEqual(res["version"], "3.0")
        self.assertEqual(res["engine"], "tractor:5600")

    def test_garbage_output(self):
        with self.assertRaises(tb.BridgeError) as ctx:
            tb.call("ping", self.settings(_GARBAGE_BRIDGE), "adam")
        self.assertIn("illisible", str(ctx.exception))
        self.assertIn("Traceback boom", str(ctx.exception))

    def test_timeout(self):
        with self.assertRaises(tb.BridgeError) as ctx:
            tb.call("ping", self.settings(_SLEEP_BRIDGE), "adam", timeout=1)
        self.assertIn("delai depasse (1 s)", str(ctx.exception))

    def test_ok_false(self):
        with self.assertRaises(tb.BridgeError) as ctx:
            tb.call("ping", self.settings(_FAIL_BRIDGE), "adam")
        self.assertEqual(str(ctx.exception), "Tractor : no such job")

    def test_bad_verb(self):
        with self.assertRaises(tb.BridgeError):
            tb.call("format_disk", self.settings(), "adam")

    def test_bad_jid(self):
        for verb in ("kill", "retry", "pause", "resume"):
            for jid in ("12", None, True, 1.5):
                with self.assertRaises(tb.BridgeError):
                    tb.call(verb, self.settings(), "adam", jid=jid)
        with self.assertRaises(tb.BridgeError):
            tb.call("kill", self.settings(), "adam")

    def test_spool_requires_alf_path(self):
        with self.assertRaises(tb.BridgeError):
            tb.call("spool", self.settings(), "adam")

    def test_env_cleaned(self):
        env = {"PYTHONPATH": "C:/py3/lib", "PYTHONHOME": "C:/py3", "PYTHONUSERBASE": "C:/ub"}
        with mock.patch.dict(os.environ, env):
            res = tb.call("ping", self.settings(), "adam")
            self.assertEqual(os.environ["PYTHONPATH"], "C:/py3/lib")  # parent env untouched
        self.assertEqual(res["pythonpath"], "")
        self.assertFalse(res["has_home"])


class SpoolTests(BridgeTestCase):
    def test_dry_run_writes_files_without_bridge(self):
        out = self.tmp / "render"
        with mock.patch.object(tb.subprocess, "run") as run:
            res = tb.spool(_spec(), self.settings(dry_run=True), "adam", out)
        run.assert_not_called()
        self.assertTrue(res["dry_run"])
        self.assertIsNone(res["jid"])
        self.assertTrue(Path(res["files"]["alf"]).is_file())
        self.assertTrue(Path(res["files"]["json"]).is_file())

    def test_real_spool_returns_jid(self):
        res = tb.spool(_spec(), self.settings(), "adam", self.tmp / "render")
        self.assertFalse(res["dry_run"])
        self.assertEqual(res["jid"], 42)
        self.assertIn(res["files"]["alf"], res["output"])
        self.assertTrue(Path(res["files"]["alf"]).is_file())

    def test_invalid_spec_raises_validation_error(self):
        with self.assertRaises(jb.JobValidationError):
            tb.spool(_spec(output_pattern="C:/r/a.$F4.exr"), self.settings(), "adam", self.tmp / "r")


class QueryAndActionTests(BridgeTestCase):
    def test_jobs_and_blades_dry_run(self):
        s = self.settings(dry_run=True, bridge_python="")
        self.assertEqual(tb.jobs(s, "adam"), {"jobs": [], "dry_run": True})
        self.assertEqual(tb.blades(s, "adam"),
                         {"blades": [], "active_by_project": {}, "dry_run": True})

    def test_jobs_lists_every_state_and_owner(self):
        out = tb.jobs(self.settings(), "adam", project="team_a", days=14)
        self.assertEqual([(j["jid"], j["state"], j["flux_user"]) for j in out["jobs"]],
                         [(7, "done", "adam"), (8, "error", "")])
        echo = out["jobs"][0]["echo"]
        self.assertEqual((echo["login"], echo["user"]), ("root", "adam"))  # login is not the owner
        self.assertEqual((echo["days"], echo["project"], echo.get("owner")), (14, "team_a", None))
        self.assertEqual(out["jobs"][0]["metadata"], {"user": "adam"})

    def test_jobs_mine_uses_flux_metadata(self):
        # Every school job is owned by the shared Windows login, so "mine" reads the metadata.
        self.assertEqual([j["jid"] for j in tb.jobs(self.settings(), "adam", mine=True)["jobs"]], [7])

    def test_reads_hit_engine_in_dry_run_when_configured(self):
        out = tb.jobs(self.settings(dry_run=True), "adam")
        self.assertEqual((len(out["jobs"]), out["dry_run"]), (2, True))
        self.assertEqual(tb.tasks(self.settings(dry_run=True), "adam", 7), {"jid": 7})

    def test_engine_login_setting(self):
        out = tb.jobs(self.settings(engine_user="farm"), "adam")
        self.assertEqual(out["jobs"][0]["echo"]["login"], "farm")

    def test_job_state(self):
        cases = [({"deletetime": "x", "numActive": 1}, "deleted"), ({"pausetime": "x"}, "paused"),
                 ({"numActive": 2, "numError": 1}, "active"), ({"numError": 1}, "error"),
                 ({"numTasks": 3, "numDone": 3}, "done"), ({"numTasks": 3, "numDone": 1}, "waiting")]
        for job, state in cases:
            self.assertEqual(tb.job_state(job), state, job)

    def test_task_log_needs_tid(self):
        with self.assertRaises(tb.BridgeError):
            tb.task_log(self.settings(), "adam", 7, "4")
        self.assertEqual(tb.task_log(self.settings(), "adam", 7, 4), {"jid": 7})

    def test_blades_real(self):
        self.assertEqual(tb.blades(self.settings(), "adam")["active_by_project"], {"team_a": 2})

    def test_actions_refused_in_dry_run(self):
        s = self.settings(dry_run=True)
        for fn in (tb.kill, tb.retry, tb.pause, tb.resume):
            with self.assertRaises(tb.BridgeError) as ctx:
                fn(s, "adam", 7)
            self.assertIn("Mode simulation", str(ctx.exception))

    def test_actions_real(self):
        for fn in (tb.kill, tb.retry, tb.pause, tb.resume):
            self.assertEqual(fn(self.settings(), "adam", 7), {"jid": 7})

    def test_actions_refused_on_other_jobs(self):
        # FLUX logs in as root: it must not touch jobs another user (or Nuke, Maya) spooled.
        for user in ("tom", ""):
            with self.assertRaises(tb.BridgeError) as ctx:
                tb.kill(self.settings(), user or "nobody", 7)
            self.assertIn("pas ete lance par vous", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
