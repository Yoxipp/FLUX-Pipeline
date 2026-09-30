# test_production_lock.py - a locked sequence / shot cannot be edited, renamed or deleted.

from __future__ import annotations

import copy
import unittest

from features.production import lock


def _prod():
    return {
        "sequences": [{"id": "s1", "name": "SEQ010"}, {"id": "s2", "name": "SEQ020"}],
        "shots": [
            {"id": "h1", "seq_id": "s1", "name": "SHOT010", "frame_start": 1001},
            {"id": "h2", "seq_id": "s2", "name": "SHOT010", "frame_start": 1001},
        ],
    }


class ProductionLock(unittest.TestCase):
    def test_lock_then_unlock_needs_the_phrase(self):
        p = _prod()
        lock.set_lock(p, "shot", "SEQ010", "SHOT010", True, "adam")
        self.assertEqual(lock.lock_of(p, "shot", "SEQ010", "SHOT010")["by"], "adam")
        with self.assertRaises(PermissionError):
            lock.set_lock(p, "shot", "SEQ010", "SHOT010", False, "bob", "understand?")
        lock.set_lock(p, "shot", "SEQ010", "SHOT010", False, "bob", "Understand")
        self.assertIsNone(lock.lock_of(p, "shot", "SEQ010", "SHOT010"))

    def test_locked_seq_protects_its_shots_and_delete(self):
        p = _prod()
        lock.set_lock(p, "seq", "SEQ010", "", True, "adam")
        with self.assertRaises(lock.LockedError):
            lock.ensure_unlocked(p, "shot", "SEQ010", "SHOT010")
        with self.assertRaises(lock.LockedError):
            lock.ensure_unlocked(p, "seq", "SEQ010")
        lock.ensure_unlocked(p, "shot", "SEQ020", "SHOT010")

    def test_seq_with_a_locked_shot_cannot_be_deleted(self):
        p = _prod()
        lock.set_lock(p, "shot", "SEQ020", "SHOT010", True, "adam")
        with self.assertRaises(lock.LockedError):
            lock.ensure_unlocked(p, "seq", "SEQ020")

    def test_save_restores_edited_and_removed_locked_records(self):
        prev = _prod()
        lock.set_lock(prev, "seq", "SEQ010", "", True, "adam")
        new = copy.deepcopy(prev)
        new["sequences"][0]["name"] = "SEQ999"                 # rename of a locked seq
        new["shots"] = [s for s in new["shots"] if s["id"] != "h1"]   # its shot removed
        new["shots"][0]["frame_start"] = 2001                  # unlocked shot edit kept
        restored = lock.keep_locked(new, prev)
        self.assertEqual(new["sequences"][0]["name"], "SEQ010")
        self.assertIn("h1", [s["id"] for s in new["shots"]])
        self.assertEqual(next(s for s in new["shots"] if s["id"] == "h2")["frame_start"], 2001)
        self.assertEqual(sorted(restored), ["SEQ010", "SHOT010"])

    def test_task_progress_of_a_locked_shot_stays_editable(self):
        prev = _prod()
        lock.set_lock(prev, "shot", "SEQ010", "SHOT010", True, "adam")
        new = copy.deepcopy(prev)
        new["shots"][0]["task_details"] = {"t1": {"status": "done"}}
        new["shots"][0]["frame_start"] = 5
        restored = lock.keep_locked(new, prev)
        self.assertEqual(new["shots"][0]["task_details"], {"t1": {"status": "done"}})
        self.assertEqual(new["shots"][0]["frame_start"], 1001)
        self.assertEqual(restored, ["SHOT010"])

    def test_save_cannot_add_or_drop_a_lock(self):
        prev = _prod()
        lock.set_lock(prev, "shot", "SEQ020", "SHOT010", True, "adam")
        new = copy.deepcopy(prev)
        new["shots"][0]["locked"] = {"by": "x"}   # lock smuggled in a save
        del new["shots"][1]["locked"]             # lock dropped by a stale client
        lock.keep_locked(new, prev)
        self.assertNotIn("locked", new["shots"][0])
        self.assertEqual(new["shots"][1]["locked"]["by"], "adam")


if __name__ == "__main__":
    unittest.main()
