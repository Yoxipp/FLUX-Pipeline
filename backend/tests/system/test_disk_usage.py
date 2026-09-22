# Disk usage scanner: heaviest files under DOSSIER_PROJETS.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock


def _write(p: Path, size: int) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\0" * size)


class DiskUsageScan(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.projects_dir = Path(self._tmp.name)
        _write(self.projects_dir / "PROJ_A" / "a.abc",    2000)
        _write(self.projects_dir / "PROJ_A" / "b.usda",    500)
        _write(self.projects_dir / "PROJ_B" / "big.exr", 10000)
        _write(self.projects_dir / "PROJ_B" / "small.txt", 100)
        # Patch the projects_dir getter used by the scanner.
        patcher = mock.patch(
            "features.system.disk_usage.get_projects_dir",
            return_value=self.projects_dir,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_scan_returns_top_files_sorted_desc(self) -> None:
        from features.system.disk_usage import scan
        r = scan(limit=10)
        self.assertEqual(r["file_count"], 4)
        self.assertEqual(r["total_bytes"], 12600)
        sizes = [f["size"] for f in r["top_files"]]
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        self.assertEqual(r["top_files"][0]["rel"], "PROJ_B/big.exr")
        self.assertEqual(r["top_files"][0]["project"], "PROJ_B")

    def test_scan_limits_top_files(self) -> None:
        from features.system.disk_usage import scan
        r = scan(limit=2)
        self.assertEqual(len(r["top_files"]), 2)
        # Total still counts every file even when the list is truncated.
        self.assertEqual(r["file_count"], 4)

    def test_scan_by_project_aggregates(self) -> None:
        from features.system.disk_usage import scan
        r = scan(limit=10)
        by_p = {row["project"]: row for row in r["by_project"]}
        self.assertEqual(by_p["PROJ_A"]["size"], 2500)
        self.assertEqual(by_p["PROJ_A"]["file_count"], 2)
        self.assertEqual(by_p["PROJ_B"]["size"], 10100)
        # Order: heaviest project first.
        self.assertEqual(r["by_project"][0]["project"], "PROJ_B")

    def test_scan_single_project_scope(self) -> None:
        from features.system.disk_usage import scan
        r = scan(project="PROJ_A", limit=10)
        self.assertEqual(r["file_count"], 2)
        # by_project only populated on a full scan.
        self.assertEqual(r["by_project"], [])
        # Top files are still project-relative under DOSSIER_PROJETS.
        self.assertTrue(all(f["rel"].startswith("PROJ_A/") for f in r["top_files"]))

    def test_scan_missing_project(self) -> None:
        from features.system.disk_usage import scan
        r = scan(project="PROJ_MISSING", limit=10)
        self.assertEqual(r["file_count"], 0)
        self.assertEqual(r["total_bytes"], 0)
        self.assertEqual(r["top_files"], [])


if __name__ == "__main__":
    unittest.main()
