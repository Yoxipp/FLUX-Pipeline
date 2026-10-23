# P1 (2026-10-22): TD / Team TD boxes of the Flows (01 §7).

from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from flux_flows import rights
from flux_flows.rights import FlowRightsError


class Rights(unittest.TestCase):
    def test_boxes_from_user_data(self) -> None:
        self.assertEqual(rights.rights_from_data("ADAM", {}), {"user": "ADAM", "td": False, "team_td": False})
        self.assertEqual(rights.rights_from_data("ADAM", {"flows_td": True})["td"], True)
        # team_td implies td; only a real True counts.
        self.assertEqual(rights.rights_from_data("ADAM", {"flows_team_td": True}),
                         {"user": "ADAM", "td": True, "team_td": True})
        self.assertFalse(rights.rights_from_data("ADAM", {"flows_td": "yes"})["td"])
        self.assertFalse(rights.rights_from_data(None, None)["td"])

    def test_work_profile_does_not_grant(self) -> None:
        data = {"work_profile": {"flows_td": True, "flows_team_td": True}}
        self.assertFalse(rights.rights_from_data("ADAM", data)["td"])

    def test_table(self) -> None:
        for scope in rights.SCOPE_ORDER:
            self.assertIsNone(rights.required(rights.READ, scope))
            self.assertEqual(rights.required(rights.DRAFT, scope), "td")
            self.assertEqual(rights.required(rights.ADMIN, scope), "team_td")
        self.assertEqual(rights.required(rights.WRITE, "perso"), "td")
        for scope in ("team", "project", "shipped"):
            self.assertEqual(rights.required(rights.WRITE, scope), "team_td")
        with self.assertRaises(ValueError):
            rights.required("fly", "team")
        with self.assertRaises(ValueError):
            rights.required(rights.WRITE, "moon")

    def test_check_raises_403(self) -> None:
        artist = rights.rights_from_data("BOB", {})
        td = rights.rights_from_data("BOB", {"flows_td": True})
        rights.check(artist, rights.READ, "team")
        with self.assertRaises(FlowRightsError) as ctx:
            rights.check(artist, rights.WRITE, "perso")
        self.assertEqual((ctx.exception.status, str(ctx.exception)), (403, "Case TD requise"))
        rights.check(td, rights.WRITE, "perso")
        rights.check(td, rights.DRAFT, "team")
        with self.assertRaises(FlowRightsError) as ctx:
            rights.check(td, rights.WRITE, "project")
        self.assertEqual((str(ctx.exception), ctx.exception.detail), ("Case Team TD requise", {"required": "team_td"}))

    def test_current_rights_uses_local_user(self) -> None:
        with mock.patch("core.config.get_current_user", return_value="ADAM"), \
             mock.patch("utils.user_utils.read_user_data", return_value={"flows_team_td": True}) as read:
            got = rights.current_rights()
        read.assert_called_once_with("ADAM")
        self.assertTrue(got["team_td"])
        with mock.patch("core.config.get_current_user", return_value=None):
            self.assertFalse(rights.current_rights()["td"])

    def test_route_summary(self) -> None:
        from routers import flows as flows_router

        with mock.patch.object(rights, "current_rights", return_value=rights.rights_from_data("ADAM", {"flows_td": True})):
            body = asyncio.run(flows_router.get_rights())
        self.assertTrue(body["td"])
        self.assertEqual(body["can"]["perso"], {"write": True, "draft": True, "admin": False})
        self.assertEqual(body["can"]["team"]["write"], False)
        self.assertIn("pas une securite", body["note_fr"])


if __name__ == "__main__":
    unittest.main()
