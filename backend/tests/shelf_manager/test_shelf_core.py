# Shelf Manager: the Houdini shelf installs the FLUX HDAs too (non-blocking), and
# removing the shelf keeps them (the autostart still uses them).

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from features.shelf_manager import shelf_core


class HoudiniShelfHdas(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.toolbar = Path(self._tmp.name) / "houdini21.0" / "toolbar"
        patcher = mock.patch.object(shelf_core, "get_dcc_shelf_dir", return_value=self.toolbar)
        patcher.start()
        self.addCleanup(patcher.stop)
        # Never reach a real open Houdini from the tests.
        self.reload = mock.patch.object(shelf_core, "_reload_houdini_shelf", return_value=[]).start()
        self.addCleanup(mock.patch.stopall)

    def test_install_reloads_the_shelf_in_open_houdini(self) -> None:
        self.reload.return_value = [48885]
        with mock.patch.object(shelf_core, "install_hdas", return_value=(True, "ok")):
            ok, msg = shelf_core.install_shelf("Houdini", "21.0")
        self.reload.assert_called_once_with(self.toolbar / "Flux.shelf")
        self.assertIn("shelf rechargee dans Houdini :48885", msg)

    def test_reload_targets_only_connected_sessions(self) -> None:
        mock.patch.stopall()
        sent = []

        class _Client:
            def __init__(self, port):
                self.port = port

            def run(self, code, timeout):
                sent.append((self.port, code))
                return {"ok": True, "result": self.port == 48885}
        with mock.patch("core.dcc_instances.scan_instances",
                        return_value=[{"port": 48884, "connected": True}, {"port": 48885, "connected": True},
                                      {"port": 48886, "connected": False}]), \
             mock.patch("dcc.houdini.client.HoudiniClient", _Client):
            done = shelf_core._reload_houdini_shelf(Path(r"C:\prefs\houdini22.0\toolbar\Flux.shelf"))
        self.assertEqual(done, [48885])
        self.assertEqual([p for p, _ in sent], [48884, 48885])
        self.assertIn("_FLUX_SHELF = 'C:/prefs/houdini22.0/toolbar/Flux.shelf'", sent[0][1])
        compile(sent[0][1], "<reload>", "exec")

    def test_install_also_installs_hdas(self) -> None:
        with mock.patch.object(shelf_core, "install_hdas", return_value=(True, "HDAs installed → otls")) as hdas:
            ok, msg = shelf_core.install_shelf("Houdini", "21.0")
        hdas.assert_called_once_with("21.0")
        self.assertTrue(ok)
        self.assertTrue((self.toolbar / "Flux.shelf").is_file())
        self.assertIn("HDAs installed", msg)

    def test_hda_failure_does_not_fail_shelf(self) -> None:
        with mock.patch.object(shelf_core, "install_hdas", return_value=(False, "no staged HDA")):
            ok, msg = shelf_core.install_shelf("Houdini", "21.0")
        self.assertTrue(ok)
        self.assertTrue((self.toolbar / "Flux.shelf").is_file())
        self.assertIn("HDA non installes", msg)

    def test_hda_exception_does_not_fail_shelf(self) -> None:
        with mock.patch.object(shelf_core, "install_hdas", side_effect=RuntimeError("boom")):
            ok, msg = shelf_core.install_shelf("Houdini", "21.0")
        self.assertTrue(ok)
        self.assertIn("boom", msg)

    def test_remove_keeps_hdas(self) -> None:
        with mock.patch.object(shelf_core, "install_hdas", return_value=(True, "ok")):
            shelf_core.install_shelf("Houdini", "21.0")
        with mock.patch.object(shelf_core, "remove_hdas") as remove_hdas:
            ok, _ = shelf_core.remove_shelf("Houdini", "21.0")
        self.assertTrue(ok)
        remove_hdas.assert_not_called()
        self.assertFalse((self.toolbar / "Flux.shelf").exists())


class HdaBackupPurge(unittest.TestCase):
    def test_only_flux_backups_are_removed(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            otls = Path(d) / "otls"
            backup = otls / "backup"
            backup.mkdir(parents=True)
            for name in ("flux_anim_bak1.hda", "flux_importer_lop_bak12.hda"):
                (backup / name).write_bytes(b"x")
            (backup / "studio_tool_bak1.hda").write_bytes(b"x")
            (otls / "flux_anim.hda").write_bytes(b"x")
            self.assertEqual(shelf_core.purge_hda_backups([otls, Path(d) / "missing"]), 2)
            self.assertEqual([f.name for f in backup.iterdir()], ["studio_tool_bak1.hda"])
            self.assertTrue((otls / "flux_anim.hda").exists())

    def test_empty_backup_folder_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            backup = Path(d) / "backup"
            backup.mkdir()
            (backup / "flux_shot_bak3.hda").write_bytes(b"x")
            shelf_core.purge_hda_backups([Path(d)])
            self.assertFalse(backup.exists())


if __name__ == "__main__":
    unittest.main()


class LiveHdaBuild(unittest.TestCase):
    """2026-09-25: after a reinstall FLUX Lighting stayed empty and FLUX Import kept
    its old + / -. One failed build used to drop EVERY HDA onto its old staged copy
    and still report "installed"."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.otls = Path(self._tmp.name) / "houdini22.0" / "otls"
        staging = mock.patch.object(shelf_core, "_HDA_STAGING_DIR", Path(self._tmp.name) / "staging")
        staging.start()
        self.addCleanup(staging.stop)
        prefer = mock.patch.object(shelf_core, "_prefer_built_definitions", return_value=[])
        self.prefer = prefer.start()
        # Never ask a real open Houdini which prefs it reads.
        active = mock.patch("features.shelf_manager.stale_cleanup.active_houdini_otls", return_value=None)
        active.start()
        self.addCleanup(active.stop)
        self.addCleanup(prefer.stop)

    def _fake_import(self, failing: str = ""):
        def builder_for(func_name: str, module: str):
            def build(path: str) -> dict:
                if module.endswith(failing) and failing:
                    return {"ok": False, "error": "boom " + module}
                Path(path).write_text(module + ":" + func_name)
                return {"ok": True}
            return build

        class _Mod:
            def __init__(self, name: str) -> None:
                self.name = name

            def __getattr__(self, func: str):
                return builder_for(func, self.name)

        return lambda name: _Mod(name)

    def test_every_hda_is_built_and_preferred(self) -> None:
        with mock.patch("importlib.import_module", side_effect=self._fake_import()):
            ok, msg = shelf_core._build_hdas_live([self.otls])
        self.assertTrue(ok, msg)
        names = {p.name for p in self.otls.glob("*.hda")}
        self.assertEqual(names, {f for _, f, _, _ in shelf_core._HDA_BUILDS})
        # The exporter exists in the three contexts.
        self.assertTrue({"flux_exporter.hda", "flux_exporter_lop.hda", "flux_exporter_obj.hda"} <= names)
        expected = self.prefer.call_args[0][0]
        self.assertEqual(len(expected), len(shelf_core._HDA_BUILDS))

    def test_one_failure_is_reported_and_others_still_built(self) -> None:
        with mock.patch("importlib.import_module", side_effect=self._fake_import("flux_lighting_hda")):
            ok, msg = shelf_core._build_hdas_live([self.otls])
        self.assertFalse(ok)
        self.assertIn("flux_lighting", msg)
        self.assertIn("boom", msg)
        self.assertFalse((self.otls / "flux_lighting.hda").exists())
        self.assertTrue((self.otls / "flux_crowd.hda").exists())

    def test_failed_live_build_is_not_reported_as_installed(self) -> None:
        with mock.patch.object(shelf_core, "get_dcc_otls_dirs", return_value=[self.otls]), \
             mock.patch.object(shelf_core, "_build_hdas_live", return_value=(False, "ECHEC : flux_lighting")), \
             mock.patch("dcc.houdini.client.houdini_client.is_connected", return_value=True):
            ok, msg = shelf_core.install_hdas("22.0")
        self.assertFalse(ok)
        self.assertIn("flux_lighting", msg)

    def test_old_definitions_are_named(self) -> None:
        self.prefer.return_value = [
            {"type": "Lop/flux_lighting", "ok": True, "others": ["C:/old/otls/flux_lighting.hda"]},
            {"type": "Sop/flux_importer", "ok": False, "error": "definition FLUX non chargee", "others": []},
        ]
        with mock.patch("importlib.import_module", side_effect=self._fake_import()):
            ok, msg = shelf_core._build_hdas_live([self.otls])
        self.assertIn("C:/old/otls/flux_lighting.hda", msg)
        self.assertIn("Sop/flux_importer : definition FLUX non chargee", msg)


class InstallIntoTheReadPrefs(unittest.TestCase):
    """2026-10-10: Houdini open -> the HDAs go only where it reads them; the copies
    elsewhere become duplicates the Shelf Manager offers to delete."""

    def test_open_houdini_gets_one_install_closed_gets_every_dir(self) -> None:
        dirs = [Path("C:/home/houdini22.0/otls"), Path("C:/docs/houdini22.0/otls")]
        with mock.patch.object(shelf_core, "get_dcc_otls_dirs", return_value=dirs), \
             mock.patch.object(shelf_core, "purge_hda_backups"), \
             mock.patch("dcc.houdini.client.houdini_client.is_connected", return_value=True), \
             mock.patch.object(shelf_core, "_build_hdas_live", return_value=(True, "ok")) as build:
            with mock.patch("features.shelf_manager.stale_cleanup.active_houdini_otls", return_value=dirs[1]):
                shelf_core.install_hdas("22.0")
            build.assert_called_with([dirs[1]])
            with mock.patch("features.shelf_manager.stale_cleanup.active_houdini_otls", return_value=None):
                shelf_core.install_hdas("22.0")
            build.assert_called_with(dirs)
