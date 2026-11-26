# test_lead_validate.py - Valider / Refuser under a task DM are for the project lead or
# supervisor only; "Donner a" keeps its rule (any role). No real Discord, no disk.

from __future__ import annotations

import copy
import unittest
from unittest import mock

from features.notify import dm_actions, store


def _production() -> dict:
    return {"sequences": [{"id": "q_1", "name": "sq010"}],
            "shots": [{"id": "s_1", "seq_id": "q_1", "name": "sh010",
                       "task_details": {"ANIM": {"assignee": "LEA", "status": "WFA"}}}],
            "assets": []}


class LeadValidateTests(unittest.TestCase):
    def setUp(self):
        self.role: str | None = "artist"
        patches = [
            mock.patch.object(store, "user_for_discord", return_value="LEA"),
            mock.patch("features.production.production_store.load_production", side_effect=lambda p: _production()),
            mock.patch("features.production.production_store.save_production", return_value=True),
            mock.patch("features.roles.project_roles.role_of", side_effect=lambda p, u: self.role),
            mock.patch("utils.user_utils.list_users", return_value=["LEA", "MAX"]),
            mock.patch("features.notify.hooks.on_production"),
        ]
        mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.save, self.notify = mocks[2], mocks[-1]

    def _click(self, op: str, values: list | None = None) -> tuple[str, bool]:
        return dm_actions.handle("PROJ", "111", dm_actions.make_id(op, "PROJ", "s_1", "ANIM"), values)

    def _saved(self) -> dict:
        return copy.deepcopy(self.save.call_args.args[1]["shots"][0]["task_details"]["ANIM"])

    def test_junior_and_artist_cannot_validate_nor_refuse(self):
        for role in ("junior", "artist", None):
            for op in ("ok", "no"):
                with self.subTest(role=role, op=op):
                    self.role = role
                    text, done = self._click(op)
                    self.assertFalse(done)              # ephemeral answer, the buttons stay
                    self.assertTrue(text.startswith("FLUX a refuse : "), text)
        self.save.assert_not_called()
        self.notify.assert_not_called()

    def test_lead_and_supervisor_validate_and_refuse(self):
        for role in ("lead", "supervisor"):
            for op, status in (("ok", "APPROVED"), ("no", "RTK")):
                with self.subTest(role=role, op=op):
                    self.role = role
                    self.assertTrue(self._click(op)[1])
                    self.assertEqual(self._saved()["status"], status)

    def test_give_stays_open_to_every_role(self):
        for role in ("junior", "artist", "lead", "supervisor"):
            with self.subTest(role=role):
                self.role = role
                self.assertTrue(self._click("give", ["MAX"])[1])
                self.assertEqual(self._saved()["assignee"], "MAX")
        self.role = None
        self.save.reset_mock()
        self.assertFalse(self._click("give", ["MAX"])[1])
        self.save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
