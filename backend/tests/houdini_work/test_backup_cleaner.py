"""Cleaner of the Houdini backups (ADR 0090 point 8, ADR 0092)."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from features.houdini_work import backup_cleaner as bc

DAY = 86400.0
NOW = 2_000_000_000.0


def _touch(path: Path, age_days: float, data: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    t = NOW - age_days * DAY
    os.utime(path, (t, t))
    return path


class BackupCleanerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.project = base / "PROJ"
        self.root = base / "autosave"
        self.task = self.project / "shot" / "SEQ010" / "SH010" / "fx" / "work" / "houdini" / "FX"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _scan(self, days: int = 14) -> dict:
        return bc.scan(self.project, "PROJ", days=days, now=NOW, root=self.root)

    def _names(self, scan: dict) -> set[str]:
        return {i["name"] for i in scan["items"]}

    def test_old_backups_go_newest_of_scene_stays(self) -> None:
        _touch(self.task / "backup" / "w003_bak1.hip", 40)
        _touch(self.task / "backup" / "w003_bak2.hip", 30)
        _touch(self.task / "backup" / "w003_bak3.hip", 20)     # newest of w003: kept
        _touch(self.task / "backup" / "w002_bak1.hip", 3)      # recent: kept
        scan = self._scan()
        self.assertEqual(self._names(scan), {"w003_bak1.hip", "w003_bak2.hip"})
        self.assertEqual(scan["kept"], 2)

    def test_never_versions_nor_other_files(self) -> None:
        _touch(self.task / "w001.hip", 90)
        _touch(self.task / "w002.hipnc", 80)
        _touch(self.task / "w001.json", 90)
        _touch(self.task / "backup" / "w001.hip", 90)          # a version name, even in backup/
        _touch(self.task / "backup" / "notes.txt", 90)
        _touch(self.task / "cache" / "w001_bak1.hip", 90)       # not backup/ nor the task folder
        _touch(self.project / "assets" / "OGRE" / "backup" / "old_bak1.hip", 90)  # not FLUX Work
        _touch(self.project / "assets" / "OGRE" / "backup" / "old_bak2.hip", 80)
        self.assertEqual(self._scan()["items"], [])

    def test_bak_next_to_versions(self) -> None:
        _touch(self.task / "w004_bak1.hiplc", 60)
        _touch(self.task / "w004_bak2.hiplc", 50)
        self.assertEqual(self._names(self._scan()), {"w004_bak1.hiplc"})

    def test_autosave_copies_of_this_project_only(self) -> None:
        mine = self.root / "PROJ__SEQ010__SH010__FX"
        _touch(mine / "a0.hip", 30)
        _touch(mine / "a1.hip", 20)
        _touch(mine / "a2.hip", 1)
        other = self.root / "OTHER__SEQ010__SH010__FX"
        _touch(other / "a0.hip", 30)
        _touch(other / "a1.hip", 1)
        scan = self._scan()
        self.assertEqual({i["path"] for i in scan["items"]},
                         {"PROJ__SEQ010__SH010__FX/a0.hip", "PROJ__SEQ010__SH010__FX/a1.hip"})
        self.assertTrue(all(i["where"] == "autosave" for i in scan["items"]))

    def test_zero_days_is_off(self) -> None:
        _touch(self.task / "backup" / "w003_bak1.hip", 40)
        _touch(self.task / "backup" / "w003_bak2.hip", 30)
        scan = self._scan(days=0)
        self.assertFalse(scan["enabled"])
        self.assertEqual(scan["items"], [])

    def test_apply_deletes_validated_ids_and_journals(self) -> None:
        old = _touch(self.task / "backup" / "w003_bak1.hip", 40, b"abc")
        _touch(self.task / "backup" / "w003_bak2.hip", 30)
        newest = _touch(self.task / "backup" / "w003_bak3.hip", 20)
        auto_old = _touch(self.root / "PROJ__SEQ010__SH010__FX" / "a0.hip", 30)
        _touch(self.root / "PROJ__SEQ010__SH010__FX" / "a1.hip", 1)
        scan = self._scan()
        ids = [i["id"] for i in scan["items"] if i["name"] in ("w003_bak1.hip", "a0.hip")]
        res = bc.apply(self.project, "PROJ", ids + ["p|" + newest.relative_to(self.project).as_posix()],
                       days=14, now=NOW, root=self.root)
        self.assertEqual(res["deleted"], 2)
        self.assertEqual(res["freed"], 4)
        self.assertEqual(len(res["errors"]), 1)                # the newest: not in the scan
        self.assertFalse(old.exists())
        self.assertFalse(auto_old.exists())
        self.assertTrue(newest.exists())
        self.assertTrue((self.task / "backup" / "w003_bak2.hip").exists())   # not picked
        journal = self.project / ".flux_cleanup" / "houdini_backups" / f"{res['journal']}.json"
        data = json.loads(journal.read_text(encoding="utf-8"))
        self.assertEqual(len(data["deleted"]), 2)

    def test_apply_rejects_forged_ids(self) -> None:
        keep = _touch(self.task / "w001.hip", 90)
        res = bc.apply(self.project, "PROJ", ["p|" + keep.relative_to(self.project).as_posix(),
                                              "p|../../outside.hip"], days=14, now=NOW, root=self.root)
        self.assertEqual(res["deleted"], 0)
        self.assertTrue(keep.exists())
        self.assertEqual(res["journal"], "")

    def test_keep_days_setting(self) -> None:
        with mock.patch.dict(os.environ, {bc.ENV_DAYS: "7"}):
            self.assertEqual(bc.keep_days(), 7)
        with mock.patch.dict(os.environ, {bc.ENV_DAYS: "9999"}):
            self.assertEqual(bc.keep_days(), bc.MAX_DAYS)
        with mock.patch.dict(os.environ, {bc.ENV_DAYS: "abc"}):
            self.assertEqual(bc.keep_days(), bc.DEFAULT_DAYS)
        env = {k: v for k, v in os.environ.items() if k != bc.ENV_DAYS}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(bc.keep_days(), bc.DEFAULT_DAYS)


if __name__ == "__main__":
    unittest.main()
