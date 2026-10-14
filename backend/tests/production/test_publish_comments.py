# test_publish_comments.py - each publish row gets ITS version's note (not the newest).

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from routers import production

BASE = "CHAR_RIG_UTAH_ALLBODY"
LOGS = [  # newest first, as read_logs returns them
    {"name": BASE, "version": "v002", "date": "2026-10-13", "time": "13:28", "modification": "fix skin"},
    {"name": BASE, "version": "v001", "date": "2026-10-12", "time": "10:00", "modification": "first rig"},
    {"name": BASE + "X", "version": "v009", "date": "2026-10-13", "time": "13:30", "modification": "other base"},
]


def _ev(ver: str, time: str) -> dict:
    return {"file": f"{BASE}_{ver}.ma", "dest_folder": "chars/utah/rig/allbody",
            "date": "2026-10-12" if ver == "v001" else "2026-10-13", "time": time}


class PublishCommentTests(unittest.TestCase):
    def _attach(self, events):
        with mock.patch.object(production, "_cached_modif_logs", return_value=LOGS):
            production._attach_publish_comments(Path("/proj"), {"rig": events})
        return events

    def test_each_version_gets_its_own_note(self):
        # Event times straddle the log minute: the version still matches.
        v1, v2 = self._attach([_ev("v001", "10:01"), _ev("v002", "13:29")])
        self.assertEqual(v1["description"], "first rig")
        self.assertEqual(v2["description"], "fix skin")

    def test_unknown_version_borrows_nothing(self):
        (v3,) = self._attach([_ev("v003", "14:00")])
        self.assertNotIn("description", v3)


if __name__ == "__main__":
    unittest.main()
