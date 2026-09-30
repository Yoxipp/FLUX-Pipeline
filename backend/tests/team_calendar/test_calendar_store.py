# test_calendar_store.py - commitments, proposals and answers of the team calendar.

from __future__ import annotations

import unittest

from features.calendar import calendar_store as cal


def _doc():
    return {"items": []}


class Commitments(unittest.TestCase):
    def test_own_commitment_is_accepted(self):
        d = _doc()
        it = cal.create_item(d, "adam", "Rig horse", "", "2026-10-05", "2026-10-09")
        self.assertEqual((it["owner"], it["status"]), ("adam", "accepted"))

    def test_bad_dates_are_refused(self):
        with self.assertRaises(cal.CalendarError):
            cal.create_item(_doc(), "adam", "x", "adam", "2026-10-09", "2026-10-05")
        with self.assertRaises(cal.CalendarError):
            cal.create_item(_doc(), "adam", "x", "adam", "demain")
        with self.assertRaises(cal.CalendarError):
            cal.create_item(_doc(), "adam", "  ", "adam", "2026-10-09")

    def test_single_day_when_no_end(self):
        it = cal.create_item(_doc(), "adam", "x", "adam", "2026-10-05")
        self.assertEqual(it["end"], "2026-10-05")


class Proposals(unittest.TestCase):
    def setUp(self):
        self.d = _doc()
        self.it = cal.create_item(self.d, "adam", "Anim SHOT010", "milo", "2026-10-05", "2026-10-07")

    def test_proposal_to_someone_else(self):
        self.assertEqual(self.it["status"], "proposed")
        self.assertEqual(self.it["created_by"], "adam")

    def test_only_the_owner_answers(self):
        with self.assertRaises(cal.CalendarForbidden):
            cal.respond(self.d, self.it["id"], "adam", "accept")
        cal.respond(self.d, self.it["id"], "Milo", "accept")   # case-insensitive
        self.assertEqual(self.it["status"], "accepted")

    def test_postpone_moves_later_and_accepts(self):
        cal.respond(self.d, self.it["id"], "milo", "postpone", "2026-10-12", "2026-10-14")
        self.assertEqual((self.it["start"], self.it["end"], self.it["status"]),
                         ("2026-10-12", "2026-10-14", "accepted"))
        with self.assertRaises(cal.CalendarError):
            cal.respond(self.d, self.it["id"], "milo", "postpone", "2026-10-01", "2026-10-02")

    def test_decline(self):
        cal.respond(self.d, self.it["id"], "milo", "decline")
        self.assertEqual(self.it["status"], "declined")
        self.assertEqual([h["action"] for h in self.it["history"]], ["propose", "decline"])

    def test_author_edits_only_while_proposed(self):
        cal.update_item(self.d, self.it["id"], "adam", title="Anim SHOT010 blocking")
        cal.respond(self.d, self.it["id"], "milo", "accept")
        with self.assertRaises(cal.CalendarForbidden):
            cal.update_item(self.d, self.it["id"], "adam", start="2026-10-20")

    def test_progress_needs_an_answer_first(self):
        with self.assertRaises(cal.CalendarError):
            cal.update_item(self.d, self.it["id"], "milo", status="in_progress")
        cal.respond(self.d, self.it["id"], "milo", "accept")
        cal.update_item(self.d, self.it["id"], "milo", status="in_progress")
        self.assertEqual(self.it["status"], "in_progress")
        self.assertEqual(self.it["history"][-1]["action"], "start")

    def test_owner_marks_done_and_either_deletes(self):
        cal.respond(self.d, self.it["id"], "milo", "accept")
        cal.update_item(self.d, self.it["id"], "milo", status="done")
        self.assertEqual(self.it["status"], "done")
        with self.assertRaises(cal.CalendarForbidden):
            cal.delete_item(self.d, self.it["id"], "dorian")
        cal.delete_item(self.d, self.it["id"], "adam")
        self.assertEqual(self.d["items"], [])


if __name__ == "__main__":
    unittest.main()
