# test_jsonl.py — Phase 5 append-only JSONL: concurrency, migration, read-state.

from __future__ import annotations

import json
import multiprocessing as mp
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import core.json_manager as jm
from core.json_manager import append_jsonl, read_jsonl
from features.activity import activity_reader as ar


def _mp_append_worker(args: tuple[str, int, int]) -> None:
    """Top-level (picklable) worker: a separate process appending to the shared log.

    Simulates a second FLUX instance on another machine writing to the same file.
    """
    path, wid, n = args
    backend = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from core.json_manager import append_jsonl as _append
    for i in range(n):
        _append(Path(path), [{"id": f"p{wid:02d}_e{i:03d}", "date": "2026-09-01",
                              "time": "10:00", "read": False}])


class JsonlConcurrencyTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())
        jm.invalidate_cache()

    def test_concurrent_appends_lose_nothing(self):
        """Many writers appending at once → every event present, no torn lines.

        This is the property the old read-modify-write of a JSON array could not
        guarantee (last-writer-wins clobbered concurrent events).
        """
        log = self._tmp / "activite.json"
        writers, per_writer = 20, 50
        total = writers * per_writer

        def work(w: int) -> None:
            for i in range(per_writer):
                ok = append_jsonl(log, [{"id": f"w{w:02d}_e{i:03d}", "date": "2026-09-01",
                                         "time": "10:00", "read": False}])
                assert ok

        with ThreadPoolExecutor(max_workers=writers) as ex:
            list(ex.map(work, range(writers)))

        events = read_jsonl(log)
        self.assertEqual(len(events), total)                       # nothing lost
        self.assertEqual(len({e["id"] for e in events}), total)    # nothing duplicated
        # Every raw line is valid JSON (no interleaving corruption).
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                json.loads(line)

    def test_multiprocess_appends_lose_nothing(self):
        """Separate PROCESSES (≈ separate instances) appending at once → all present.

        This is the real cross-machine property; the OS advisory lock, not the
        in-process lock, is what protects it here.
        """
        log = self._tmp / "activite_mp.json"
        procs, per_proc = 6, 80
        total = procs * per_proc
        try:
            ctx = mp.get_context("spawn")   # match Windows behaviour everywhere
            with ctx.Pool(procs) as pool:
                pool.map(_mp_append_worker, [(str(log), w, per_proc) for w in range(procs)])
        except (OSError, ValueError, RuntimeError) as exc:  # env can't spawn → don't fail CI
            self.skipTest(f"multiprocessing unavailable: {exc}")

        events = read_jsonl(log)
        self.assertEqual(len(events), total)
        self.assertEqual(len({e["id"] for e in events}), total)


class JsonlMigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())
        jm.invalidate_cache()

    def test_legacy_array_is_read_then_migrated_on_append(self):
        log = self._tmp / "activite.json"
        legacy = [
            {"id": "a", "date": "2026-09-01", "time": "10:00", "read": True},
            {"id": "b", "date": "2026-09-02", "time": "11:00", "read": False},
        ]
        log.write_text(json.dumps(legacy), encoding="utf-8")   # old array format

        # Read side handles the legacy array transparently.
        self.assertEqual({e["id"] for e in read_jsonl(log)}, {"a", "b"})

        # First append migrates the file to JSONL, preserving history.
        self.assertTrue(append_jsonl(log, [{"id": "c", "date": "2026-09-03",
                                            "time": "12:00", "read": False}]))
        self.assertEqual([e["id"] for e in read_jsonl(log)], ["a", "b", "c"])

        raw = log.read_text(encoding="utf-8")
        self.assertFalse(raw.lstrip().startswith("["))   # no longer an array
        self.assertEqual(len([ln for ln in raw.splitlines() if ln.strip()]), 3)


class ReadStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())
        self._log = self._tmp / "activite.json"
        jm.invalidate_cache()
        for i in range(3):
            append_jsonl(self._log, [{"id": f"e{i}", "user": "A", "action": "publish",
                                      "project": "P", "date": "2026-09-01",
                                      "time": f"10:0{i}", "read": False}])

    def test_mark_all_and_incremental_unread(self):
        _, unread = ar.get_events_and_unread(limit=50, path=self._log)
        self.assertEqual(unread, 3)

        # Mark all read → companion set-file only; the log is untouched.
        self.assertTrue(ar.mark_all_as_read(path=self._log))
        raw_lines = self._log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len([l for l in raw_lines if l.strip()]), 3)   # log unchanged
        events, unread = ar.get_events_and_unread(limit=50, path=self._log)
        self.assertEqual(unread, 0)
        self.assertTrue(all(e["read"] for e in events))

        # A newly appended event is unread again; marking it individually clears it.
        append_jsonl(self._log, [{"id": "e9", "user": "A", "action": "publish",
                                  "project": "P", "date": "2026-09-02", "time": "09:00",
                                  "read": False}])
        _, unread = ar.get_events_and_unread(limit=50, path=self._log)
        self.assertEqual(unread, 1)
        self.assertTrue(ar.mark_as_read("e9", path=self._log))
        _, unread = ar.get_events_and_unread(limit=50, path=self._log)
        self.assertEqual(unread, 0)

    def test_mark_as_read_unknown_id_returns_false(self):
        self.assertFalse(ar.mark_as_read("does-not-exist", path=self._log))


if __name__ == "__main__":
    unittest.main(verbosity=2)
