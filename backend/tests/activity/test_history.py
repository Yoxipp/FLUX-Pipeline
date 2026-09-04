# test_history.py — Phase 3 hot-file rotation + cold-archive reads.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import core.json_manager as jm
from core.json_manager import read_jsonl
from features.activity import history


def _ev(i: int, month: str = "09") -> dict:
    """A synthetic event with a deterministic, monotonically increasing sort key."""
    return {"id": f"e{i:04d}", "date": f"2026-{month}-01",
            "time": f"{i // 60:02d}:{i % 60:02d}", "read": False}


class RotationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())
        self._archive = self._tmp / "archive"
        # Redirect the archive location to a temp dir (no FLUX_ROOT needed).
        self._orig_dir = history.get_archive_dir
        self._orig_path = history.get_archive_path
        history.get_archive_dir = lambda: self._archive
        history.get_archive_path = lambda stem, ym: self._archive / f"{stem}_{ym}.json"
        jm.invalidate_cache()

    def tearDown(self) -> None:
        history.get_archive_dir = self._orig_dir
        history.get_archive_path = self._orig_path

    def test_hot_file_stays_bounded_and_loses_nothing(self):
        hot = self._tmp / "activite.json"
        total = 50
        for i in range(total):
            self.assertTrue(history.append_events(
                hot, [_ev(i)], "activite", max_events=10, max_days=3650, slack=5))

        hot_events = read_jsonl(hot)
        # Bounded: never exceeds max_events + slack.
        self.assertLessEqual(len(hot_events), 15)

        archived, _ = history.read_archive_events("activite", limit=1000, offset=0)
        hot_ids = {e["id"] for e in hot_events}
        arch_ids = {e["id"] for e in archived}
        # No event lost, none duplicated across hot/cold.
        self.assertEqual(hot_ids | arch_ids, {f"e{i:04d}" for i in range(total)})
        self.assertEqual(hot_ids & arch_ids, set())

    def test_hot_keeps_the_newest_events(self):
        hot = self._tmp / "activite.json"
        for i in range(50):
            history.append_events(hot, [_ev(i)], "activite",
                                  max_events=10, max_days=3650, slack=5)
        hot_events = read_jsonl(hot)
        # The most recent event must remain in the hot file (feed correctness).
        self.assertIn("e0049", {e["id"] for e in hot_events})

    def test_no_rotation_below_threshold(self):
        hot = self._tmp / "activite.json"
        for i in range(12):    # 12 <= max(10)+slack(5)=15 → no rotation
            history.append_events(hot, [_ev(i)], "activite",
                                  max_events=10, max_days=3650, slack=5)
        self.assertFalse(self._archive.exists())

    def test_age_purge_moves_old_events_out_of_hot(self):
        hot = self._tmp / "activite.json"
        # Enough recent events to trip the count threshold, plus stale ones.
        recent = [_ev(i, month="09") for i in range(20)]
        stale = [{"id": f"old{i}", "date": "2020-01-01", "time": "00:00", "read": False}
                 for i in range(2)]
        history.append_events(hot, stale + recent, "activite",
                              max_events=10, max_days=30, slack=5)
        hot_events = read_jsonl(hot)
        # Stale (2020) events must not remain in the hot file.
        self.assertEqual({e["id"] for e in hot_events} & {"old0", "old1"}, set())
        archived, _ = history.read_archive_events("activite", limit=1000, offset=0)
        self.assertTrue({"old0", "old1"} <= {e["id"] for e in archived})

    def test_archive_read_is_newest_first_and_paginates(self):
        hot = self._tmp / "activite.json"
        for i in range(50):
            history.append_events(hot, [_ev(i)], "activite",
                                  max_events=10, max_days=3650, slack=5)
        p1, more1 = history.read_archive_events("activite", limit=5, offset=0)
        p2, _ = history.read_archive_events("activite", limit=5, offset=5)
        self.assertTrue(more1)
        self.assertGreater(p1[0]["id"], p1[-1]["id"])        # newest first
        self.assertEqual({e["id"] for e in p1} & {e["id"] for e in p2}, set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
