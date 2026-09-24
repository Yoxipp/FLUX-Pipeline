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
