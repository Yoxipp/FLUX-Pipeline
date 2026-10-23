# Job menu of the Tractor Dashboard in FLUX: bridge calls, ownership guard, restore from the archive, trace.
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from unittest import mock

from features.render import tractor_bridge as tb

_SCRIPT = Path(__file__).resolve().parents[2] / "features" / "render" / "bridge" / "flux_tractor_bridge.py"


def _bridge_module():
    spec = importlib.util.spec_from_file_location("flux_tractor_bridge_menu", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeClient:
    QUEUE, CONTROL = "queue", "ctrl"

    def __init__(self):
        self.sent = []

    def _transaction(self, urltype, attrs, translation="JSON"):
        self.sent.append((urltype, attrs, translation))
        return "trace text" if urltype == self.CONTROL else None


class FakeTq:
    def __init__(self, live=(7,), archived=()):
        self.live, self.archived, self.calls = live, archived, []

    def jobs(self, clause, columns=(), limit=None, archive=False):
        jid = int(clause.split("=")[1])
        return [{"jid": jid}] if jid in (self.archived if archive else self.live) else []

    def __getattr__(self, name):
        def op(job, **kw):
            self.calls.append((name, job, kw))
        return op


class BridgeOps(unittest.TestCase):
    def setUp(self):
        self.bridge = _bridge_module()
        self.client = FakeClient()
        p = mock.patch.object(self.bridge, "_engine_client", return_value=self.client)
        p.start()
        self.addCleanup(p.stop)

    def run_op(self, name, tq, **req):
        with mock.patch.object(self.bridge, "_tq", return_value=tq):
            return self.bridge.VERBS[name]({"jid": 7, **req})

    def test_each_menu_entry_calls_the_dashboard_operation_on_one_job(self):
        expected = {"retry": "retryerrors", "skip_errors": "skiperrors", "restart": "restart", "archive": "delete",
                    "lock": "lock", "unlock": "unlock", "pause": "pause", "resume": "unpause"}
        for verb, call in expected.items():
            tq = FakeTq()
            self.assertEqual(self.run_op(verb, tq, user="adam"), {"jid": 7})
            self.assertEqual(tq.calls[0][:2], (call, [{"jid": 7}]), verb)   # exact list, never a search
        tq = FakeTq()
        self.run_op("lock", tq, user="adam")
        self.assertEqual(tq.calls[0][2], {"note": "FLUX adam"})

    def test_restore_looks_in_the_archive(self):
        tq = FakeTq(live=(), archived=(7,))
        self.run_op("restore", tq)
        self.assertEqual(tq.calls, [("undelete", [{"jid": 7}], {})])
        with self.assertRaises(ValueError):
            self.run_op("archive", FakeTq(live=()))     # unknown job: nothing sent

    def test_shuffle_and_trace_use_the_dashboard_requests(self):
        self.run_op("shuffle_top", FakeTq())
        self.assertEqual(self.client.sent[-1], ("queue", {"q": "jshuffle", "jid": "7"}, "JSON"))
        self.assertEqual(self.run_op("trace", FakeTq()), {"trace": "trace text"})
        self.assertEqual(self.client.sent[-1], ("ctrl", {"q": "tracer", "t": "J7", "fmt": "plain"}, None))


class BackendGuards(unittest.TestCase):
    def settings(self, **over):
        return {"dry_run": False, **over}

    def _calls(self, owner="adam"):
        calls = []

        def fake_call(verb, settings, user, **args):
            calls.append((verb, args))
            if verb == "jobs":
                return {"jobs": [{"jid": 7, "metadata": json.dumps({"user": owner})}]}
            return {"jid": args.get("jid")}
        return calls, fake_call

    def test_every_action_checks_the_owner_first(self):
        for verb in tb.JOB_ACTIONS:
            calls, fake = self._calls()
            with mock.patch.object(tb, "call", side_effect=fake):
                self.assertEqual(tb.job_action(verb, self.settings(), "adam", 7), {"jid": 7})
            self.assertEqual(calls[0], ("jobs", {"jid": 7, "archive": verb == "restore"}))
            self.assertEqual(calls[1][0], verb)

    def test_refused_on_other_jobs_unknown_verbs_and_dry_run(self):
        calls, fake = self._calls(owner="tom")
        with mock.patch.object(tb, "call", side_effect=fake):
            with self.assertRaises(tb.BridgeError):
                tb.job_action("archive", self.settings(), "adam", 7)
            with self.assertRaises(tb.BridgeError):
                tb.job_action("delete_everything", self.settings(), "adam", 7)
        self.assertEqual([c[0] for c in calls], ["jobs"])    # nothing written
        with self.assertRaises(tb.BridgeError):
            tb.job_action("restart", self.settings(dry_run=True), "adam", 7)

    def test_trace_is_a_read(self):
        with mock.patch.object(tb, "call", return_value={"trace": "x"}) as call:
            self.assertEqual(tb.trace(self.settings(), "tom", 7), {"trace": "x"})
        call.assert_called_once_with("trace", self.settings(), "tom", jid=7)


if __name__ == "__main__":
    unittest.main()
