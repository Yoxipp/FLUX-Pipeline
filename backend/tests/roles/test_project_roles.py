# test_project_roles.py - project roles junior < artist < lead < supervisor (ADR 0064).
#
# Runs on a temporary FLUX_ROOT: one project folder, studio.json in CONFIG/.

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import studio_config
from features.roles import project_roles as pr


class _Workspace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "DOSSIER_PROJETS" / "PROJ" / "_flux_setup").mkdir(parents=True)
        (self.root / "CONFIG").mkdir()
        self.user = "ADAM"
        patches = [
            mock.patch("core.paths.get_flux_root", return_value=self.root),
            mock.patch("core.config.get_current_user", side_effect=lambda: self.user),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def stored(self) -> dict:
        return json.loads((self.root / "DOSSIER_PROJETS" / "PROJ" / "_flux_setup" / "roles.json")
                          .read_text(encoding="utf-8"))


class CreatorAndDefaultsTests(_Workspace):
    def test_creator_is_supervisor_others_artist(self):
        pr.init_project_roles("PROJ", "adam")
        self.assertEqual(pr.role_of("PROJ", "ADAM"), "supervisor")
        self.assertEqual(pr.role_of("PROJ", "EVA"), "artist")
        self.assertEqual(self.stored()["created_by"], "ADAM")

    def test_no_user_no_role(self):
        pr.init_project_roles("PROJ", "ADAM")
        self.assertIsNone(pr.role_of("PROJ", None))
        self.user = None
        self.assertFalse(pr.can("PROJ", "edit_entity"))
        with self.assertRaises(pr.RoleError):
            pr.require("PROJ", "edit_entity")

    def test_legacy_project_uses_studio_supervisors(self):
        studio_config.write_studio({"legacy_supervisors": ["adam", "MILO"]})
        roles = pr.read_roles("PROJ")
        self.assertTrue(roles["legacy"])
        self.assertEqual(pr.supervisors(roles), ["ADAM", "MILO"])
        self.assertEqual(pr.role_of("PROJ", "DORIAN"), "artist")

    def test_legacy_project_empty_studio_has_no_supervisor(self):
        self.assertEqual(pr.supervisors(pr.read_roles("PROJ")), [])
        self.assertTrue(pr.summary("PROJ", ["ADAM"])["can_claim"])


class MatrixTests(_Workspace):
    def setUp(self):
        super().setUp()
        pr.init_project_roles("PROJ", "ADAM")
        for name, role in (("JUN", "junior"), ("LEA", "lead")):
            pr.set_role("PROJ", name, role, actor="ADAM")

    def test_matrix(self):
        expect = {
            "JUN": {"edit_entity": False, "hard_delete": False, "farm_env": False},
            "EVA": {"edit_entity": True, "hard_delete": False, "farm_env": False, "render_settings": False},
            "LEA": {"edit_entity": True, "hard_delete": True, "farm_env": True, "render_settings": True,
                    "project_settings": True, "reset_password": True, "manage_accounts": False,
                    "delete_project": False},
            "ADAM": {"manage_accounts": True, "delete_project": True},
        }
        for user, actions in expect.items():
            for action, allowed in actions.items():
                self.assertEqual(pr.can("PROJ", action, user), allowed, (user, action))

    def test_require_message_names_roles(self):
        self.user = "JUN"
        with self.assertRaises(pr.RoleError) as ctx:
            pr.require("PROJ", "edit_entity")
        self.assertIn("Artist", str(ctx.exception))
        self.assertIn("Junior", str(ctx.exception))

    def test_unknown_action(self):
        with self.assertRaises(ValueError):
            pr.can("PROJ", "fly")


class SetRoleTests(_Workspace):
    def setUp(self):
        super().setUp()
        pr.init_project_roles("PROJ", "ADAM")
        pr.set_role("PROJ", "LEA", "lead", actor="ADAM")

    def test_lead_manages_junior_artist_lead(self):
        pr.set_role("PROJ", "EVA", "junior", actor="LEA")
        pr.set_role("PROJ", "EVA", "lead", actor="LEA")
        self.assertEqual(pr.role_of("PROJ", "EVA"), "lead")
        pr.set_role("PROJ", "EVA", "artist", actor="LEA")  # a lead demotes another lead
        self.assertEqual(pr.role_of("PROJ", "EVA"), "artist")

    def test_lead_cannot_name_or_touch_supervisor(self):
        with self.assertRaises(pr.RoleError):
            pr.set_role("PROJ", "EVA", "supervisor", actor="LEA")
        with self.assertRaises(pr.RoleError):
            pr.set_role("PROJ", "ADAM", "artist", actor="LEA")

    def test_artist_and_junior_cannot_change_roles(self):
        for actor in ("EVA", "JUN"):
            with self.assertRaises(pr.RoleError):
                pr.set_role("PROJ", "DORIAN", "junior", actor=actor)

    def test_supervisor_demotes_another_supervisor_but_not_the_last(self):
        pr.set_role("PROJ", "MILO", "supervisor", actor="ADAM")
        pr.set_role("PROJ", "ADAM", "artist", actor="MILO")  # the creator demoted
        self.assertEqual(pr.role_of("PROJ", "ADAM"), "artist")
        with self.assertRaises(pr.RoleError) as ctx:
            pr.set_role("PROJ", "MILO", "lead", actor="MILO")
        self.assertIn("dernier", str(ctx.exception))
        self.assertEqual(self.stored()["created_by"], "ADAM")
        self.assertEqual(self.stored()["updated_by"], "MILO")

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            pr.set_role("PROJ", "EVA", "boss", actor="ADAM")
        with self.assertRaises(ValueError):
            pr.set_role("PROJ", "../X", "junior", actor="ADAM")
        with self.assertRaises(pr.RoleError):
            pr.set_role("PROJ", "EVA", "junior", actor="")

    def test_summary_lists_options(self):
        out = pr.summary("PROJ", ["EVA", "ADAM", "LEA"], user="LEA")
        by_name = {m["name"]: m for m in out["members"]}
        self.assertEqual(by_name["EVA"]["assignable"], ["junior", "artist", "lead"])
        self.assertEqual(by_name["ADAM"]["assignable"], [])
        self.assertEqual(out["me"]["role"], "lead")
        self.assertFalse(out["can_claim"])
        sup = pr.summary("PROJ", ["EVA", "ADAM"], user="ADAM")
        # the last supervisor is never offered a lower role
        self.assertEqual({m["name"]: m["assignable"] for m in sup["members"]}["ADAM"], ["supervisor"])


class ClaimTests(_Workspace):
    def test_claim_only_without_supervisor(self):
        pr.claim_supervisor("PROJ")
        self.assertEqual(pr.role_of("PROJ", "ADAM"), "supervisor")
        self.user = "EVA"
        with self.assertRaises(pr.RoleError):
            pr.claim_supervisor("PROJ")

    def test_corrupt_roles_file_is_not_legacy(self):
        path = self.root / "DOSSIER_PROJETS" / "PROJ" / "_flux_setup" / "roles.json"
        path.write_text('{"members": {"EVA": "god", "lea": "lead"}}', encoding="utf-8")
        roles = pr.read_roles("PROJ")
        self.assertEqual(roles["members"], {"LEA": "lead"})
        self.assertFalse(roles["legacy"])


class DepartmentsTests(_Workspace):
    # ADR 0078: departments target TOOL pages; own ones, or anyone's for a lead.
    def setUp(self):
        super().setUp()
        pr.init_project_roles("PROJ", "ADAM")
        pr.set_role("PROJ", "LEA", "lead", actor="ADAM")

    def test_artist_sets_own_and_lead_sets_anyone(self):
        pr.set_departments("PROJ", "EVA", ["anim", "RIG", "ANIM"], actor="EVA")
        self.assertEqual(pr.departments_of("PROJ", "eva"), ["RIG", "ANIM"])
        with self.assertRaises(pr.RoleError):
            pr.set_departments("PROJ", "LEA", ["FX"], actor="EVA")
        pr.set_departments("PROJ", "EVA", ["FX"], actor="LEA")
        self.assertEqual(self.stored()["departments"], {"EVA": ["FX"]})
        pr.set_departments("PROJ", "EVA", [], actor="LEA")
        self.assertNotIn("EVA", self.stored()["departments"])

    def test_unknown_department_and_roles_keep_departments(self):
        with self.assertRaises(ValueError):
            pr.set_departments("PROJ", "EVA", ["COOKING"], actor="ADAM")
        pr.set_departments("PROJ", "EVA", ["MODELING"], actor="ADAM")
        pr.set_role("PROJ", "EVA", "junior", actor="ADAM")
        self.assertEqual(pr.departments_of("PROJ", "EVA"), ["MODELING"])
        row = next(m for m in pr.summary("PROJ", ["EVA"])["members"] if m["name"] == "EVA")
        self.assertEqual((row["departments"], row["can_set_departments"]), (["MODELING"], True))

    def test_old_file_without_departments(self):
        path = self.root / "DOSSIER_PROJETS" / "PROJ" / "_flux_setup" / "roles.json"
        path.write_text('{"members": {"EVA": "lead"}, "departments": {"eva": ["ANIM", "X"], "BOB": "RIG"}}', encoding="utf-8")
        self.assertEqual(pr.read_roles("PROJ")["departments"], {"EVA": ["ANIM"]})
        self.assertEqual(pr.departments_of("PROJ", None), [])


class StudioConfigTests(_Workspace):
    def test_defaults_are_empty(self):
        self.assertEqual(studio_config.read_studio(), studio_config.DEFAULTS)
        self.assertIsNone(studio_config.environment_path())

    def test_link_resolution(self):
        studio_config.write_studio({"environment": "CONFIG/environments/A.json"})
        self.assertEqual(studio_config.environment_path(), self.root / "CONFIG" / "environments" / "A.json")
        studio_config.write_studio({"environment": r"\\server\share\B.json"})
        self.assertEqual(str(studio_config.environment_path()), r"\\server\share\B.json")

    def test_rejects_bad_values(self):
        with self.assertRaises(ValueError):
            studio_config.write_studio({"legacy_supervisors": ["../X"]})
        with self.assertRaises(ValueError):
            studio_config.write_studio({"unknown": 1})


if __name__ == "__main__":
    unittest.main()
