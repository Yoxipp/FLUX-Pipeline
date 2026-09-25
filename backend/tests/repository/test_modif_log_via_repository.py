# test_modif_log_via_repository.py - modif_log routes through the repository (Phase 1a).
#
# End-to-end: append_log writes and read_logs / get_logs_for_file read, through the
# process repository (modif_log collection = a JSON-array file per publish folder).
# Proves the reroute keeps the on-disk format (a JSON array) and public signatures.

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.constants import JSON_MODIF_LOG
from features.publisher import modif_log


# Pin the JSON backend so a dev config flipped to sqlite does not fail these tests.
from tests.repository._backend import setUpModule, tearDownModule  # noqa: E402,F401


class ModifLogViaRepositoryTests(unittest.TestCase):
    def test_append_then_read_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            self.assertEqual(modif_log.read_logs(folder), [])
            self.assertTrue(modif_log.append_log(folder, "CHAR_RIG_A_LAST.mb", "v001", "first", "adam"))
            self.assertTrue(modif_log.append_log(folder, "CHAR_RIG_A_LAST.mb", "v002", "tweak", "adam"))
            logs = modif_log.read_logs(folder)
            self.assertEqual(len(logs), 2)
            self.assertEqual({e["version"] for e in logs}, {"v001", "v002"})

    def test_on_disk_format_stays_a_json_array(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            modif_log.append_log(folder, "N_LAST.mb", "v001", "m", "adam")
            raw = json.loads((folder / JSON_MODIF_LOG).read_text(encoding="utf-8"))
            self.assertIsInstance(raw, list)
            self.assertEqual(raw[0]["name"], "N_LAST.mb")

    def test_get_logs_for_file_filters_by_prefix(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            modif_log.append_log(folder, "CHAR_RIG_A_LAST.mb", "v001", "a", "adam")
            modif_log.append_log(folder, "PROP_GEO_B_LAST.mb", "v001", "b", "adam")
            hits = modif_log.get_logs_for_file(folder, "CHAR_RIG_A")
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["name"], "CHAR_RIG_A_LAST.mb")


if __name__ == "__main__":
    unittest.main()
