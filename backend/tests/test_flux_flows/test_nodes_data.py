# P3 (2026-10-23): data nodes (02_NODES §3): python_value (read by ast, never run),
# json_value key paths, path, context called directly with a fake ctx; template
# through the engine (it uses the run's resolver).

from __future__ import annotations

import asyncio
import inspect
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from flux_flows.nodes import registry
from flux_flows.nodes.contract import NodeError
from tests.test_flux_flows import _flow_helpers as h
from tests.test_flux_flows._flow_helpers import flow, run_flow, setUpModule, tearDownModule  # noqa: F401


def call(ctx, node_type, inputs=None, params=None):
    res = registry.get_node(node_type).func(ctx, dict(inputs or {}), dict(params or {}))
    return asyncio.run(res) if inspect.isawaitable(res) else res


class _Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="flux_data_")).resolve()
        self.project = self.root / "DOSSIER_PROJETS" / "DEMO"
        self.project.mkdir(parents=True)
        self.patch = mock.patch("core.paths.get_flux_root", return_value=self.root)
        self.patch.start()
        self.logs = []
        self.ctx = SimpleNamespace(context={"project": "DEMO", "project_path": str(self.project), "user": "ADAM"},
                                   log=lambda text, level="info": self.logs.append((level, text)))

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.root, ignore_errors=True)


class PythonValue(_Base):
    def _module(self, text):
        path = self.root / "CONFIG" / "values.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_reads_literal_without_running_the_module(self):
        marker = self.root / "side_effect.txt"
        self._module(f"import os\nopen({str(marker)!r}, 'w').write('ran')\nos.makedirs({str(self.root / 'made')!r})\n"
                     "SOFTS = ['maya', 'houdini']\nPORT: int = 8765\nSOFTS = ['maya']\n")
        out = call(self.ctx, "data.python_value", params={"file": "$FLUX/CONFIG/values.py", "name": "SOFTS"})
        self.assertEqual(out, {"value": ["maya"]})      # last assignment wins
        self.assertEqual(call(self.ctx, "data.python_value",
                              params={"file": "$FLUX/CONFIG/values.py", "name": "PORT"})["value"], 8765)
        self.assertFalse(marker.exists())
        self.assertFalse((self.root / "made").exists())

    def test_errors(self):
        path = self._module("X = compute()\ndef f():\n    Y = 1\n")
        with self.assertRaisesRegex(NodeError, "jamais execute"):
            call(self.ctx, "data.python_value", params={"file": str(path), "name": "X"})
        with self.assertRaisesRegex(NodeError, "n'est pas defini"):
            call(self.ctx, "data.python_value", params={"file": str(path), "name": "Y"})   # not top level
        with self.assertRaises(NodeError) as err:
            call(self.ctx, "data.python_value", params={"file": str(path), "name": "not-a-name"})
        self.assertEqual(err.exception.code, "E_PARAM_INVALID")
        self._module("X = (\n")
        with self.assertRaisesRegex(NodeError, "illisible"):
            call(self.ctx, "data.python_value", params={"file": str(path), "name": "X"})
        with self.assertRaisesRegex(NodeError, "illisible"):
            call(self.ctx, "data.python_value", params={"file": str(self.root / "missing.py"), "name": "X"})


class JsonValue(_Base):
    DATA = {"a": {"b": [{"c": "v002"}, {"c": "v003"}]}, "shots": []}

    def get(self, key, **params):
        return call(self.ctx, "data.json_value", {"json": self.DATA}, {"key": key, **params})

    def test_key_paths(self):
        self.assertEqual(self.get("a.b[0].c"), {"value": "v002", "found": True})
        self.assertEqual(self.get("a.b[-1].c")["value"], "v003")
        self.assertEqual(self.get("a.b")["value"], self.DATA["a"]["b"])

    def test_missing_key_gives_default(self):
        self.assertEqual(self.get("a.b[5].c", default="none"), {"value": "none", "found": False})
        self.assertEqual(self.get("a.x"), {"value": None, "found": False})
        self.assertEqual(self.get("shots[0]", default=0), {"value": 0, "found": False})
        self.assertFalse(self.get("a[0]")["found"])      # index on a dict

    def test_invalid_key(self):
        for key in ("a..b", "a[x]", "a.b[0]c]"):
            with self.assertRaises(NodeError, msg=key) as err:
                self.get(key)
            self.assertEqual(err.exception.code, "E_PARAM_INVALID")

    def test_reads_the_file_when_json_is_not_linked(self):
        (self.project / "settings.json").write_text(json.dumps(self.DATA), encoding="utf-8")
        out = call(self.ctx, "data.json_value", params={"file": "settings.json", "key": "a.b[1].c"})
        self.assertEqual(out["value"], "v003")
        with self.assertRaisesRegex(NodeError, "json"):
            call(self.ctx, "data.json_value", params={"key": "a"})
        (self.project / "bad.json").write_text("{", encoding="utf-8")
        with self.assertRaisesRegex(NodeError, "JSON illisible"):
            call(self.ctx, "data.json_value", params={"file": "bad.json", "key": "a"})


class PathNode(_Base):
    def test_flux_and_relative(self):
        (self.root / "DAILY").mkdir()
        out = call(self.ctx, "data.path", params={"value": "$FLUX/DAILY"})
        self.assertEqual(out, {"path": f"{self.root.as_posix()}/DAILY", "dir": f"{self.root.as_posix()}/DAILY"})
        out = call(self.ctx, "data.path", params={"value": "IN/a.abc"})
        self.assertEqual(out, {"path": f"{self.project.as_posix()}/IN/a.abc", "dir": ""})   # not a folder
        self.assertEqual(self.logs, [])

    def test_absolute_mode_and_outside_warning(self):
        with self.assertRaisesRegex(NodeError, "absolu"):
            call(self.ctx, "data.path", params={"value": "IN", "relative_to": "absolute"})
        other = Path(tempfile.mkdtemp(prefix="flux_out_")).resolve()
        try:
            out = call(self.ctx, "data.path", params={"value": str(other), "relative_to": "absolute"})
            self.assertEqual(out["dir"], other.as_posix())
            self.assertTrue(any(level == "warn" and "W_ABSOLUTE_PATH" in text for level, text in self.logs))
        finally:
            shutil.rmtree(other, ignore_errors=True)

    def test_no_project_for_a_relative_path(self):
        self.ctx.context = {}
        with self.assertRaisesRegex(NodeError, "sans projet"):
            call(self.ctx, "data.path", params={"value": "IN"})


class Context(unittest.TestCase):
    def test_outputs_with_missing_keys_empty(self):
        ctx = SimpleNamespace(context={"project": "DEMO", "user": "ADAM", "shot": "sh010", "asset": None})
        out = call(ctx, "data.context")
        self.assertEqual((out["project"], out["user"], out["shot"], out["asset"], out["seq"]),
                         ("DEMO", "ADAM", "sh010", "", ""))
        self.assertEqual(set(out), {"project", "project_path", "asset", "seq", "shot", "user", "date", "time",
                                    "flow"})

    def test_in_a_run(self):
        h.reset()
        f = flow({"n1": "event.manual", "c": "data.context", "a": "action.t_record", "b": "action.t_record"},
                 ["n1.then->a.exec", "a.then->b.exec", "c.user->a.value", "c.flow->b.value"], name="ctx_flow")
        self.assertEqual(run_flow(f)["status"], "ok")
        self.assertEqual(h.CALLS, [("a", "ADAM"), ("b", "ctx_flow")])


class Template(unittest.TestCase):
    def setUp(self):
        h.reset()

    def _run(self, text):
        f = flow({"n1": "event.manual", "v": ("data.value", {"type": "dict", "value": {"soft": "maya"}}),
                  "t": ("data.template", {"text": text}), "a": "action.t_record"},
                 ["n1.then->a.exec", "v.value->t.values", "t.text->a.value"],
                 variables=[{"name": "take", "type": "str", "default": "t01"}])
        return run_flow(f)

    def test_tokens_values_and_variables(self):
        rec = self._run("DAILY_{date:%Y%m%d}_{soft}_${take}_{user}")
        self.assertEqual(rec["status"], "ok")
        self.assertRegex(h.CALLS[0][1], r"^DAILY_\d{8}_maya_t01_ADAM$")

    def test_flux_head(self):
        root = Path(tempfile.mkdtemp(prefix="flux_tpl_")).resolve()
        try:
            with mock.patch("core.paths.get_flux_root", return_value=root):
                rec = self._run("$FLUX/DAILY/{soft}")
            self.assertEqual(rec["status"], "ok")
            self.assertEqual(str(h.CALLS[0][1]).replace("\\", "/"), f"{root.as_posix()}/DAILY/maya")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_unknown_key_fails(self):
        rec = self._run("{nope}")
        self.assertEqual(rec["status"], "error")
        self.assertTrue(re.search("nope", json.dumps(rec, default=str)))


if __name__ == "__main__":
    unittest.main()
