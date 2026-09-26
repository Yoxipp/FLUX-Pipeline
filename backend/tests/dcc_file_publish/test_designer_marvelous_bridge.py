# test_designer_marvelous_bridge.py — Substance Designer + Marvelous bridge publish.
#
# No app needed: the export-config builders are pure; the bridge export and the
# ingest (publish_file) are mocked, so the orchestration is verified end to end
# without Designer / Marvelous. The in-app scripts are imported (syntax + helpers).

from __future__ import annotations

import json
import os
import sys
import time as _time
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from dcc.marvelous import autostart as md_autostart
from dcc.marvelous import client as md_client
from dcc.marvelous import marvelous_export as mx
from dcc.substance_designer import autostart as sd_autostart
from dcc.substance_designer import client as sd_client
from dcc.substance_designer import designer_export as dx


def _fake_publish_file(src, *args, **kwargs):
    return Path("/proj/dest") / Path(src).name


class DesignerConfig(unittest.TestCase):
    def test_build_export_config(self):
        cfg = dx.build_export_config("C:\\tmp\\out", [
            {"package": "/p/rock.sbs", "graph": "Rock", "outputs": ["basecolor"]},
            {"package": "/p/rock.sbs", "graph": "Moss"},
            {"package": "/p/rock.sbs", "graph": "Dirt", "outputs": []},   # no map, only the .sbsar
            {"package": "/p/rock.sbs", "graph": ""},             # no graph: dropped
        ], ".exr", 2048, "16f", maps=True, sbsar=True)
        self.assertEqual(cfg["exportPath"], "C:/tmp/out")
        self.assertEqual(cfg["graphs"], [
            {"package": "/p/rock.sbs", "graph": "Rock", "outputs": ["basecolor"]},
            {"package": "/p/rock.sbs", "graph": "Moss", "outputs": None},
            {"package": "/p/rock.sbs", "graph": "Dirt", "outputs": []}])
        self.assertEqual((cfg["fileFormat"], cfg["size"], cfg["bitDepth"]), ("exr", 2048, "16f"))
        self.assertEqual((cfg["maps"], cfg["sbsar"], cfg["sbs"]), (True, True, False))
        # nothing given: the graph open in Designer, its own size and format
        cfg = dx.build_export_config("/o", None)
        self.assertEqual((cfg["graphs"], cfg["size"], cfg["bitDepth"]), ([], None, None))

    def test_variant_for(self):
        self.assertEqual(dx.variant_for("null", "Rock_Mossy", False), "")
        self.assertEqual(dx.variant_for("null", "Rock_Mossy", True), "ROCKMOSSY")
        self.assertEqual(dx.variant_for("dirty", "Rock", True), "DIRTYROCK")
        self.assertEqual(dx.variant_for("dirty", "Rock", False), "DIRTY")


class PublishDesigner(unittest.TestCase):
    def test_maps_and_sbsar_of_one_graph(self):
        def _export(config):
            out = Path(config["exportPath"])
            (out / "Rock").mkdir()
            for name in ("Rock_basecolor.png", "Rock_normal.png", "Rock_roughness.png"):
                (out / "Rock" / name).write_bytes(b"x")
            (out / "rock.sbsar").write_bytes(b"x")
            return {"ok": True, "files": []}

        with mock.patch("core.paths.get_project_path", return_value=Path(__file__).parent), \
             mock.patch.object(sd_client.designer_client, "export", side_effect=_export) as ex, \
             mock.patch("features.publisher.publish_core.publish_file", side_effect=_fake_publish_file) as pf:
            out = dx.publish_designer("PROJ", "ENV", "TEX", "ROCK", "null",
                                      [{"package": "/p/rock.sbs", "graph": "Rock"}], sbsar=True)
        self.assertTrue(out["ok"], out)
        self.assertEqual(len(out["published"]), 4)
        self.assertTrue(ex.call_args.args[0]["sbsar"])
        names = sorted(c.args[5] for c in pf.call_args_list)
        self.assertEqual(names, ["ENV_TEX_ROCK_BCOL", "ENV_TEX_ROCK_NORM", "ENV_TEX_ROCK_ROUGH",
                                 "ENV_TEX_ROCK_SBSAR"])

    def test_two_graphs_never_share_a_map(self):
        def _export(config):
            out = Path(config["exportPath"])
            for g in ("Rock", "Moss"):
                (out / g).mkdir()
                (out / g / f"{g}_basecolor.png").write_bytes(b"x")
            return {"ok": True, "files": []}

        with mock.patch("core.paths.get_project_path", return_value=Path(__file__).parent), \
             mock.patch.object(sd_client.designer_client, "export", side_effect=_export), \
             mock.patch("features.publisher.publish_core.publish_file", side_effect=_fake_publish_file) as pf:
            out = dx.publish_designer("PROJ", "ENV", "TEX", "ROCK")
        self.assertTrue(out["ok"], out)
        self.assertEqual(sorted(c.args[5] for c in pf.call_args_list),
                         ["ENV_TEX_ROCK_BCOL_MOSS", "ENV_TEX_ROCK_BCOL_ROCK"])

    def test_nothing_asked_and_bridge_failure(self):
        out = dx.publish_designer("PROJ", "ENV", "TEX", "ROCK", maps=False)
        self.assertFalse(out["ok"])
        with mock.patch("core.paths.get_project_path", return_value=Path(__file__).parent), \
             mock.patch.object(sd_client.designer_client, "export",
                               return_value={"ok": False, "error": "Designer closed"}):
            out = dx.publish_designer("PROJ", "ENV", "TEX", "ROCK")
        self.assertEqual(out, {"ok": False, "error": "Designer closed"})


class MarvelousConfig(unittest.TestCase):
    def test_build_export_config(self):
        cfg = mx.build_export_config("/o", "CHAR_CFX_HERO_null", ".abc",
                                     {"avatar": False, "scale": None}, with_zprj=True)
        self.assertEqual(cfg, {"exportPath": "/o", "name": "CHAR_CFX_HERO_null", "format": "abc",
                               "options": {"avatar": False}, "zprj": True})
        self.assertEqual(mx.build_export_config("/o", "X", ".usdc")["format"], "usd")
        # the .zprj itself: no second .zprj
        self.assertFalse(mx.build_export_config("/o", "X", "zprj", with_zprj=True)["zprj"])

    def test_pick_published(self):
        files = [Path("/t/X.abc"), Path("/t/X.zprj"), Path("/t/X.mtl")]
        chosen, warns = mx.pick_published(files, "X", ["abc", "zprj"])
        self.assertEqual(chosen, [Path("/t/X.abc"), Path("/t/X.zprj")])
        self.assertEqual(warns, [])
        chosen, warns = mx.pick_published([Path("/t/a.obj"), Path("/t/X.obj")], "X", ["obj", "zprj"])
        self.assertEqual(chosen, [Path("/t/X.obj")])
        self.assertEqual(len(warns), 2)       # two .obj written + no .zprj


class PublishMarvelous(unittest.TestCase):
    def test_exports_then_ingests_under_the_composed_name(self):
        def _export(config):
            out = Path(config["exportPath"])
            (out / f"{config['name']}.abc").write_bytes(b"x")
            (out / f"{config['name']}.zprj").write_bytes(b"x")
            return {"ok": True, "files": []}

        with mock.patch("core.paths.get_project_path", return_value=Path(__file__).parent), \
             mock.patch.object(md_client.marvelous_client, "export", side_effect=_export), \
             mock.patch("features.publisher.publish_core.publish_file", side_effect=_fake_publish_file) as pf:
            out = mx.publish_marvelous("PROJ", "SEQ010_SH020_CFX_null", "abc", with_zprj=True)
        self.assertTrue(out["ok"], out)
        self.assertEqual([Path(c.args[0]).suffix for c in pf.call_args_list], [".abc", ".zprj"])
        self.assertEqual({c.args[5] for c in pf.call_args_list}, {"SEQ010_SH020_CFX_null"})

    def test_bridge_failure(self):
        with mock.patch("core.paths.get_project_path", return_value=Path(__file__).parent), \
             mock.patch.object(md_client.marvelous_client, "export",
                               return_value={"ok": False, "error": "export abc absent"}):
            out = mx.publish_marvelous("PROJ", "X", "abc")
        self.assertEqual(out, {"ok": False, "error": "export abc absent"})


class Autostart(unittest.TestCase):
    def test_designer_plugin_package(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"FLUX_SD_PLUGINS_DIR": d}):
            self.assertFalse(sd_autostart.is_installed())
            res = sd_autostart.install()
            self.assertTrue(res["success"], res)
            pkg = Path(d) / "flux_designer_bridge"
            self.assertTrue((pkg / "__init__.py").is_file())
            self.assertTrue((pkg / "pluginInfo.json").is_file())
            self.assertTrue(sd_autostart.is_installed())
            self.assertTrue(sd_autostart.uninstall()["success"])
            self.assertFalse(pkg.exists())

    def test_marvelous_script_goes_into_the_plugin_menu(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as plug, \
                mock.patch.dict(os.environ, {"FLUX_MD_SCRIPTS_DIR": d, "FLUX_MD_PLUGINS_DIR": plug}):
            settings = Path(plug) / "pluginSettings.json"
            # a plug-in the artist added by hand stays
            settings.write_text(json.dumps({"plugins": [{"m_PlugInTitle": "Other", "m_SourcePath": "C:/x.py"}],
                                            "version": 2}), encoding="utf-8")
            self.assertTrue(md_autostart.install()["success"])
            self.assertTrue(md_autostart.install()["success"])        # twice: one entry
            script = Path(d) / "flux_marvelous_bridge.py"
            self.assertTrue(script.is_file())
            plugins = json.loads(settings.read_text(encoding="utf-8"))["plugins"]
            self.assertEqual([p["m_PlugInTitle"] for p in plugins], ["Other", "FLUX Bridge"])
            flux = plugins[1]
            self.assertEqual((flux["m_SourcePath"], flux["m_SourceType"], flux["m_BaseMenuTreeByObjectName"]),
                             (str(script), "script", "Plugins / Plug-in"))
            self.assertIn("Plugins > Plug-in > FLUX Bridge", md_autostart.diagnose())
            self.assertTrue(md_autostart.uninstall()["success"])
            self.assertFalse(md_autostart.is_installed())
            plugins = json.loads(settings.read_text(encoding="utf-8"))["plugins"]
            self.assertEqual([p["m_PlugInTitle"] for p in plugins], ["Other"])

    def test_marvelous_unreadable_settings_are_left_alone(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as plug, \
                mock.patch.dict(os.environ, {"FLUX_MD_SCRIPTS_DIR": d, "FLUX_MD_PLUGINS_DIR": plug}):
            settings = Path(plug) / "pluginSettings.json"
            settings.write_text("{not json", encoding="utf-8")
            res = md_autostart.install()
            self.assertTrue(res["success"])                         # the script is there
            self.assertIn("+ADD", res["message"])
            self.assertEqual(settings.read_text(encoding="utf-8"), "{not json")
            # the Python Editor line is a raw string: a bare Windows path is a SyntaxError
            self.assertTrue(md_autostart.python_editor_line().startswith('exec(open(r"'))

    def test_marvelous_script_is_ascii(self):
        # Marvelous may not read the script as UTF-8.
        (Path(md_autostart._PLUGIN_SRC)).read_bytes().decode("ascii")


class MarvelousBridgeScript(unittest.TestCase):
    """The in-app script, with a fake export_api / ApiTypes (no server started)."""

    def setUp(self):
        calls: list = []

        class Option:
            bExportGarment = True
            bExportAvatar = True
            scale = 1.0

        def export_obj(path, option=None):
            calls.append(("obj", path, option))
            return [path]

        def export_zprj(path, thumb):
            calls.append(("zprj", path, thumb))
            return path

        api = types.ModuleType("export_api")
        api.ExportOBJ = export_obj
        api.ExportZPrj = export_zprj
        api.ExportZPac = lambda path: None
        types_mod = types.ModuleType("ApiTypes")
        types_mod.ImportExportOption = Option
        self.calls = calls
        self._mods = mock.patch.dict(sys.modules, {"export_api": api, "ApiTypes": types_mod})
        self._mods.start()
        # The script starts its server on import when the API is there: a state that
        # says "already listening" keeps the test from binding the real port.
        import builtins
        self._state = mock.patch.object(builtins, "_flux_marvelous_bridge",
                                        {"running": True, "stop": False}, create=True)
        self._state.start()
        sys.modules.pop("dcc.marvelous.marvelous_bridge", None)
        from dcc.marvelous import marvelous_bridge as br
        self.br = br
        self._api = mock.patch.object(br, "_export_api", api)
        self._api.start()

    def tearDown(self):
        self._api.stop()
        self._state.stop()
        self._mods.stop()

    def test_formats_and_export(self):
        self.assertEqual(self.br._formats(), ["obj", "zprj"])
        with mock.patch.object(self.br, "_MD_AVAILABLE", True), tempfile.TemporaryDirectory() as d:
            res = self.br._do_export({"exportPath": d, "name": "X", "format": "obj",
                                      "options": {"avatar": False, "scale": 0.1, "thick": True},
                                      "zprj": True})
        self.assertEqual(res["status"], "ok", res)
        kind, _, option = self.calls[0]
        self.assertEqual(kind, "obj")
        self.assertFalse(option.bExportAvatar)
        self.assertEqual(option.scale, 0.1)
        self.assertEqual(self.calls[1][0], "zprj")      # ExportZPrj, not ExportZPac
        self.assertEqual(len(res["files"]), 2)

    def test_missing_format_is_an_error(self):
        with mock.patch.object(self.br, "_MD_AVAILABLE", True), tempfile.TemporaryDirectory() as d:
            res = self.br._do_export({"exportPath": d, "name": "X", "format": "abc"})
        self.assertEqual(res["status"], "error")


    def test_serves_on_the_calling_thread_until_shutdown(self):
        # Marvelous freezes background threads: the loop runs on the caller's thread,
        # pumping the host between requests, and returns on shutdown.
        import socket as _socket
        import threading
        from dcc.json_bridge import send_json_line

        with _socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        pumps = []
        state = {"running": False, "stop": False}
        with mock.patch.object(self.br, "PORT", port), mock.patch.object(self.br, "_state", return_value=state):
            t = threading.Thread(target=self.br.serve, kwargs={"pump": lambda: pumps.append(1) or True})
            t.start()
            for _ in range(100):
                if state["running"]:
                    break
                _time.sleep(0.02)
            ping = send_json_line("127.0.0.1", port, {"action": "ping"}, 5.0)
            self.assertTrue(ping["ok"], ping)
            self.assertTrue(send_json_line("127.0.0.1", port, {"action": "shutdown"}, 5.0)["ok"])
            t.join(5.0)
        self.assertFalse(t.is_alive())
        self.assertFalse(state["running"])
        self.assertTrue(pumps)


class DesignerBridgeScript(unittest.TestCase):
    def test_importable_without_designer(self):
        from dcc.substance_designer import substance_designer_bridge as br
        self.assertFalse(br._SD_AVAILABLE)
        self.assertEqual(br._do_info()["status"], "error")
        self.assertEqual(br._dispatch({"action": "ping"})["status"], "ok")


if __name__ == "__main__":
    unittest.main()
