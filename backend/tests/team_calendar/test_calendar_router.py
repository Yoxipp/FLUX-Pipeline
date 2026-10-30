# test_calendar_router.py - a proposal pings the person, the answer pings the author.

from __future__ import annotations

import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import team_calendar


class CalendarRouter(unittest.TestCase):
    def setUp(self):
        self.doc = {"items": []}
        self.user = "adam"
        self.pings: list[tuple[str, str, str]] = []
        app = FastAPI()
        app.include_router(team_calendar.router, prefix="/calendar")
        self.client = TestClient(app)
        patches = [
            mock.patch.object(team_calendar.project_utils, "project_exists", return_value=True),
            mock.patch.object(team_calendar.store, "load", side_effect=lambda p: self.doc),
            mock.patch.object(team_calendar.store, "save", side_effect=lambda p, d: None),
            mock.patch.object(team_calendar, "_user", side_effect=lambda: self.user),
            mock.patch.object(team_calendar, "_ping",
                              side_effect=lambda p, f, t, txt, *notify: self.pings.append((f, t, txt, *notify))),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_proposal_answer_round_trip(self):
        r = self.client.post("/calendar/P/items", json={"title": "Anim", "owner": "milo", "start": "2026-10-05"})
        self.assertEqual(r.status_code, 200, r.text)
        item = r.json()["item"]
        self.assertEqual(item["status"], "proposed")
        self.assertEqual(self.pings[-1][:2], ("adam", "milo"))
        self.assertEqual(self.pings[-1][3:], ("proposal", "2026-10-05", "Anim"))   # title: ADR 0072 include_text

        r = self.client.post(f"/calendar/P/items/{item['id']}/respond", json={"action": "accept"})
        self.assertEqual(r.status_code, 403)          # adam cannot answer for milo

        self.user = "milo"
        r = self.client.post(f"/calendar/P/items/{item['id']}/respond",
                             json={"action": "postpone", "start": "2026-10-08", "end": "2026-10-09"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["item"]["status"], "accepted")
        self.assertEqual(self.pings[-1][:2], ("milo", "adam"))
        self.assertEqual(self.pings[-1][3], "postpone")

    def test_own_commitment_pings_nobody(self):
        r = self.client.post("/calendar/P/items", json={"title": "Rig", "start": "2026-10-05", "end": "2026-10-06"})
        self.assertEqual(r.json()["item"]["status"], "accepted")
        self.assertEqual(self.pings, [])
        r = self.client.post("/calendar/P/items", json={"title": "Rig", "start": "bad"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
