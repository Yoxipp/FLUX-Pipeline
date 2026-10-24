# P6b step 9 (2026-10-24): "bridge+" verbs of Mari, ZBrush, Designer and Marvelous (the
# bridge_verb_nodes factory) against fake bridges, and each real bridge script against a fake
# module of its soft. They prove the protocol, not the softs: the soft API calls stay "to
# validate live". Painter: test_painter_bridge_plus.py.

from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from tests.test_flux_flows import _flow_helpers as h
from tests.test_flux_flows._fake_bridges import FakeTcpJson
from tests.test_flux_flows.test_nodes_softs import run_node

setUpModule = h.setUpModule        # noqa: N816
tearDownModule = h.tearDownModule  # noqa: N816

# soft -> (prefix, save_as extension, import kind or None, has run)
TCP_SOFTS = {"mari": ("mari", ".mra", "version", True)}


def _handler(requests):
    def handler(req):
        requests.append(req)
        action = req.get("action")
        if action == "ping":
            return {"status": "ok", "version": "test"}
        if action in ("open", "save", "save_as"):
            return {"status": "ok", "project": req.get("path") or "chair"}
        if action == "import":
            return {"status": "ok"}
        if action == "run":
            from dcc.bridge_secret import get_secret

            if req.get("secret") != get_secret():
                return {"ok": False, "status": "error", "error": "secret du bridge refuse"}
            return {"ok": True, "status": "ok", "result": 7, "trace": ""}
        return {"status": "error", "msg": f"unknown action: {action}"}
    return handler


class Nodes(unittest.TestCase):
    def setUp(self) -> None:
        h.reset()
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_bridge_plus_"))
        self._env = mock.patch.dict(os.environ, {"FLUX_BRIDGE_SECRET_FILE": str(self.tmp / "secret.txt")})
        self._env.start()
        self.requests = []
        self.srv = FakeTcpJson(_handler(self.requests)).start()

    def tearDown(self) -> None:
        self.srv.close()
        self._env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _last(self, action):
        return [r for r in self.requests if r.get("action") == action][-1]

    def test_open_save_save_as_import_run(self) -> None:
        for soft, (prefix, ext, kind, has_run) in TCP_SOFTS.items():
            with self.subTest(soft=soft):
                mesh = self.tmp / "chair.obj"
                mesh.write_text("x", encoding="utf-8")
                rec, _ = run_node(soft, f"dcc.{prefix}_open_scene", self.srv.port, {"discard_changes": True},
                                  {"mesh": str(mesh)})
                self.assertEqual(rec["status"], "ok", rec.get("error"))
                self.assertEqual((Path(self._last("open")["mesh"]), self._last("open")["discard"]), (mesh, True))
                rec, _ = run_node(soft, f"dcc.{prefix}_save_scene", self.srv.port)
                self.assertEqual(rec["status"], "ok", rec.get("error"))
                target = self.tmp / f"chair{ext}"
                rec, value = run_node(soft, f"dcc.{prefix}_save_as", self.srv.port, {"increment": True},
                                      {"path": str(target)}, "path")
                self.assertEqual(rec["status"], "ok", rec.get("error"))
                self.assertTrue(Path(value).name.startswith("chair_v"), value)
                rec, _ = run_node(soft, f"dcc.{prefix}_save_as", self.srv.port, inputs={"path": str(self.tmp / "x.bad")})
                self.assertEqual(rec["status"], "error")
                if kind:
                    rec, _ = run_node(soft, f"dcc.{prefix}_import", self.srv.port, {"kind": kind}, {"path": str(mesh)})
                    self.assertEqual(rec["status"], "ok", rec.get("error"))
                    self.assertEqual(self._last("import")["kind"], kind)
                if has_run:
                    rec, value = run_node(soft, f"dcc.{prefix}_run_script", self.srv.port, inputs={"code": "result = 7"},
                                          out="result")
                    self.assertEqual((rec["status"], value), ("ok", 7), rec.get("error"))

    def test_mari_opens_a_project_by_name(self) -> None:
        rec, _ = run_node("mari", "dcc.mari_open_scene", self.srv.port, inputs={"path": "chair_tex"})
        self.assertEqual(rec["status"], "ok", rec.get("error"))
        self.assertEqual(self._last("open")["path"], "chair_tex")


class _FakeModules(unittest.TestCase):
    MODULE = ""

    def load(self, modules: dict):
        self._mods = mock.patch.dict(sys.modules, modules)
        self._mods.start()
        sys.modules.pop(self.MODULE, None)
        self.bridge = importlib.import_module(self.MODULE)
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_bridge_script_"))

    def tearDown(self) -> None:
        self._mods.stop()
        sys.modules.pop(self.MODULE, None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def check_run(self, namespace_probe: str, expected) -> None:
        d = self.bridge._dispatch
        with mock.patch.object(self.bridge, "_secret", return_value=""):
            self.assertFalse(d({"action": "run", "code": "result = 1", "secret": ""})["ok"])
        with mock.patch.object(self.bridge, "_secret", return_value="s3cret"):
            self.assertFalse(d({"action": "run", "code": "result = 1", "secret": "bad"})["ok"])
            resp = d({"action": "run", "code": f"result = {namespace_probe}", "secret": "s3cret"})
            self.assertEqual((resp["ok"], resp["result"]), (True, expected))
            resp = d({"action": "run", "code": "raise ValueError('boom')", "secret": "s3cret"})
            self.assertEqual((resp["ok"], resp["error"]), (False, "boom"))


class MariScript(_FakeModules):
    MODULE = "dcc.mari.mari_bridge"

    def setUp(self) -> None:
        calls = self.calls = []
        state = self.state = {"open": True, "modified": True}

        class Proj:
            def name(self):
                return "chair_tex"

            def uuid(self):
                return "u1"

            def isModified(self):  # noqa: N802 - Mari API
                return state["modified"]

            def save(self, force_save=False):
                calls.append(("save", force_save))

        class Geo:
            def addVersion(self, path, name):  # noqa: N802 - Mari API
                calls.append(("addVersion", path, name))

        projects = types.SimpleNamespace(
            current=lambda: Proj() if state["open"] else None,
            close=lambda: (calls.append(("close",)), state.update(open=False)),
            open=lambda key: (calls.append(("open", key)), state.update(open=True)),
            create=lambda name, mesh, a, b: (calls.append(("create", name, mesh)), state.update(open=True)),
            extract=lambda path: (calls.append(("extract", path)), types.SimpleNamespace(uuid=lambda: "u2"))[1],
            archive=lambda name, path: calls.append(("archive", name, path)))
        mari = types.ModuleType("mari")
        mari.projects = projects
        mari.geo = types.SimpleNamespace(current=lambda: Geo(), load=lambda p: calls.append(("geo.load", p)))
        mari.images = types.SimpleNamespace(load=lambda p: calls.append(("images.load", p)))
        mari.app = types.SimpleNamespace(version=lambda: types.SimpleNamespace(string=lambda: "test"))
        # The script starts its server on import inside Mari: the "already started" guard skips it.
        import builtins

        self._started = mock.patch.object(builtins, "_flux_mari_bridge_started", True, create=True)
        self._started.start()
        self.addCleanup(self._started.stop)
        self.load({"mari": mari})

    def test_open_refuses_unsaved_changes_and_handles_mra_and_mesh(self) -> None:
        d = self.bridge._dispatch
        self.assertEqual(d({"action": "open", "path": "other"})["status"], "error")
        self.assertEqual(self.calls, [])
        self.assertEqual(d({"action": "open", "path": "C:/p/a.mra", "discard": True})["status"], "ok")
        self.assertEqual(self.calls, [("close",), ("extract", "C:/p/a.mra"), ("open", "u2")])
        self.calls.clear()
        self.state["modified"] = False
        self.assertEqual(d({"action": "open", "mesh": "C:/p/chair.obj"})["status"], "ok")
        self.assertEqual(self.calls, [("close",), ("create", "chair", "C:/p/chair.obj")])

    def test_save_as_archives_then_reopens(self) -> None:
        d = self.bridge._dispatch
        self.assertEqual(d({"action": "save_as", "path": "C:/p/a.spp"})["status"], "error")
        target = str(self.tmp / "a.mra")
        self.assertEqual(d({"action": "save_as", "path": target})["status"], "ok")
        self.assertEqual(self.calls, [("save", True), ("close",), ("archive", "chair_tex", target), ("open", "u1")])

    def test_imports(self) -> None:
        d = self.bridge._dispatch
        for kind, call in (("image", "images.load"), ("object", "geo.load"), ("version", "addVersion")):
            self.assertEqual(d({"action": "import", "kind": kind, "path": "C:/p/chair_v2.obj"})["status"], "ok")
            self.assertEqual(self.calls[-1][0], call)
        self.assertEqual(d({"action": "import", "kind": "nope", "path": "C:/p/x"})["status"], "error")

    def test_run_needs_the_secret(self) -> None:
        self.check_run("mari.projects.current().name()", "chair_tex")


if __name__ == "__main__":
    unittest.main()
