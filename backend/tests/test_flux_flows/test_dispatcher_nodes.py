# ADR 0067: the Dispatcher nodes in real flows, and ForEach in mode dispatch. Backend local
# with this Python declared as program "py" (temp pipe config); the tasks really run.

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from features.dispatcher import config, local_backend
from flux_flows.validate import validate
from tests.test_flux_flows import _flow_helpers as helpers
from tests.test_flux_flows._flow_helpers import flow


def setUpModule() -> None:  # noqa: N802 (unittest API)
    helpers.setUpModule()


def tearDownModule() -> None:  # noqa: N802 (unittest API)
    helpers.tearDownModule()


class DispatcherNodes(unittest.TestCase):
    def setUp(self) -> None:
        helpers.reset()
        local_backend.reset()
        self.tmp = Path(tempfile.mkdtemp())
        pipe = self.tmp / "dispatcher.json"
        pipe.write_text(json.dumps({"backend": "local", "programs": {"py": {"local": sys.executable}}}),
                        encoding="utf-8")
        self.patch = mock.patch.object(config, "pipe_path", return_value=pipe)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _submit_wait(self, code: str):
        return flow({"ev": ("event.manual", {}),
                     "sub": ("dispatcher.submit", {"program": "py", "args": ["-c", code], "title": "t"}),
                     "w": ("dispatcher.wait", {"every_s": 5, "timeout_s": 60}),
                     "rec": "action.t_record", "bad": "action.t_record"},
                    ["ev.then->sub.exec", "sub.then->w.exec", "sub.job_id->w.job_id", "w.then->rec.exec",
                     "w.state->rec.value", "w.on_error->bad.exec", "w.errors->bad.value"])

    def test_submit_then_wait(self) -> None:
        out = self.tmp / "done.txt"
        f = self._submit_wait(f"open(r'{out}', 'w').write('ok')")
        self.assertEqual([i for i in validate(f) if i.level == "error"], [])
        rec = helpers.run_flow(f)
        self.assertEqual(rec["status"], "ok", rec.get("error"))
        self.assertEqual(helpers.CALLS, [("rec", "done")])
        self.assertEqual(out.read_text(encoding="utf-8"), "ok")

    def test_failed_task_goes_to_on_error(self) -> None:
        rec = helpers.run_flow(self._submit_wait("import sys; sys.exit(1)"))
        self.assertEqual(helpers.CALLS, [("bad", None)])
        self.assertEqual(rec["nodes"]["w"]["state"], "error_handled")

    def test_undeclared_program_fails_on_the_node(self) -> None:
        f = flow({"ev": ("event.manual", {}), "sub": ("dispatcher.submit", {"program": "cmd", "args": ["/c", "dir"]})},
                 ["ev.then->sub.exec"])
        rec = helpers.run_flow(f)
        self.assertEqual(rec["status"], "error")
        self.assertIn("non autorise", rec["nodes"]["sub"]["error"])

    def test_dry_run_sends_nothing(self) -> None:
        rec = helpers.run_flow(self._submit_wait("print(1)"), mode="dry")
        self.assertEqual(rec["status"], "ok", rec.get("error"))
        self.assertEqual(local_backend._JOBS, {})
        self.assertTrue(any("enverrait" in (r.get("text_fr") or "") for r in rec["report"]))

    def test_foreach_dispatch_sends_one_job(self) -> None:
        out = self.tmp / "items"
        out.mkdir()
        f = flow({"ev": ("event.manual", {}),
                  "lst": ("data.value", {"type": "list", "value": ["a", "b", "c"]}),
                  "fe": ("operator.foreach_begin", {"mode": "dispatch"}),
                  "sub": ("dispatcher.submit", {"program": "py", "title": "batch",
                                                "args": ["-c", f"import uuid; open(r'{out}' + '/' + uuid.uuid4().hex, 'w')"]}),
                  "end": ("operator.foreach_end", {"begin": "fe"}),
                  "w": ("dispatcher.wait", {"every_s": 5, "timeout_s": 60}),
                  "rec": "action.t_record"},
                 ["ev.then->fe.exec", "lst.value->fe.list", "fe.loop->sub.exec", "sub.then->end.exec",
                  "end.done->w.exec", "end.job_id->w.job_id", "w.then->rec.exec", "w.total->rec.value"])
        self.assertEqual([i for i in validate(f) if i.level == "error"], [])
        rec = helpers.run_flow(f)
        self.assertEqual(rec["status"], "ok", rec.get("error"))
        self.assertEqual(helpers.CALLS, [("rec", 3)])
        self.assertEqual(len(local_backend._JOBS), 1)            # one job, three tasks
        self.assertEqual(len(list(out.iterdir())), 3)

    def test_foreach_dispatch_without_submit_sends_nothing(self) -> None:
        f = flow({"ev": ("event.manual", {}), "lst": ("data.value", {"type": "list", "value": [1, 2]}),
                  "fe": ("operator.foreach_begin", {"mode": "dispatch"}), "rec": "action.t_record",
                  "end": ("operator.foreach_end", {"begin": "fe"})},
                 ["ev.then->fe.exec", "lst.value->fe.list", "fe.loop->rec.exec", "rec.then->end.exec"])
        rec = helpers.run_flow(f)
        self.assertEqual(rec["status"], "ok", rec.get("error"))
        self.assertEqual(local_backend._JOBS, {})

    def test_instance_farm_mode_points_to_dispatcher(self) -> None:
        f = flow({"ev": ("event.manual", {}), "i": ("session.hou_instance", {"mode": "farm"})}, ["ev.then->i.exec"])
        issues = [i for i in validate(f) if i.node == "i" and i.port == "mode"]
        self.assertTrue(any("Dispatcher" in i.message_fr for i in issues))


if __name__ == "__main__":
    unittest.main()
