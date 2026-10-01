# FLUX uninstaller cleanup (features/system/uninstall.py): removes what FLUX added to
# the DCCs, keeps the user's own content. Every path lives in a temp dir.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dcc.houdini import autostart as houdini

BLOCK = f"{houdini._BLOCK_BEGIN}\nimport flux_houdini_server\n{houdini._BLOCK_END}\n"


def _write(p: Path, text: str = "x") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


class HoudiniPurge(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "home"
        self.docs = Path(tmp.name) / "docs"
        for target, value in (("pathlib.Path.home", self.home),
                              ("dcc.houdini.autostart._get_documents_dir", self.docs)):
            p = mock.patch(target, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        env = mock.patch.dict("os.environ", {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        import os
        os.environ.pop("HOUDINI_USER_PREF_DIR", None)

    def test_flux_only_files_go_user_content_stays(self) -> None:
        prefs = self.home / "houdini22.0"
        only_flux = _write(prefs / "scripts" / "123.py", "\n" + BLOCK)
        mixed = _write(prefs / "scripts" / "456.py", "print('mine')\n" + BLOCK)
        rc = _write(prefs / "python3.13libs" / "pythonrc.py", BLOCK)
        server = _write(prefs / "scripts" / "flux_houdini_server.py")
        pkg = _write(prefs / "packages" / "flux.json", "{}")
        hda = _write(prefs / "otls" / "flux_importer.hda")
        bak = _write(prefs / "otls" / "backup" / "flux_importer_bak1.hda")
        user_hda = _write(prefs / "otls" / "my_tool.hda")
        shelf = _write(prefs / "toolbar" / "Flux.shelf")
        _write(prefs / "jump.pref", "$FLUX/\n$FLUX/DOSSIER_PROJETS/\nD:/mine/\n")

        self.assertIn(prefs, houdini.all_user_prefs_dirs())
        self.assertTrue(houdini.find_traces(prefs))
        houdini.purge_prefs_dir(prefs)

        for gone in (only_flux, rc, server, pkg, hda, bak, shelf):
            self.assertFalse(gone.exists(), gone)
        self.assertEqual(mixed.read_text(encoding="utf-8").strip(), "print('mine')")
        self.assertTrue(user_hda.exists())
        self.assertEqual((prefs / "jump.pref").read_text(encoding="utf-8").strip(), "D:/mine/")
        # Folders FLUX created and left empty are gone; the user's ones stay.
        self.assertFalse((prefs / "packages").exists())
        self.assertFalse((prefs / "python3.13libs").exists())
        self.assertTrue((prefs / "otls").exists())
        self.assertEqual(houdini.find_traces(prefs), [])

    def test_every_version_and_root_is_swept(self) -> None:
        a = _write(self.home / "houdini21.0" / "scripts" / "123.py", BLOCK)
        b = _write(self.docs / "houdini20.5" / "scripts" / "123.py", BLOCK)
        _write(self.home / "houdini_not_a_version" / "scripts" / "123.py", BLOCK)
        from features.system import uninstall
        uninstall._remove_houdini()
        self.assertFalse(a.exists())
        self.assertFalse(b.exists())
        self.assertTrue((self.home / "houdini_not_a_version" / "scripts" / "123.py").exists())


class StartupFilesAndSteps(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_empty_startup_file_deleted_user_one_kept(self) -> None:
        from features.system import uninstall
        empty = _write(self.root / "2024" / "scripts" / "userSetup.py", "\n\n")
        mine = _write(self.root / "scripts" / "userSetup.py", "import my_rig\n")
        with mock.patch.object(uninstall, "_startup_files", return_value=[empty, mine]):
            removed = uninstall._drop_empty_startup_files()
        self.assertEqual(removed, [str(empty)])
        self.assertTrue(mine.exists())

    def test_one_failing_step_does_not_stop_the_others(self) -> None:
        from features.system import uninstall
        broken = mock.Mock()
        broken.uninstall.side_effect = RuntimeError("boom")
        ok = mock.Mock()
        ok.uninstall.return_value = {"success": True}
        with mock.patch.object(uninstall, "_autostart", side_effect=lambda m: broken if "maya" in m else ok), \
             mock.patch.object(uninstall, "_remove_houdini", return_value=[]), \
             mock.patch.object(uninstall, "_drop_empty_startup_files", return_value=[]), \
             mock.patch.object(uninstall, "_remove_maya_shelves", return_value=[]), \
             mock.patch.object(uninstall, "_remove_zbrush_ui", return_value=[]), \
             mock.patch.object(uninstall, "_remove_painter_presets", return_value=[]), \
             mock.patch.object(uninstall, "_remove_marvelous_pylib", return_value="absent"), \
             mock.patch.object(uninstall, "_remove_temp", return_value=[]), \
             mock.patch.object(uninstall, "_exe", return_value=None):
            report = uninstall.run_cleanup()
        by_step = {r["step"]: r for r in report}
        self.assertFalse(by_step["maya"]["ok"])
        self.assertTrue(by_step["nuke"]["ok"])
        self.assertTrue(by_step["temp"]["ok"])
        ok.uninstall.assert_called()

    def test_painter_edited_preset_is_kept(self) -> None:
        from dcc.substance_painter import presets
        bundled = self.root / "bundled"
        dest = self.root / "painter"
        _write(bundled / "FLUX_A.spexp", "a")
        _write(bundled / "FLUX_B.spexp", "b")
        same = _write(dest / "FLUX_A.spexp", "a")
        edited = _write(dest / "FLUX_B.spexp", "edited by the artist")
        with mock.patch.object(presets, "_BUNDLED_DIR", bundled), \
             mock.patch.object(presets, "painter_presets_dir", return_value=dest):
            removed = presets.remove_presets()
        self.assertEqual(removed, [str(same)])
        self.assertTrue(edited.exists())

    def test_plan_lists_what_is_kept(self) -> None:
        from features.system import uninstall
        with mock.patch("dcc.houdini.autostart.all_user_prefs_dirs", return_value=[]), \
             mock.patch.object(uninstall, "_AUTOSTART_MODULES", {}), \
             mock.patch("features.shelf_manager.shelf_core.get_installed_versions", return_value=[]), \
             mock.patch("features.shelf_manager.zbrush_ui.get_versions", return_value=[]), \
             mock.patch("dcc.substance_painter.presets.find_installed_presets", return_value=[]), \
             mock.patch.object(uninstall, "app_data_dirs", return_value=[]), \
             mock.patch.object(uninstall, "_temp_traces", return_value=[]):
            result = uninstall.plan()
        self.assertEqual(result["remove"], [])
        self.assertTrue(any("Python" in k for k in result["keep"]))


if __name__ == "__main__":
    unittest.main()
