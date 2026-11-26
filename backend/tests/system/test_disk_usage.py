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
        from features.system.disk_usage import refresh
        refresh(author="adam")

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

    def test_scan_reads_index_without_walking(self) -> None:
        from features.system.disk_usage import scan
        _write(self.projects_dir / "PROJ_A" / "new.exr", 99999)
        with mock.patch("os.walk", side_effect=AssertionError("walked")):
            r = scan(limit=10)
        self.assertEqual(r["file_count"], 4)                 # stale until refresh
        self.assertEqual(r["scanned_by"], "adam")
        self.assertIsNotNone(r["scanned_at"])
        self.assertEqual(r["not_indexed"], [])

    def test_refresh_rewrites_index(self) -> None:
        from features.system.disk_usage import refresh, scan
        _write(self.projects_dir / "PROJ_A" / "new.exr", 99999)
        self.assertEqual(refresh(author="bob")["file_count"], 5)
        r = scan(limit=10)
        self.assertEqual(r["top_files"][0]["rel"], "PROJ_A/new.exr")
        self.assertEqual(r["scanned_by"], "bob")

    def test_missing_or_corrupt_index(self) -> None:
        from features.system import pipeline_index
        from features.system.disk_usage import scan
        pipeline_index.index_path(self.projects_dir / "PROJ_A").unlink()
        broken = pipeline_index.index_path(self.projects_dir / "PROJ_B")
        for text in ("{not json", "[]", '{"version": 1}',
                     '{"version":1,"scanned_at":1,"scanned_by":"a","dirs":[],"files":[["x"]]}'):
            broken.write_text(text, encoding="utf-8")
            r = scan(limit=10)
            self.assertEqual(r["file_count"], 0, text)
            self.assertEqual(r["not_indexed"], ["PROJ_A", "PROJ_B"], text)
            self.assertIsNone(r["scanned_at"])

    def test_atomic_write_keeps_previous_index_on_failure(self) -> None:
        from features.system import pipeline_index
        from features.system.disk_usage import refresh
        target = pipeline_index.index_path(self.projects_dir / "PROJ_A")
        before = target.read_bytes()
        with mock.patch("os.replace", side_effect=PermissionError("locked")):
            r = refresh(project="PROJ_A", author="bob")
        self.assertEqual(len(r["errors"]), 1)
        self.assertEqual(r["file_count"], 2)                 # fresh data still shown
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual([p.name for p in target.parent.iterdir()], [target.name])   # no tmp left

    def test_index_does_not_count_itself(self) -> None:
        from features.system.disk_usage import refresh
        self.assertEqual(refresh(author="adam")["file_count"], 4)

    def test_refresh_refuses_paths(self) -> None:
        from features.system.disk_usage import refresh
        for name in ("..", "PROJ_A/..", "../PROJ_A"):
            self.assertEqual(refresh(project=name, author="adam")["file_count"], 0, name)
        self.assertFalse((self.projects_dir.parent / "_flux_setup" / "pipeline_index.json").exists())

    def test_scan_missing_project(self) -> None:
        from features.system.disk_usage import scan
        r = scan(project="PROJ_MISSING", limit=10)
        self.assertEqual(r["file_count"], 0)
        self.assertEqual(r["total_bytes"], 0)
        self.assertEqual(r["top_files"], [])


if __name__ == "__main__":
    unittest.main()
