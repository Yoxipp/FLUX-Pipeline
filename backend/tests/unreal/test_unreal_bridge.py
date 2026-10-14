# test_unreal_bridge.py - Unreal host project, bridge plugin, launcher and client (ADR 0052).

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from core.constants import DCC_PORT_RANGES
from dcc.unreal import autostart
from features.launcher import launcher_core

UE56 = r"C:\Program Files\Epic Games\UE_5.6\Engine\Binaries\Win64\UnrealEditor.exe"


class _TmpProject(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "FluxRender"
        self._env = mock.patch.dict(os.environ, {"FLUX_UNREAL_PROJECT_DIR": str(self.root)})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()


class HostProject(_TmpProject):
    def test_default_location_is_not_appdata(self):
        # Microsoft Store Python redirects AppData writes: Unreal never saw the .uproject.
        with mock.patch.dict(os.environ, {"USERPROFILE": r"C:\Users\x"}):
            os.environ.pop("FLUX_UNREAL_PROJECT_DIR", None)
            path = autostart.project_dir()
        self.assertEqual(path, Path(r"C:\Users\x") / "FluxPipeline" / "unreal" / "FluxRender")
        self.assertNotIn("appdata", str(path).lower())

    def test_engine_association_from_exe(self):
        self.assertEqual(autostart.engine_association(UE56), "5.6")
        self.assertEqual(autostart.engine_association(r"D:\custom\UnrealEditor.exe"), "")

    def test_ensure_project_writes_uproject_plugin_and_init(self):
        uproject = autostart.ensure_project(UE56)
        data = json.loads(uproject.read_text(encoding="utf-8"))
        self.assertEqual(data["EngineAssociation"], "5.6")
        enabled = {p["Name"] for p in data["Plugins"] if p["Enabled"]}
        self.assertTrue({"USDImporter", "PythonScriptPlugin", "MovieRenderPipeline", "FluxBridge"} <= enabled)
        python_dir = self.root / "Plugins" / "FluxBridge" / "Content" / "Python"
        self.assertTrue((self.root / "Plugins" / "FluxBridge" / "FluxBridge.uplugin").is_file())
        self.assertIn("flux_unreal_bridge.start()", (python_dir / "init_unreal.py").read_text(encoding="utf-8"))
        self.assertTrue(autostart.is_installed())

    def test_refresh_keeps_artist_plugins_and_follows_engine(self):
        uproject = autostart.ensure_project(UE56)
        data = json.loads(uproject.read_text(encoding="utf-8"))
        data["Plugins"].append({"Name": "SomeArtistPlugin", "Enabled": True})
        data["Plugins"][0]["Enabled"] = False        # a FLUX plugin turned off by hand
        uproject.write_text(json.dumps(data), encoding="utf-8")
        autostart.ensure_project(UE56.replace("UE_5.6", "UE_5.7"))
        data = json.loads(uproject.read_text(encoding="utf-8"))
        self.assertEqual(data["EngineAssociation"], "5.7")
        names = {p["Name"]: p["Enabled"] for p in data["Plugins"]}
        self.assertTrue(names["SomeArtistPlugin"])
        self.assertTrue(all(names[n] for n in ("USDImporter", "PythonScriptPlugin", "FluxBridge")))

    def test_stale_bridge_copy_is_not_installed(self):
        autostart.ensure_project(UE56)
        bridge = self.root / "Plugins" / "FluxBridge" / "Content" / "Python" / "flux_unreal_bridge.py"
        bridge.write_text("# old bridge\n", encoding="utf-8")
        self.assertFalse(autostart.is_installed())
        self.assertTrue(autostart.install(UE56)["success"])
        self.assertTrue(autostart.is_installed())

    def test_uninstall_removes_plugin_keeps_project(self):
        uproject = autostart.ensure_project(UE56)
        self.assertTrue(autostart.uninstall()["success"])
        self.assertFalse((self.root / "Plugins" / "FluxBridge").exists())
        self.assertTrue(uproject.is_file())
        self.assertFalse(autostart.is_installed())


class Launcher(_TmpProject):
    def test_ue_versions_sort_newest_first(self):
        paths = [UE56.replace("5.6", v) for v in ("5.4", "5.10", "5.6")]
        ordered = sorted(paths, key=launcher_core._version_key, reverse=True)
        self.assertIn("UE_5.10", ordered[0])
        self.assertIn("UE_5.4", ordered[-1])

    def test_epic_launcher_installs_on_other_drives(self):
        with tempfile.TemporaryDirectory() as tmp:
            dat = Path(tmp) / "Epic" / "UnrealEngineLauncher" / "LauncherInstalled.dat"
            dat.parent.mkdir(parents=True)
            dat.write_text(json.dumps({"InstallationList": [
                {"InstallLocation": r"D:\Epic\UE_5.6", "AppName": "UE_5.6"},
                {"InstallLocation": r"D:\Epic\Fortnite", "AppName": "Fortnite"},
            ]}), encoding="utf-8")
            with mock.patch.dict(os.environ, {"PROGRAMDATA": tmp}):
                found = launcher_core._epic_launcher_candidates()
        self.assertEqual(found, [os.path.join(r"D:\Epic\UE_5.6", "Engine", "Binaries", "Win64", "UnrealEditor.exe")])

    def test_launch_opens_the_host_project(self):
        with mock.patch.object(launcher_core, "_resolve_exe", return_value=UE56), \
                mock.patch.object(launcher_core.subprocess, "Popen") as popen:
            self.assertTrue(launcher_core.launch_dcc("unreal"))
        cmd = popen.call_args[0][0]
        target = cmd if isinstance(cmd, str) else " ".join(cmd)
        self.assertIn("FluxRender.uproject", target)
        self.assertTrue(autostart.is_installed())


def _fake_unreal() -> types.ModuleType:
    module = types.ModuleType("unreal")
    module.log = lambda *_a: None
    module.log_error = lambda *_a: None
    module.SystemLibrary = types.SimpleNamespace(get_engine_version=lambda: "5.6.1")
    return module


class BridgeProtocol(unittest.TestCase):
    def setUp(self):
        self._mods = mock.patch.dict(sys.modules, {"unreal": _fake_unreal()})
        self._mods.start()
        sys.modules.pop("dcc.unreal.unreal_bridge", None)
        from dcc.unreal import unreal_bridge
        self.bridge = unreal_bridge

    def tearDown(self):
        sys.modules.pop("dcc.unreal.unreal_bridge", None)
        self._mods.stop()

    def test_port_range_matches_constants(self):
        self.assertEqual((self.bridge.PORT_BASE, self.bridge.PORT_COUNT), DCC_PORT_RANGES["Unreal"])

    def test_ping_and_unknown_action(self):
        self.assertEqual(self.bridge.handle({"action": "ping"}), {"status": "ok", "version": "Unreal 5.6.1"})
        self.assertEqual(self.bridge.handle({"action": "nope"})["status"], "error")

    def test_live_opens_first_then_reloads(self):
        b = self.bridge
        actor = object()
        with mock.patch.object(b, "_find_stage_actor", return_value=actor), \
                mock.patch.object(b, "_root_layer", return_value="C:/other/stage.usd"), \
                mock.patch.object(b, "_cmd_open_stage", return_value={"status": "ok"}) as opened, \
                mock.patch.object(b, "_cmd_reload", return_value={"status": "ok", "mode": "targeted"}) as reloaded:
            self.assertEqual(b.handle({"action": "live", "path": "C:/live/a.usd"})["mode"], "open")
            opened.assert_called_once()
            reloaded.assert_not_called()
        # Same file, other spelling (Windows): a reload, not a new open.
        with mock.patch.object(b, "_find_stage_actor", return_value=actor), \
                mock.patch.object(b, "_root_layer", return_value=r"C:\live\A.usd"), \
                mock.patch.object(b, "_cmd_reload", return_value={"status": "ok", "mode": "targeted"}) as reloaded:
            self.assertEqual(b.handle({"action": "live", "path": "C:/live/a.usd"})["mode"], "targeted")
            reloaded.assert_called_once()

    def test_live_pause_ignores_pushes(self):
        b = self.bridge
        self.assertTrue(b.handle({"action": "live_pause", "paused": True})["paused"])
        with mock.patch.object(b, "_cmd_open_stage") as opened:
            self.assertTrue(b.handle({"action": "live", "path": "C:/live/a.usd"})["paused"])
            opened.assert_not_called()
        self.assertFalse(b.handle({"action": "live_pause", "paused": False})["paused"])

    def test_open_stage_refuses_missing_file(self):
        answer = self.bridge.handle({"action": "open_stage", "path": "Z:/missing/stage.usda"})
        self.assertEqual(answer["status"], "error")
        self.assertIn("introuvable", answer["msg"])


class ClientAndRouter(unittest.TestCase):
    def test_open_stage_payload(self):
        from dcc.unreal import client
        with mock.patch.object(client, "send_json_line", return_value={"ok": True}) as send:
            client.unreal_client.open_stage("C:/p/SH010_LAST.usda", "render")
        payload = send.call_args[0][2]
        self.assertEqual(payload, {"action": "open_stage", "path": "C:/p/SH010_LAST.usda", "purpose": "render"})

    def test_router_refuses_missing_stage_and_bad_purpose(self):
        from fastapi import HTTPException
        from routers import dcc as dcc_router
        req = dcc_router.UnrealOpenStageRequest(path="Z:/missing.usda")
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(dcc_router.unreal_open_stage(req))
        self.assertEqual(ctx.exception.status_code, 404)
        bad = dcc_router.UnrealOpenStageRequest(path="Z:/missing.usda", purpose="guide")
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(dcc_router.unreal_open_stage(bad))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_router_live_refuses_missing_layer(self):
        from fastapi import HTTPException
        from routers import dcc as dcc_router
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(dcc_router.unreal_live(dcc_router.UnrealLiveRequest(path="Z:/missing_live.usd")))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_unreal_is_wired_everywhere(self):
        from core.dcc_process import PROCESS_NAMES
        from routers import dcc as dcc_router
        self.assertIn("unreal", dcc_router._AUTOSTART_MODULES)
        self.assertIn("unreal", dcc_router._PING_PROBES)
        self.assertIn("unreal", launcher_core.DCC_FRONTEND_KEYS)
        self.assertIn("Unreal", PROCESS_NAMES)


class ShelfAndHda(_TmpProject):
    def test_shelf_manager_versions_install_and_remove(self):
        from features.shelf_manager import shelf_core
        exes = [UE56.replace("5.6", "5.7"), UE56]
        with mock.patch("features.launcher.launcher_core.list_dcc_candidates", return_value=exes):
            self.assertEqual(shelf_core.get_installed_versions("Unreal"), ["5.6", "5.7"])
            ok, _msg = shelf_core.install_shelf("Unreal", "5.6")
            self.assertTrue(ok)
            self.assertTrue(shelf_core.is_shelf_installed("Unreal", "5.6"))
            self.assertFalse(shelf_core.is_shelf_installed("Unreal", "5.7"))
            self.assertFalse(shelf_core.install_shelf("Unreal", "4.27")[0])
            self.assertTrue(shelf_core.remove_shelf("Unreal", "5.6")[0])
            self.assertFalse(shelf_core.is_shelf_installed("Unreal", "5.6"))

    def test_live_hda_never_rewrites_disk_layers_and_is_built(self):
        from dcc.houdini.hda import flux_unreal_live_hda as hda
        from features.shelf_manager.shelf_core import _HDA_BUILDS
        code = hda._build_code("C:/otls/flux_unreal_live.hda")
        self.assertIn('parm("savefilesfromdisk").set(0)', code)
        self.assertIn('createNode("usd_rop", "live_rop")', code)
        compile(code, "build", "exec")
        compile(hda.MODULE_FUNCTIONS, "module", "exec")
        compile(hda.BOOTSTRAP, "bootstrap", "exec")
        self.assertIn("/dcc/unreal/live", hda.MODULE_FUNCTIONS)
        self.assertIn(("flux_unreal_live_hda:build_hda", "flux_unreal_live.hda",
                       "hou.lopNodeTypeCategory()", "flux_unreal_live"), _HDA_BUILDS)

    def test_houdini_shelf_has_the_live_button(self):
        import xml.dom.minidom
        shelf = Path(__file__).resolve().parents[2] / "resources" / "shelves" / "houdini" / "Flux.shelf"
        doc = xml.dom.minidom.parse(str(shelf))
        tools = {t.getAttribute("name") for t in doc.getElementsByTagName("tool")}
        members = {m.getAttribute("name") for m in doc.getElementsByTagName("memberTool")}
        self.assertIn("flux_tool_unreal_live", tools & members)


if __name__ == "__main__":
    unittest.main()
