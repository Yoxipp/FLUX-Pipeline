# test_calendar_publishes.py - publishes of a project between two dates (hot log + archives).

from __future__ import annotations

import unittest
from unittest import mock

from features.calendar import publishes as pub


def ev(i, d, t, project="P", action="publish", user="adam"):
    return {"id": i, "date": d, "time": t, "user": user, "action": action, "project": project,
            "file": f"f{i}.usd", "dest_folder": ""}


class Publishes(unittest.TestCase):
    def test_range_project_action_and_dedup(self):
        hot = [ev("a", "2026-09-30", "10:00"), ev("b", "2026-10-02", "09:00"),
               ev("c", "2026-09-30", "11:00", project="Q"), ev("d", "2026-09-30", "12:00", action="import"),
               ev("e", "2026-10-09", "08:00")]
        archived = [ev("z", "2026-09-29", "18:00"), ev("a", "2026-09-30", "10:00")]
        with mock.patch.object(pub, "get_all_events", return_value=hot), \
                mock.patch.object(pub, "get_activity_path", return_value="x"), \
                mock.patch.object(pub, "_archived", return_value=archived):
            got = pub.publishes_between("P", "2026-09-28", "2026-10-03")
        self.assertEqual([p["id"] for p in got], ["z", "a", "b"])
        self.assertEqual(got[0]["user"], "adam")

    def test_months_and_bad_range(self):
        self.assertEqual(pub._months("2026-12-30", "2027-01-02"), ["202612", "202701"])
        with self.assertRaises(ValueError):
            pub.publishes_between("P", "2020-01-01", "2026-01-01")


if __name__ == "__main__":
    unittest.main()
