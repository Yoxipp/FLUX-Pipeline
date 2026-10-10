# test_json_atomic_write.py - a failed atomic replace (OneDrive lock) leaves no .flux_tmp_ file.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import json_manager


class AtomicWriteCleanup(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _leftovers(self):
        return [p.name for p in self.dir.iterdir() if p.name.startswith(".flux_tmp_")]

    def test_locked_target_json(self):
        with mock.patch.object(json_manager.os, "replace", side_effect=PermissionError("locked")):
            self.assertFalse(json_manager.write_json(self.dir / "production.json", {"a": 1}))
        self.assertEqual(self._leftovers(), [])

    def test_locked_target_jsonl(self):
        with mock.patch.object(json_manager.os, "replace", side_effect=PermissionError("locked")):
            self.assertFalse(json_manager.write_jsonl(self.dir / "log.jsonl", [{"a": 1}]))
        self.assertEqual(self._leftovers(), [])

    def test_normal_write(self):
        self.assertTrue(json_manager.write_json(self.dir / "p.json", {"a": 1}))
        self.assertEqual(self._leftovers(), [])


if __name__ == "__main__":
    unittest.main()
