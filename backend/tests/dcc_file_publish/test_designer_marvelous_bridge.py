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
            # Marvelous 2024 mangles " and backslashes pasted in its editor (SyntaxError)
            line = md_autostart.python_editor_line()
            self.assertTrue(line.startswith("exec(open('"), line)
            self.assertNotIn('"', line)
            self.assertNotIn("\\", line)

    def test_marvelous_ctypes_comes_from_the_official_python_zip(self):
        # Marvelous 2024 ships Python 3.7 without _ctypes: the Plug button fetches it.
        import zipfile

        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "python-3.7.9-embed-amd64.zip"
            import io as _io
            stdlib = _io.BytesIO()
            with zipfile.ZipFile(stdlib, "w") as inner:
                inner.writestr("ctypes/__init__.pyc", b"pyc")
                inner.writestr("ctypes/wintypes.pyc", b"pyc")
                inner.writestr("ctypes/test/test_x.pyc", b"no")
                inner.writestr("socket.pyc", b"no")
            with zipfile.ZipFile(src, "w") as zf:
                zf.writestr("_ctypes.pyd", b"pyd")
                zf.writestr("libffi-7.dll", b"dll")
                zf.writestr("_socket.pyd", b"not wanted")
                zf.writestr("python37.zip", stdlib.getvalue())
            with mock.patch.dict(os.environ, {"LOCALAPPDATA": d}):
                self.assertEqual(md_autostart.ensure_pylib(src.as_uri()), "ctypes installe")
                lib = md_autostart.pylib_dir()
                got = sorted(str(p.relative_to(lib)).replace(os.sep, "/") for p in lib.rglob("*") if p.is_file())
                self.assertEqual(got, ["_ctypes.pyd", "ctypes/__init__.pyc", "ctypes/wintypes.pyc", "libffi-7.dll"])
                self.assertEqual(md_autostart.ensure_pylib("file:///nowhere.zip"), "ctypes deja present")
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"LOCALAPPDATA": d}):
            msg = md_autostart.ensure_pylib((Path(d) / "missing.zip").as_uri())
            self.assertIn("non telecharge", msg)                  # no network: never fatal
            self.assertFalse(md_autostart.has_pylib())

    def test_marvelous_script_survives_the_2024_editor(self):
        # ASCII (Marvelous may not read UTF-8), no " nor backslash (its 2024 editor
        # mangles them), no __future__ import (the editor may prepend a line) and
        # Python 3.7 syntax (older embedded Python).
        import ast

        text = Path(md_autostart._PLUGIN_SRC).read_bytes().decode("ascii")
        self.assertNotIn('"', text)
        self.assertNotIn("\\", text)
        self.assertNotIn("__future__", text)
        ast.parse(text, feature_version=(3, 7))


class MarvelousBridgeScript(unittest.TestCase):
    """The in-app script, with a fake export_api / ApiTypes (no server started)."""

    def setUp(self):
        # Fakes shaped like Marvelous 2024 as seen live: pybind11 functions that
        # describe their signatures in __doc__, option classes registered in a module
        # FLUX has to find, a path-only Alembic export that opens a dialog and writes
        # nothing, ExportUSDW refusing a call without its two option objects.
        calls: list = []

        class ImportExportOption:
            def __init__(self):
                self.bExportGarment = True
                self.bExportAvatar = True
                self.scale = 1.0

        class ExportUSDOption:
            pass

        def _write(path):
            Path(path).write_text("x")
            return [path]

        def ExportOBJ(path, option=None):
            calls.append(("obj", path, option))
            return _write(path)
        ExportOBJ.__doc__ = ("ExportOBJ(*args, **kwargs)\nOverloaded function.\n\n"
                             "1. ExportOBJ(arg0: str) -> List[str]\n\n"
                             "2. ExportOBJ(arg0: str, arg1: Marvelous::ImportExportOption) -> List[str]\n")

        def ExportAlembic(path):
            calls.append(("abc-dialog", path, None))       # Marvelous opens its own dialog
            return []
        ExportAlembic.__doc__ = "ExportAlembic(arg0: str) -> List[str]\n"

        def ExportAlembicW(path, option):
            calls.append(("abc", path, option))
            return _write(path)
        ExportAlembicW.__doc__ = "ExportAlembicW(arg0: str, arg1: Marvelous::ImportExportOption) -> List[str]\n"

        def ExportUSDW(path, option, usd_option):
            if not isinstance(option, ImportExportOption) or not isinstance(usd_option, ExportUSDOption):
                raise TypeError("ExportUSDW(): incompatible function arguments")
            calls.append(("usd", path, option))
            return _write(path)
        ExportUSDW.__doc__ = ("ExportUSDW(arg0: str, arg1: Marvelous::ImportExportOption, "
                              "arg2: Marvelous::ExportUSDOption) -> List[str]\n")

        def ExportZPrj(path, thumbnail):
            calls.append(("zprj", path, thumbnail))
            return _write(path)
        ExportZPrj.__doc__ = "ExportZPrj(arg0: str, arg1: bool) -> str\n"

        api = types.ModuleType("export_api")
        for fn in (ExportOBJ, ExportAlembic, ExportAlembicW, ExportUSDW, ExportZPrj):
            setattr(api, fn.__name__, fn)
        api.ExportZPac = lambda path: None
        md_types = types.ModuleType("MarvelousTypes")          # not ApiTypes: found by sweep
        md_types.ImportExportOption = ImportExportOption
        md_types.ExportUSDOption = ExportUSDOption
        self.calls = calls
        self._mods = mock.patch.dict(sys.modules, {"export_api": api, "MarvelousTypes": md_types})
        self._mods.start()
        # The script serves on import when the API is there: a state that says
        # "already running" keeps the import from blocking.
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

    def _export(self, fmt, **extra):
        with mock.patch.object(self.br, "_MD_AVAILABLE", True), tempfile.TemporaryDirectory() as d:
            return self.br._do_export({"exportPath": d, "name": "X", "format": fmt, **extra})

    def test_formats_and_signatures(self):
        self.assertEqual(self.br._formats(), ["abc", "obj", "zprj", "usd"])
        self.assertEqual(self.br._signatures(sys.modules["export_api"].ExportOBJ),
                         [["str"], ["str", "Marvelous::ImportExportOption"]])

    def test_obj_with_options_and_zprj(self):
        res = self._export("obj", options={"avatar": False, "scale": 0.1, "thick": True}, zprj=True)
        self.assertEqual(res["status"], "ok", res)
        kind, _, option = self.calls[0]
        self.assertEqual(kind, "obj")
        self.assertIsNotNone(option)                   # the "with options" overload first
        self.assertFalse(option.bExportAvatar)
        self.assertEqual(option.scale, 0.1)
        self.assertEqual(self.calls[1][0], "zprj")      # ExportZPrj, not ExportZPac
        self.assertEqual(len(res["files"]), 2)

    def test_abc_never_takes_the_dialog_variant(self):
        # 2026-09-26: exporting .abc opened Marvelous' dialog, in the wrong place.
        res = self._export("abc")
        self.assertEqual(res["status"], "ok", res)
        self.assertEqual([c[0] for c in self.calls], ["abc"])

    def test_usd_gets_both_option_objects(self):
        # 2026-09-26: "ExportUSDW(): incompatible function arguments ... invoked with path".
        res = self._export("usd")
        self.assertEqual(res["status"], "ok", res)
        self.assertEqual(self.calls[0][0], "usd")

    def test_a_call_that_writes_nothing_is_an_error(self):
        # 2026-09-26: ".zprj" alone published nothing, Marvelous said it saved.
        def ExportZPrj(path, thumbnail):
            return path
        ExportZPrj.__doc__ = "ExportZPrj(arg0: str, arg1: bool) -> str"
        with mock.patch.object(sys.modules["export_api"], "ExportZPrj", ExportZPrj):
            res = self._export("zprj")
        self.assertEqual(res["status"], "error")
        self.assertIn("rien ecrit", res["msg"])

    def test_missing_format_is_an_error(self):
        res = self._export("fbx")
        self.assertEqual(res["status"], "error")

    def test_inventory_lists_the_signatures(self):
        rows = self.br._inventory()
        self.assertTrue(any(r.startswith("export_api.ExportUSDW[[") for r in rows), rows)

    def _import_api(self):
        # import_api shaped like export_api: a format reader with options, the
        # generic ImportFile, and a reader that refuses (returns False).
        imported: list = []

        def ImportOBJ(path, option):
            imported.append(("obj", path, option))
            return True
        ImportOBJ.__doc__ = "ImportOBJ(arg0: str, arg1: Marvelous::ImportExportOption) -> bool\n"

        def ImportFBX(path):
            return False
        ImportFBX.__doc__ = "ImportFBX(arg0: str) -> bool\n"

        def ImportFile(path):
            imported.append(("file", path, None))
            return True
        ImportFile.__doc__ = "ImportFile(arg0: str) -> bool\n"

        api = types.ModuleType("import_api")
        for fn in (ImportOBJ, ImportFBX, ImportFile):
            setattr(api, fn.__name__, fn)
        api.ImportObjectFromLibrary = lambda path: imported.append(("object", path, None))
        # Inside setUp's sys.modules patch (restored in tearDown): a second patch.dict
        # stopped after it would put the fake export_api back for the next tests.
        sys.modules["import_api"] = api
        return imported

    def _import(self, name):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / name
            path.write_text("x")
            return self.br._do_import({"path": str(path)})

    def test_import_uses_the_format_reader_first(self):
        imported = self._import_api()
        res = self._import("Robe.obj")
        self.assertEqual(res["status"], "ok", res)
        self.assertEqual(res["function"], "ImportOBJ")
        self.assertEqual([c[0] for c in imported], ["obj"])         # not ImportObjectFromLibrary
        self.assertIsNotNone(imported[0][2])

    def test_import_falls_back_to_import_file(self):
        imported = self._import_api()
        res = self._import("Robe.fbx")                                # ImportFBX refuses
        self.assertEqual(res["status"], "ok", res)
        self.assertEqual(res["function"], "ImportFile")
        self.assertEqual([c[0] for c in imported], ["file"])

    def test_import_of_a_missing_file_is_an_error(self):
        self._import_api()
        res = self.br._do_import({"path": "C:/nowhere/Robe.obj"})
        self.assertEqual(res["status"], "error")
        self.assertIn("introuvable", res["msg"])

    def test_import_through_the_mailbox(self):
        imported = self._import_api()
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as src:
            box = Path(d) / "flux_marvelous_bridge"
            box.mkdir()
            f = Path(src) / "Robe.obj"
            f.write_text("x")
            t, state = self._serve_in_thread(box, lambda: True)
            res = md_client.marvelous_client.import_file(str(f))
            self.assertTrue(res["ok"], res)
            self.assertEqual(imported[0][0], "obj")
            md_client.call({"action": "shutdown"}, 5.0)
            t.join(5.0)

    def _serve_in_thread(self, box, pump):
        # The thread plays Marvelous: the loop runs on its caller's thread (Marvelous
        # freezes background threads) and talks to FLUX through the mailbox files
        # (Marvelous 2024 has no _socket).
        import threading

        state = {"running": False, "stop": False}
        patches = [mock.patch.object(self.br, "MAILBOX", str(box)),
                   mock.patch.object(self.br, "_state", return_value=state),
                   mock.patch.dict(os.environ, {"FLUX_MD_MAILBOX_ROOT": str(box.parent)})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        t = threading.Thread(target=self.br.serve, kwargs={"pump": pump}, daemon=True)
        t.start()
        for _ in range(200):
            if (box / "alive.json").exists():
                break
            _time.sleep(0.02)
        return t, state

    def test_serves_through_the_mailbox_until_shutdown(self):
        with tempfile.TemporaryDirectory() as d:
            box = Path(d) / "flux_marvelous_bridge"
            (box).mkdir()
            (box / "old.req").write_text("{}")         # left by a previous session: dropped
            pumps = []
            t, state = self._serve_in_thread(box, lambda: pumps.append(1) or True)
            self.assertFalse((box / "old.req").exists())
            ping = md_client.marvelous_client.ping()
            self.assertTrue(ping["ok"], ping)
            self.assertEqual(ping["mode"], "live")
            info = md_client.marvelous_client.info()
            self.assertTrue(info["ok"], info)
            self.assertEqual(info["formats"], ["abc", "obj", "zprj", "usd"])
            self.assertTrue(md_client.call({"action": "shutdown"}, 5.0)["ok"])
            t.join(5.0)
            self.assertFalse(t.is_alive())
            self.assertFalse(state["running"])
            self.assertTrue(pumps)
            self.assertFalse((box / "alive.json").exists())
            self.assertFalse(md_client.marvelous_client.ping()["ok"])     # gone = not connected

    def test_one_shot_mode_gives_marvelous_back_after_the_export(self):
        # No ctypes (no message pump): Marvelous is busy while the script runs, so it
        # stops by itself once the export is done.
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as out:
            box = Path(d) / "flux_marvelous_bridge"
            with mock.patch.object(self.br, "_make_pump", return_value=None):
                t, state = self._serve_in_thread(box, None)
                self.assertEqual(md_client.marvelous_client.ping()["mode"], "one-shot")
                self.assertTrue(md_client.marvelous_client.info()["ok"])      # info does not stop it
                self.assertTrue(state["running"])
                res = md_client.marvelous_client.export({"exportPath": out, "name": "X", "format": "obj"})
                self.assertTrue(res["ok"], res)
                t.join(5.0)
            self.assertFalse(t.is_alive())

    def test_no_heartbeat_means_not_running(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"FLUX_MD_MAILBOX_ROOT": d}):
            res = md_client.marvelous_client.info()
        self.assertFalse(res["ok"])
        self.assertIn(md_client.NOT_RUNNING, res["error"])

    def test_an_export_in_progress_reads_as_busy(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"FLUX_MD_MAILBOX_ROOT": d}):
            box = Path(d) / "flux_marvelous_bridge"
            box.mkdir()
            (box / "x.work").write_text("{}")
            ping = md_client.marvelous_client.ping()
        self.assertEqual((ping["ok"], ping.get("busy")), (True, True))


class DesignerBridgeScript(unittest.TestCase):
    def test_importable_without_designer(self):
        from dcc.substance_designer import substance_designer_bridge as br
        self.assertFalse(br._SD_AVAILABLE)
        self.assertEqual(br._do_info()["status"], "error")
        self.assertEqual(br._dispatch({"action": "ping"})["status"], "ok")


if __name__ == "__main__":
    unittest.main()
