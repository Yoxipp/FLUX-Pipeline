# test_shot_retake.py - a shotboard idea sent to Production becomes a 'retake' comment (ADR 0083).

from __future__ import annotations

import unittest

from features.production import production_store as store


def _prod():
    return {
        "sequences": [{"id": "s1", "name": "SEQ010", "tasks": [{"id": "t1", "name": "LAYOUT"}]}],
        "shots": [{"id": "h1", "seq_id": "s1", "name": "SHOT010", "inherit_tasks": True,
                   "tasks": [{"id": "t2", "name": "Anim"}],
                   "task_details": {"anim": {"comments": [{"id": "c_old", "text": "old", "kind": "note"}]}},
                   "locked": {"by": "adam", "at": "2026-10-30"}}],
    }


class ShotRetake(unittest.TestCase):
    def test_appended_to_the_existing_detail_key(self):
        p = _prod()
        c = store.add_shot_retake_comment(p, "seq010", "shot010", "ANIM", "  bigger arc  ", "bob", "2026-10-30", "10:00")
        self.assertEqual((c["kind"], c["text"], c["author"]), ("retake", "bigger arc", "BOB"))
        comments = p["shots"][0]["task_details"]["anim"]["comments"]
        self.assertEqual([x["id"] for x in comments], ["c_old", c["id"]])

    def test_inherited_task_and_new_key(self):
        p = _prod()
        store.add_shot_retake_comment(p, "SEQ010", "SHOT010", "layout", "x", "bob", "2026-10-30", "10:00")
        self.assertEqual(p["shots"][0]["task_details"]["LAYOUT"]["comments"][0]["kind"], "retake")
        p["shots"][0]["inherit_tasks"] = False
        with self.assertRaises(ValueError):
            store.add_shot_retake_comment(p, "SEQ010", "SHOT010", "LAYOUT", "x", "bob", "2026-10-30", "10:00")

    def test_unknown_shot_task_or_empty(self):
        p = _prod()
        for seq, shot, task, text in (("SEQ999", "SHOT010", "ANIM", "x"), ("SEQ010", "SHOT999", "ANIM", "x"),
                                      ("SEQ010", "SHOT010", "COMP", "x"), ("SEQ010", "SHOT010", "ANIM", "  ")):
            with self.assertRaises(ValueError):
                store.add_shot_retake_comment(p, seq, shot, task, text, "bob", "2026-10-30", "10:00")


if __name__ == "__main__":
    unittest.main()
