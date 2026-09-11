# test_read_state_via_repository.py - read_state routes through the repository now.
#
# End-to-end: mark_read writes and load_read_ids reads, both through the process
# repository (read_state collection = addressed by the companion path). Proves the
# reroute preserves behaviour with no change to the store's public signatures.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from features.activity import read_state


class ReadStateViaRepositoryTests(unittest.TestCase):
    def test_mark_then_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            companion = Path(d) / "activite_read.json"
            self.assertEqual(read_state.load_read_ids(companion), set())
            self.assertTrue(read_state.mark_read(companion, {"e1", "e2"}))
            self.assertEqual(read_state.load_read_ids(companion), {"e1", "e2"})

    def test_mark_prunes_to_live_ids(self):
        with tempfile.TemporaryDirectory() as d:
            companion = Path(d) / "activite_read.json"
            read_state.mark_read(companion, {"e1", "e2", "stale"}, live_ids={"e1", "e2"})
            self.assertEqual(read_state.load_read_ids(companion), {"e1", "e2"})

    def test_is_read_reflects_stored_set(self):
        with tempfile.TemporaryDirectory() as d:
            companion = Path(d) / "chatMentions_read.json"
            read_state.mark_read(companion, {"m1"})
            ids = read_state.load_read_ids(companion)
            self.assertTrue(read_state.is_read({"id": "m1"}, ids))
            self.assertFalse(read_state.is_read({"id": "m2"}, ids))


if __name__ == "__main__":
    unittest.main()
