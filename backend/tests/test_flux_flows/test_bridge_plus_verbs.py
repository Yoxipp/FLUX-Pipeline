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

# soft -> (prefix, open extension (None = new project from a mesh), save_as extension, import kind or None)
TCP_SOFTS = {"mari": ("mari", None, ".mra", "version"),
             "zbrush": ("zb", ".zpr", ".zpr", "mesh"),
             "designer": ("sd", ".sbs", ".sbs", "bitmap")}
NO_DISCARD = {"designer"}   # open adds a package, nothing is replaced


def _handler(requests):
    def handler(req):
        requests.append(req)
        action = req.get("action")
        if action == "ping":
            return {"status": "ok", "version": "test"}
        if action in ("open", "save", "save_as"):
            return {"status": "ok", "project": req.get("path") or "chair"}
        if action in ("import", "stop", "cancel"):
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
        for soft, (prefix, open_ext, ext, kind) in TCP_SOFTS.items():
            with self.subTest(soft=soft):
                mesh = self.tmp / "chair.obj"
                mesh.write_text("x", encoding="utf-8")
                source = {"mesh": str(mesh)} if open_ext is None else {"path": str(self.tmp / f"chair{open_ext}")}
                discard = soft not in NO_DISCARD
                rec, _ = run_node(soft, f"dcc.{prefix}_open_scene", self.srv.port,
                                  {"discard_changes": True} if discard else {}, source)
                self.assertEqual(rec["status"], "ok", rec.get("error"))
                req = self._last("open")
                self.assertEqual((Path(req["mesh"] or req["path"]), req["discard"]),
                                 (Path(list(source.values())[0]), discard))
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
                rec, value = run_node(soft, f"dcc.{prefix}_run_script", self.srv.port, inputs={"code": "result = 7"},
                                      out="result")
                self.assertEqual((rec["status"], value), ("ok", 7), rec.get("error"))

    def test_zbrush_is_released_at_the_end_of_the_run_not_between_verbs(self) -> None:
        rec, _ = run_node("zbrush", "dcc.zb_save_scene", self.srv.port)
        self.assertEqual(rec["status"], "ok", rec.get("error"))
        actions = [r.get("action") for r in self.requests if r.get("action") != "ping"]
        self.assertEqual(actions[-2:], ["save", "stop"])
        self.requests.clear()
        rec, _ = run_node("zbrush", "dcc.zb_run_script", self.srv.port, inputs={"code": "result = 7"})
        self.assertIn("stop", [r.get("action") for r in self.requests])

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


def _load_zbrush_plugin(zbc) -> dict:
    """The plugin binds its socket and registers its UI at import: its source is run without
    the module-level try blocks (except the zbrush import), as tests/zbrush does."""
    import ast

    src = Path(__file__).resolve().parents[2] / "dcc" / "zbrush" / "zbrush_bridge_plugin.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    tries = [n for n in tree.body if isinstance(n, ast.Try)]
    body = [n for n in tree.body if not isinstance(n, ast.Try) or n is tries[0]]
    ns = {"__name__": "zb_plugin_test", "__file__": str(src)}
    zbrush = types.ModuleType("zbrush")
    zbrush.commands = zbc
    with mock.patch.dict(sys.modules, {"zbrush": zbrush, "zbrush.commands": zbc}):
        exec(compile(ast.Module(body=body, type_ignores=[]), str(src), "exec"), ns)
    ns["_log"] = ns["_diag"] = lambda msg: None
    return ns


class ZBrushScript(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_zb_script_"))
        calls = self.calls = []
        state = {"next": "", "last": ""}
        tmp = self.tmp

        def press(button):
            calls.append((button, state["next"]))
            if button in ("File:Save As", "Tool:Save"):
                Path(state["next"]).write_text("x", encoding="utf-8")
            if button in ("File:Save As", "File:Open"):
                state["last"] = state["next"]

        zbc = types.ModuleType("zbrush.commands")
        zbc.set_next_filename = lambda p: state.update(next=p)
        zbc.press = press
        zbc.get_last_used_filename = lambda: state["last"]
        zbc.get_active_tool_index = lambda: 0
        zbc.get_tool_path = lambda i: str(tmp / "artist.ztl")
        zbc.set_tool_path = lambda i, p: state.update(next=p)
        zbc.update = lambda redraw_ui=True: None
        self.ns = _load_zbrush_plugin(zbc)
        self.ns["_ZBRUSH_AVAILABLE"] = True
        self.state = state

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_open_needs_discard_for_a_project_and_save_needs_a_project(self) -> None:
        d = self.ns["_dispatch"]
        zpr = self.tmp / "head_v004.zpr"
        zpr.write_text("x", encoding="utf-8")
        self.assertEqual(d({"action": "open", "path": str(zpr)})["status"], "error")
        self.assertEqual(self.calls, [])
        self.assertIn("zbSaveAs", d({"action": "save"})["msg"])
        self.assertEqual(d({"action": "open", "path": str(zpr), "discard": True})["status"], "ok")
        self.assertEqual(self.calls[-1], ("File:Open", str(zpr)))
        self.assertEqual(d({"action": "save"})["status"], "ok")
        self.assertEqual(self.calls[-1][0], "File:Save As")

    def test_save_as_project_or_tool_and_imports(self) -> None:
        d = self.ns["_dispatch"]
        zpr, ztl = str(self.tmp / "out" / "head.zpr"), str(self.tmp / "out" / "head.ztl")
        self.assertEqual(d({"action": "save_as", "path": zpr, "copy": True})["status"], "error")
        self.assertEqual(d({"action": "save_as", "path": zpr})["status"], "ok")
        self.assertEqual(d({"action": "save_as", "path": ztl})["status"], "ok")
        self.assertEqual(self.calls[-1][0], "Tool:Save")
        mesh = self.tmp / "retopo.obj"
        mesh.write_text("x", encoding="utf-8")
        self.assertEqual(d({"action": "import", "kind": "mesh", "path": str(mesh)})["status"], "ok")
        self.assertEqual(self.calls[-1], ("Tool:Import", str(mesh)))
        self.assertEqual(d({"action": "import", "kind": "tool", "path": str(mesh)})["status"], "ok")
        self.assertEqual(self.calls[-1][0], "Tool:Load")

    def test_run_needs_the_secret(self) -> None:
        d = self.ns["_dispatch"]
        self.ns["_secret"] = lambda: ""
        self.assertFalse(d({"action": "run", "code": "result = 1", "secret": ""})["ok"])
        self.ns["_secret"] = lambda: "s3cret"
        self.assertFalse(d({"action": "run", "code": "result = 1", "secret": "bad"})["ok"])
        resp = d({"action": "run", "code": "result = zbc.get_active_tool_index()", "secret": "s3cret"})
        self.assertEqual((resp["ok"], resp["result"]), (True, 0))


class DesignerScript(_FakeModules):
    MODULE = "dcc.substance_designer.substance_designer_bridge"

    def setUp(self) -> None:
        calls = self.calls = []
        tmp = Path(tempfile.mkdtemp(prefix="flux_sd_files_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        self.sbs = tmp / "wood.sbs"
        self.sbs.write_text("x", encoding="utf-8")

        class Pkg:
            def __init__(self, path):
                self.path = path

            def getFilePath(self):  # noqa: N802 - sd API
                return self.path

        pkg = Pkg("C:/p/current.sbs")
        graph = types.SimpleNamespace(getPackage=lambda: pkg)
        mgr = types.SimpleNamespace(
            getUserPackageFromFilePath=lambda p: None,
            loadUserPackage=lambda p: (calls.append(("load", p)), Pkg(p))[1],
            savePackage=lambda k: calls.append(("save", k.path)),
            savePackageAs=lambda k, p: calls.append(("save_as", k.path, p)),
            getUserPackages=lambda: [pkg])
        app = types.SimpleNamespace(getPackageMgr=lambda: mgr,
                                    getQtForPythonUIMgr=lambda: types.SimpleNamespace(getCurrentGraph=lambda: graph))
        sd = types.ModuleType("sd")
        sd.getContext = lambda: types.SimpleNamespace(getSDApplication=lambda: app)
        api = types.ModuleType("sd.api")
        res = types.ModuleType("sd.api.sdresource")
        res.EmbedMethod = types.SimpleNamespace(Linked="linked")
        bitmap = types.ModuleType("sd.api.sdresourcebitmap")
        bitmap.SDResourceBitmap = types.SimpleNamespace(
            sNewFromFile=lambda k, p, m: calls.append(("bitmap", k.path, p, m)))
        scene = types.ModuleType("sd.api.sdresourcescene")
        scene.SDResourceScene = types.SimpleNamespace(
            sNewFromFile=lambda k, p, m: calls.append(("scene", k.path, p, m)))
        self.load({"sd": sd, "sd.api": api, "sd.api.sdresource": res, "sd.api.sdresourcebitmap": bitmap,
                   "sd.api.sdresourcescene": scene})

    def test_open_save_save_as_import(self) -> None:
        d = self.bridge._dispatch
        self.assertEqual(d({"action": "open", "path": "C:/p/x.spp"})["status"], "error")
        self.assertEqual(d({"action": "open", "path": str(self.sbs)})["project"], str(self.sbs))
        self.assertEqual(d({"action": "save"})["project"], "C:/p/current.sbs")
        target = str(self.tmp / "out" / "wood_v2.sbs")
        self.assertEqual(d({"action": "save_as", "path": target})["status"], "ok")
        self.assertEqual(self.calls[:3], [("load", str(self.sbs)), ("save", "C:/p/current.sbs"),
                                          ("save_as", "C:/p/current.sbs", target)])
        self.assertEqual(d({"action": "import", "kind": "bitmap", "path": str(self.sbs)})["status"], "ok")
        self.assertEqual(self.calls[-1], ("bitmap", "C:/p/current.sbs", str(self.sbs), "linked"))
        self.assertEqual(d({"action": "import", "kind": "mesh", "path": str(self.sbs)})["status"], "ok")
        self.assertEqual(self.calls[-1][0], "scene")

    def test_run_needs_the_secret(self) -> None:
        self.check_run("app.getPackageMgr().getUserPackages()[0].getFilePath()", "C:/p/current.sbs")


class MarvelousNodes(unittest.TestCase):
    """The file mailbox (no TCP in Marvelous' Python)."""

    def setUp(self) -> None:
        import json
        import threading
        import time

        h.reset()
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_mvd_plus_"))
        box = self.tmp / "flux_marvelous_bridge"
        box.mkdir()
        self._env = mock.patch.dict(os.environ, {"FLUX_MD_MAILBOX_ROOT": str(self.tmp),
                                                 "FLUX_BRIDGE_SECRET_FILE": str(self.tmp / "secret.txt")})
        self._env.start()
        self.requests, self.stop = [], threading.Event()

        def beat():
            tmp = box / "alive.json.tmp"
            tmp.write_text(json.dumps({"time": time.time(), "pid": os.getpid(), "version": "MD"}), encoding="utf-8")
            os.replace(tmp, box / "alive.json")

        def serve():
            while not self.stop.is_set():
                beat()
                for req in list(box.glob("*.req")):
                    payload = json.loads(req.read_text(encoding="utf-8"))
                    req.unlink()
                    self.requests.append(payload)
                    answer = _handler([])(payload)
                    (box / (req.name[:-4] + ".resp")).write_text(json.dumps(answer), encoding="utf-8")
                time.sleep(0.02)

        beat()
        self.thread = threading.Thread(target=serve, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.stop.set()
        self.thread.join(2)
        self._env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_open_save_save_as_run(self) -> None:
        zprj = str(self.tmp / "dress.zprj")
        rec, _ = run_node("marvelous", "dcc.mvd_open_scene", None, {"discard_changes": True}, {"path": zprj})
        self.assertEqual(rec["status"], "ok", rec.get("error"))
        self.assertEqual((self.requests[-1]["action"], self.requests[-1]["discard"]), ("open", True))
        rec, _ = run_node("marvelous", "dcc.mvd_save_scene", None)
        self.assertEqual(rec["status"], "ok", rec.get("error"))
        rec, value = run_node("marvelous", "dcc.mvd_save_as", None, inputs={"path": zprj}, out="path")
        self.assertEqual((rec["status"], Path(value)), ("ok", Path(zprj)), rec.get("error"))
        rec, _ = run_node("marvelous", "dcc.mvd_save_as", None, inputs={"path": str(self.tmp / "d.obj")})
        self.assertEqual(rec["status"], "error")
        rec, value = run_node("marvelous", "dcc.mvd_run_script", None, inputs={"code": "result = 7"}, out="result")
        self.assertEqual((rec["status"], value), ("ok", 7), rec.get("error"))


class MarvelousScript(unittest.TestCase):
    """The script serves at import inside Marvelous: run without its final `serve()`."""

    def setUp(self) -> None:
        import ast

        src = Path(__file__).resolve().parents[2] / "dcc" / "marvelous" / "marvelous_bridge.py"
        tree = ast.parse(src.read_text(encoding="utf-8"))
        body = [n for n in tree.body if not (isinstance(n, ast.If) and "serve" in ast.dump(n))]
        self.ns = {"__name__": "mvd_bridge_test"}
        exec(compile(ast.Module(body=body, type_ignores=[]), str(src), "exec"), self.ns)
        self.ns["_MD_AVAILABLE"] = True
        self.ns["_diag"] = lambda msg: None
        self.calls = []
        self.ns["_do_import"] = lambda cfg: (self.calls.append(("import", cfg["path"])), {"status": "ok"})[1]
        self.ns["_call_export"] = lambda fmt, path, opts: (self.calls.append(("export", fmt, path)), [path])[1]
        self.ns["_project"] = lambda: ("dress", "C:/p/dress_v003.zprj")
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_mvd_script_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_open_needs_discard_save_and_save_as_export_a_zprj(self) -> None:
        d = self.ns["_dispatch"]
        self.assertEqual(d({"action": "open", "path": "C:/p/a.zprj"})["status"], "error")
        self.assertEqual(self.calls, [])
        self.assertEqual(d({"action": "open", "config": {"path": "C:/p/a.zprj"}, "discard": True})["project"],
                         "C:/p/a.zprj")
        self.assertEqual(d({"action": "save"})["project"], "C:/p/dress_v003.zprj")
        target = str(self.tmp / "out" / "dress.zprj").replace(chr(92), "/")
        self.assertEqual(d({"action": "save_as", "path": target})["status"], "ok")
        self.assertEqual(self.calls, [("import", "C:/p/a.zprj"), ("export", "zprj", "C:/p/dress_v003.zprj"),
                                      ("export", "zprj", target)])
        self.ns["_project"] = lambda: ("", "")
        self.assertIn("mvdSaveAs", d({"action": "save"})["msg"])

    def test_run_needs_the_secret(self) -> None:
        d = self.ns["_dispatch"]
        self.ns["_secret"] = lambda: ""
        self.assertFalse(d({"action": "run", "code": "result = 1", "secret": ""})["ok"])
        self.ns["_secret"] = lambda: "s3cret"
        self.assertFalse(d({"action": "run", "code": "result = 1", "secret": "bad"})["ok"])
        resp = d({"action": "run", "code": "result = 40 + 2", "secret": "s3cret"})
        self.assertEqual((resp["ok"], resp["result"]), (True, 42))


if __name__ == "__main__":
    unittest.main()
