# P6b step 9 (2026-10-24): Painter "bridge+" verbs (open, save, save_as, import, run_script).
# Nodes against a fake TCP bridge, the real bridge script against a fake substance_painter
# module, the machine secret and its sidecar. They prove the protocol, not Painter: the
# Painter API calls stay "to validate live".

from __future__ import annotations

import importlib
import json
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


class _SecretEnv(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_sp_plus_"))
        self._env = mock.patch.dict(os.environ, {"FLUX_BRIDGE_SECRET_FILE": str(self.tmp / "secret.txt")})
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


class Secret(_SecretEnv):
    def test_secret_is_stable_and_written_next_to_the_script(self) -> None:
        from dcc import bridge_secret

        first = bridge_secret.get_secret()
        self.assertGreaterEqual(len(first), 32)
        self.assertEqual(bridge_secret.get_secret(), first)
        script = self.tmp / "flux_substance_bridge.py"
        script.write_text("", encoding="utf-8")
        side = bridge_secret.write_sidecar(script)
        self.assertEqual(side.name, "flux_substance_bridge.json")
        self.assertEqual(json.loads(side.read_text(encoding="utf-8"))["secret"], first)
        bridge_secret.remove_sidecar(script)
        self.assertFalse(side.exists())

    def test_painter_install_writes_and_uninstall_removes_the_sidecar(self) -> None:
        from dcc.substance_painter import autostart

        with mock.patch.dict(os.environ, {"FLUX_SP_PLUGINS_DIR": str(self.tmp / "startup")}), \
                mock.patch("dcc.substance_painter.presets.install_presets", return_value=[]):
            self.assertTrue(autostart.install()["success"])
            side = self.tmp / "startup" / "flux_substance_bridge.json"
            self.assertTrue(side.exists())
            self.assertTrue(autostart.uninstall()["success"])
            self.assertFalse(side.exists())


class Nodes(_SecretEnv):
    def setUp(self) -> None:
        super().setUp()
        h.reset()

        def handler(req):
            action = req.get("action")
            if action == "ping":
                return {"status": "ok", "version": "test"}
            if action in ("open", "save", "save_as"):
                return {"status": "ok", "project": req.get("path") or "/p/new.spp"}
            if action == "import":
                return {"status": "ok", "url": "" if req.get("kind") == "mesh" else "resource://project/a"}
            if action == "run":
                from dcc.bridge_secret import get_secret

                if req.get("secret") != get_secret():
                    return {"ok": False, "status": "error", "error": "secret du bridge refuse"}
                return {"ok": True, "status": "ok", "result": 42, "trace": ""}
            return {"status": "error", "msg": f"unknown action: {action}"}

        self.srv = FakeTcpJson(handler).start()

    def tearDown(self) -> None:
        self.srv.close()
        super().tearDown()

    def _last(self, action):
        return [r for r in self.srv.requests if r.get("action") == action][-1]

    def test_open_from_a_spp_or_a_mesh(self) -> None:
        spp = str(self.tmp / "chair.spp")
        rec, value = run_node("painter", "dcc.sp_open_scene", self.srv.port, inputs={"path": spp}, out="scene")
        self.assertEqual((rec["status"], Path(value)), ("ok", Path(spp)), rec.get("error"))
        self.assertEqual((self._last("open")["mesh"], self._last("open")["discard"]), ("", False))
        mesh = str(self.tmp / "chair.fbx")
        rec, _ = run_node("painter", "dcc.sp_open_scene", self.srv.port, {"discard_changes": True},
                          {"path": spp, "mesh": mesh})
        self.assertEqual(rec["status"], "ok", rec.get("error"))
        req = self._last("open")
        self.assertEqual((Path(req["mesh"]), req["path"], req["discard"]), (Path(mesh), "", True))

    def test_save_and_save_as(self) -> None:
        rec, _ = run_node("painter", "dcc.sp_save_scene", self.srv.port)
        self.assertEqual(rec["status"], "ok", rec.get("error"))
        target = str(self.tmp / "chair_tex.spp")
        rec, value = run_node("painter", "dcc.sp_save_as", self.srv.port, {"copy": True}, {"path": target}, "path")
        self.assertEqual((rec["status"], Path(value)), ("ok", Path(target)), rec.get("error"))
        self.assertTrue(self._last("save_as")["copy"])
        rec, _ = run_node("painter", "dcc.sp_save_as", self.srv.port, inputs={"path": str(self.tmp / "chair.ma")})
        self.assertEqual(rec["status"], "error")
        self.assertIn(".spp", rec["nodes"]["n"]["error"])

    def test_save_as_refuses_an_existing_file_without_overwrite(self) -> None:
        target = self.tmp / "chair_tex.spp"
        target.write_text("x", encoding="utf-8")
        rec, _ = run_node("painter", "dcc.sp_save_as", self.srv.port, inputs={"path": str(target)})
        self.assertEqual(rec["status"], "error")
        self.assertFalse([r for r in self.srv.requests if r.get("action") == "save_as"])

    def test_import_mesh_or_resource(self) -> None:
        src = self.tmp / "chair.fbx"
        src.write_text("x", encoding="utf-8")
        rec, value = run_node("painter", "dcc.sp_import", self.srv.port, {"kind": "mesh"}, {"path": str(src)}, "url")
        self.assertEqual((rec["status"], value), ("ok", ""), rec.get("error"))
        self.assertEqual(self._last("import")["kind"], "mesh")
        rec, value = run_node("painter", "dcc.sp_import", self.srv.port, {"usage": "alpha"}, {"path": str(src)}, "url")
        self.assertEqual(value, "resource://project/a")
        self.assertEqual((self._last("import")["kind"], self._last("import")["usage"]), ("resource", "alpha"))
        rec, _ = run_node("painter", "dcc.sp_import", self.srv.port, inputs={"path": str(self.tmp / "missing.png")})
        self.assertEqual(rec["status"], "error")

    def test_run_script_sends_the_machine_secret(self) -> None:
        rec, value = run_node("painter", "dcc.sp_run_script", self.srv.port, inputs={"code": "result = 42"}, out="result")
        self.assertEqual((rec["status"], value), ("ok", 42), rec.get("error"))
        self.assertTrue(self._last("run")["secret"])

    def test_an_old_bridge_asks_for_a_reinstall(self) -> None:
        self.srv.close()
        self.srv = FakeTcpJson(lambda req: {"status": "ok"} if req.get("action") == "ping"
                               else {"status": "error", "msg": f"unknown action: {req.get('action')}"}).start()
        rec, _ = run_node("painter", "dcc.sp_save_scene", self.srv.port)
        self.assertIn("reinstalle le bridge", rec["nodes"]["n"]["error"])


class BridgeScript(unittest.TestCase):
    """The script copied into Painter, against a fake substance_painter module."""

    def setUp(self) -> None:
        self.calls = []
        calls = self.calls
        state = {"open": True, "dirty": True, "path": "C:/p/a.spp"}
        self.state = state

        project = types.ModuleType("substance_painter.project")
        project.is_open = lambda: state["open"]
        project.needs_saving = lambda: state["dirty"]
        project.is_busy = lambda: False
        project.file_path = lambda: state["path"]
        project.close = lambda: calls.append(("close",))
        project.open = lambda p: (calls.append(("open", p)), state.update(path=p))
        project.create = lambda mesh_file_path: (calls.append(("create", mesh_file_path)), state.update(path=""))
        project.save = lambda: calls.append(("save",))
        project.save_as = lambda p: calls.append(("save_as", p))
        project.save_as_copy = lambda p: calls.append(("save_as_copy", p))
        project.MeshReloadingSettings = lambda: "settings"

        def reload_mesh(path, settings, cb):
            calls.append(("reload_mesh", path, settings))
            cb("ReloadMeshStatus.SUCCESS")

        project.reload_mesh = reload_mesh
        resource = types.ModuleType("substance_painter.resource")
        resource.Usage = types.SimpleNamespace(TEXTURE="tex", ALPHA="alpha")

        class _Res:
            def identifier(self):
                return types.SimpleNamespace(url=lambda: "resource://project/a")

        resource.import_project_resource = lambda p, u: (calls.append(("import_resource", p, u)), _Res())[1]
        sp = types.ModuleType("substance_painter")
        sp.project, sp.resource, sp.__version__ = project, resource, "test"
        export = types.ModuleType("substance_painter.export")
        sp.export = export
        self._mods = mock.patch.dict(sys.modules, {"substance_painter": sp, "substance_painter.project": project,
                                                   "substance_painter.resource": resource,
                                                   "substance_painter.export": export})
        self._mods.start()
        sys.modules.pop("dcc.substance_painter.substance_painter_bridge", None)
        self.bridge = importlib.import_module("dcc.substance_painter.substance_painter_bridge")
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_sp_script_"))

    def tearDown(self) -> None:
        self._mods.stop()
        sys.modules.pop("dcc.substance_painter.substance_painter_bridge", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_open_refuses_unsaved_changes_unless_discard(self) -> None:
        d = self.bridge._dispatch
        self.assertEqual(d({"action": "open", "path": "C:/p/b.spp"})["status"], "error")
        self.assertEqual(self.calls, [])
        resp = d({"action": "open", "path": "C:/p/b.spp", "discard": True})
        self.assertEqual((resp["status"], resp["project"]), ("ok", "C:/p/b.spp"))
        self.assertEqual(self.calls, [("close",), ("open", "C:/p/b.spp")])
        self.calls.clear()
        self.state["dirty"] = False
        self.assertEqual(d({"action": "open", "mesh": "C:/p/m.fbx"})["status"], "ok")
        self.assertEqual(self.calls, [("close",), ("create", "C:/p/m.fbx")])

    def test_save_save_as_and_imports(self) -> None:
        d = self.bridge._dispatch
        self.assertEqual(d({"action": "save"})["status"], "ok")
        target = str(self.tmp / "out" / "c.spp")
        self.assertEqual(d({"action": "save_as", "path": target, "copy": True})["status"], "ok")
        self.assertIn(("save_as_copy", target), self.calls)
        self.assertEqual(d({"action": "import", "kind": "mesh", "path": "C:/p/m.fbx"})["status"], "ok")
        self.assertIn(("reload_mesh", "C:/p/m.fbx", "settings"), self.calls)
        resp = d({"action": "import", "kind": "resource", "path": "C:/p/t.png", "usage": "alpha"})
        self.assertEqual((resp["status"], resp["url"]), ("ok", "resource://project/a"))
        self.assertEqual(d({"action": "import", "path": "C:/p/t.png", "usage": "nope"})["status"], "error")
        self.state["path"] = ""
        self.assertIn("spSaveAs", d({"action": "save"})["msg"])

    def test_run_needs_the_secret(self) -> None:
        d = self.bridge._dispatch
        with mock.patch.object(self.bridge, "_secret", return_value=""):
            self.assertFalse(d({"action": "run", "code": "result = 1", "secret": ""})["ok"])
        with mock.patch.object(self.bridge, "_secret", return_value="s3cret"):
            self.assertFalse(d({"action": "run", "code": "result = 1", "secret": "bad"})["ok"])
            resp = d({"action": "run", "code": "result = substance_painter.__version__", "secret": "s3cret"})
            self.assertEqual((resp["ok"], resp["result"]), (True, "test"))
            resp = d({"action": "run", "code": "raise ValueError('boom')", "secret": "s3cret"})
            self.assertEqual((resp["ok"], resp["error"]), (False, "boom"))


if __name__ == "__main__":
    unittest.main()
