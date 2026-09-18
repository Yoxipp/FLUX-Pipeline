# The generated usd/ folder of a shot (stage versions, ADR 0020) is not a task
# (2026-09-19: a "USD" task with version folders as subtasks was copied into other shots).

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from features.production.disk_scan import scan_project_shots


class ShotUsdIsNotATask(unittest.TestCase):
    def test_usd_folder_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            shot = project / "shot" / "SEQ001" / "SHOT010"
            (shot / "anim" / "dingo").mkdir(parents=True)
            (shot / "usd" / "SEQ001_SHOT010_v001").mkdir(parents=True)
            (shot / "usd" / "lighting").mkdir(parents=True)
            found = scan_project_shots(project, {"ANIM": "shot/{seq}/{shot}/anim"})
            entry = next(e for e in found if e["shot"] == "SHOT010")
            self.assertEqual([t["token"] for t in entry["tasks"]], ["ANIM"])


if __name__ == "__main__":
    unittest.main()
