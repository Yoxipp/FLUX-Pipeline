# Old FLUX files after a shelf reinstall (2026-10-10): listed with a reason, only
# FLUX's own files (never an artist's HDA / shelf), deleted only if a fresh scan lists them.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from features.shelf_manager import shelf_core
from features.shelf_manager import stale_cleanup as sc


def _hda(path: Path, flux: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"INDX ... Sop/flux_importer ..." if flux else b"INDX ... Sop/my_tool ...")
    return path


class HoudiniScan(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.home, self.docs = root / "home" / "otls", root / "docs" / "otls"
        self.staging = root / "staging"
        mock.patch.object(shelf_core, "get_dcc_otls_dirs", return_value=[self.home, self.docs]).start()
        mock.patch.object(shelf_core, "_HDA_STAGING_DIR", self.staging).start()
        self.addCleanup(mock.patch.stopall)
        for d in (self.home, self.docs):
            _hda(d / "flux_importer.hda")
        _hda(self.docs / "flux_shot_switch.hda")                 # name FLUX no longer ships
        _hda(self.docs / "backup" / "flux_importer_bak1.hda")
        _hda(self.docs / "sop_artist_tool.hda", flux=False)     # never FLUX's
        _hda(self.docs / "flux_my_own.hda", flux=False)          # flux_ name, not a FLUX HDA
        _hda(self.staging / "flux_old_name.hda")

    def _scan(self, active):
        with mock.patch.object(sc, "active_houdini_otls", return_value=active):
            return {Path(i["path"]).relative_to(Path(self._tmp.name)).as_posix(): i["reason"]
                    for i in sc.scan("Houdini", "22.0")}

    def test_reasons_with_the_running_houdini_known(self) -> None:
        got = self._scan(self.docs)
        self.assertIn("copie en double", got["home/otls/flux_importer.hda"])
        self.assertIn("n'existe plus", got["docs/otls/flux_shot_switch.hda"])
        self.assertIn("sauvegarde", got["docs/otls/backup/flux_importer_bak1.hda"])
        self.assertIn("hors ligne", got["staging/flux_old_name.hda"])
        self.assertNotIn("docs/otls/flux_importer.hda", got)          # the real one
        self.assertNotIn("docs/otls/sop_artist_tool.hda", got)
        self.assertNotIn("docs/otls/flux_my_own.hda", got)

    def test_houdini_closed_never_calls_a_copy_duplicate(self) -> None:
        got = self._scan(None)
        self.assertNotIn("home/otls/flux_importer.hda", got)
        self.assertIn("docs/otls/flux_shot_switch.hda", got)

    def test_remove_only_what_a_fresh_scan_lists(self) -> None:
        dup = self.home / "flux_importer.hda"
        artist = self.docs / "sop_artist_tool.hda"
        with mock.patch.object(sc, "active_houdini_otls", return_value=self.docs), \
             mock.patch.object(sc, "_forget_in_houdini") as forget:
            out = sc.remove("Houdini", "22.0", [str(dup), str(artist), str(self.docs / "backup" / "flux_importer_bak1.hda")])
        self.assertFalse(dup.exists())
        self.assertTrue(artist.exists())
        self.assertEqual(out["skipped"], [str(artist)])
        self.assertEqual(len(out["removed"]), 2)
        self.assertFalse((self.docs / "backup").exists())            # emptied backup dir dropped
        forget.assert_called_once()


class MayaScan(unittest.TestCase):
    def test_older_flux_shelves_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shelves = Path(tmp)
            for name in ("shelf_Flux.mel", "shelf_Flux_old.mel", "shelf_FluxPipeline.mel", "shelf_MyRig.mel"):
                (shelves / name).write_text("// x", encoding="utf-8")
            with mock.patch.object(shelf_core, "get_dcc_shelf_dir", return_value=shelves):
                got = sorted(Path(i["path"]).name for i in sc.scan("Maya", "2024"))
        self.assertEqual(got, ["shelf_FluxPipeline.mel", "shelf_Flux_old.mel"])

    def test_other_dcc_has_no_rule(self) -> None:
        self.assertEqual(sc.scan("ZBrush", "2024"), [])


if __name__ == "__main__":
    unittest.main()
