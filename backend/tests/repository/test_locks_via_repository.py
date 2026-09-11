# test_locks_via_repository.py - locks.json routes through the repository (Phase 1a).
#
# End-to-end: load_locks / is_locked / set_lock go through the process repository
# (locks collection = one locks.json per project folder). Proves the reroute keeps
# the on-disk format (a dict {"locked": [...]}), the empty default when absent, the
# path normalisation, and the public signatures.

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.constants import JSON_LOCKS
from features.folder_manager import locks as lk


class LocksViaRepositoryTests(unittest.TestCase):
    def test_load_missing_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(lk.load_locks(Path(d)), [])
            self.assertFalse(lk.is_locked(Path(d), "assets/chara/HERO"))

    def test_set_then_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            project = Path(d)
            ordered = lk.set_lock(project, "assets/chara/HERO/rig", True)
            self.assertEqual(ordered, ["assets/chara/HERO/rig"])
            self.assertTrue(lk.is_locked(project, "assets/chara/HERO/rig"))
            self.assertEqual(lk.load_locks(project), ["assets/chara/HERO/rig"])

    def test_unlock_removes_entry(self):
        with tempfile.TemporaryDirectory() as d:
            project = Path(d)
            lk.set_lock(project, "a/b", True)
            self.assertTrue(lk.is_locked(project, "a/b"))
            remaining = lk.set_lock(project, "a/b", False)
            self.assertEqual(remaining, [])
            self.assertFalse(lk.is_locked(project, "a/b"))

    def test_path_normalisation(self):
        with tempfile.TemporaryDirectory() as d:
            project = Path(d)
            # backslashes and surrounding slashes normalise to the canonical form
            lk.set_lock(project, "\\assets\\props\\A\\", True)
            self.assertTrue(lk.is_locked(project, "assets/props/A"))
            self.assertEqual(lk.load_locks(project), ["assets/props/A"])

    def test_on_disk_format_is_a_dict(self):
        with tempfile.TemporaryDirectory() as d:
            project = Path(d)
            lk.set_lock(project, "a/b", True)
            raw = json.loads((project / JSON_LOCKS).read_text(encoding="utf-8"))
            self.assertIsInstance(raw, dict)
            self.assertEqual(raw, {"locked": ["a/b"]})


if __name__ == "__main__":
    unittest.main()
