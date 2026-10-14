# Retake 04: personal notifications (Self / Global) per artist and per project.

from __future__ import annotations

import unittest

from features.activity.notifications import (
    assignments, followed_shots, personal_feed, reason_for, shot_follow_key,
)

PROJECT = "PROJ"

PRODUCTION = {
    "sequences": [{"id": "s1", "name": "SEQ010"}],
    "shots": [
        {"id": "a", "seq_id": "s1", "name": "SHOT010",
         "tasks": [{"name": "ANIM", "type_tokens": ["ANIM"]}],
         "task_details": {"ANIM": {"assignee": "bob"}}},
        {"id": "b", "seq_id": "s1", "name": "SHOT020",
         "tasks": [{"name": "LIGHTING", "type_tokens": ["LIGHT"]}],
         "task_details": {"LIGHTING|null": {"assignee": "ALICE"}}},
    ],
    "assets": [{"id": "c", "class": "CHAR", "name": "UTAH", "tasks": [{"name": "GEO", "type_tokens": []}]}],
}


def _ev(file: str, user: str = "CARL", project: str = PROJECT, time: str = "10:00:00", action: str = "publish") -> dict:
    return {"id": f"{file}{time}{project}", "user": user, "action": action, "file": file,
            "project": project, "date": "2026-10-08", "time": time}


EVENTS = [
    _ev("SEQ010_SHOT010_ANIM_null_v002.ma", time="10:05:00"),
    _ev("SEQ010_SHOT020_LIGHT_null_v001.usd", time="10:04:00"),
    _ev("CHAR_UTAH_GEO_null_v003.usd", time="10:03:00"),
    _ev("SEQ010_SHOT010_ANIM_null_v002.ma", project="OTHER", time="10:02:00"),
]

ALICE_FAVS = [shot_follow_key(PROJECT, "SEQ010", "SHOT010"), shot_follow_key(PROJECT, "SEQ099", "SHOT999")]
BOB_FAVS = [f"{PROJECT}|CHAR/UTAH|GEO", shot_follow_key("OTHER", "SEQ010", "SHOT010")]


class Notifications(unittest.TestCase):
    def _feed(self, user: str, favs: list[str], scope: str = "self") -> list[dict]:
        return personal_feed(EVENTS, project=PROJECT, scope=scope, favorites=favs,
                             assigned=assignments(PRODUCTION, user))

    def test_assignments_by_task_name_and_type_tokens(self) -> None:
        self.assertEqual(assignments(PRODUCTION, "Bob"), {("SEQ010/SHOT010", "ANIM")})
        self.assertEqual(assignments(PRODUCTION, "alice"),
                         {("SEQ010/SHOT020", "LIGHTING"), ("SEQ010/SHOT020", "LIGHT")})
        self.assertEqual(assignments(PRODUCTION, ""), set())

    def test_two_artists_see_their_own_events_only(self) -> None:
        alice = {(e["file"], e["reason"]) for e in self._feed("ALICE", ALICE_FAVS)}
        bob = {(e["file"], e["reason"]) for e in self._feed("BOB", BOB_FAVS)}
        self.assertEqual(alice, {("SEQ010_SHOT010_ANIM_null_v002.ma", "followed_shot"),
                                 ("SEQ010_SHOT020_LIGHT_null_v001.usd", "assigned")})
        self.assertEqual(bob, {("SEQ010_SHOT010_ANIM_null_v002.ma", "assigned"),
                               ("CHAR_UTAH_GEO_null_v003.usd", "favorite")})

    def test_other_project_never_leaks(self) -> None:
        # Bob follows SHOT010 of OTHER: not an event of PROJ, and OTHER events are never returned.
        for scope in ("self", "global"):
            self.assertTrue(all(e["project"] == PROJECT for e in self._feed("BOB", BOB_FAVS, scope)))
        self.assertIsNone(reason_for(EVENTS[3], project=PROJECT, favorites=BOB_FAVS, assigned=set()))

    def test_global_keeps_every_project_event_with_reason(self) -> None:
        feed = self._feed("ALICE", ALICE_FAVS, "global")
        self.assertEqual(len(feed), 3)
        self.assertEqual([e["reason"] for e in feed], ["followed_shot", "assigned", None])

    def test_empty_states(self) -> None:
        self.assertEqual(self._feed("NOBODY", []), [])
        self.assertEqual(followed_shots([], PROJECT), [])

    def test_followed_shots_of_project_only_and_unique(self) -> None:
        favs = ALICE_FAVS + [ALICE_FAVS[0], f"{PROJECT}|CHAR/UTAH|GEO"]
        self.assertEqual(followed_shots(favs, PROJECT), [("SEQ010", "SHOT010"), ("SEQ099", "SHOT999")])
        self.assertEqual(followed_shots(favs, "OTHER"), [])

    def test_duplicate_lines_give_one_notification(self) -> None:
        dup = [_ev("SEQ010_SHOT010_ANIM_null_v002.ma", time="10:05:01"),
               _ev("SEQ010_SHOT010_ANIM_null_v002.ma", time="10:05:40")]
        feed = personal_feed(dup, project=PROJECT, scope="self", favorites=ALICE_FAVS, assigned=set())
        self.assertEqual(len(feed), 1)

    def test_followed_shot_does_not_match_an_asset(self) -> None:
        favs = [f"{PROJECT}|CHAR/UTAH|*"]
        self.assertIsNone(reason_for(EVENTS[2], project=PROJECT, favorites=favs, assigned=set()))


if __name__ == "__main__":
    unittest.main()
