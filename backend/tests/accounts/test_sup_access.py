# test_sup_access.py - supervisor entry without a password, bound to the active project.
# Runs on a temporary root and an in-memory prefs dict: nothing touches the real workspace.

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from features.accounts import passwords, sup_access
from features.roles import project_roles as pr
from utils import user_utils as uu


class _Studio(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.users = self.root / "USER"
        for name in ("SUP", "BOB", "EVA"):
            (self.users / name).mkdir(parents=True)
        for project in ("PROJ", "OTHER"):
            (self.root / "DOSSIER_PROJETS" / project).mkdir(parents=True)
        self.prefs: dict = {"last_project": "PROJ"}
        self.active = {"name": "SUP"}
        patches = [
            mock.patch("core.paths.get_flux_root", return_value=self.root),
            mock.patch("core.paths.get_users_dir", return_value=self.users),
            mock.patch("core.config.get", side_effect=lambda k, d=None: self.prefs.get(k, d)),
            mock.patch("core.config.set", side_effect=lambda k, v: self.prefs.__setitem__(k, v)),
            mock.patch("core.config.get_last_project", side_effect=lambda: self.prefs.get("last_project")),
            mock.patch("core.config.set_last_project",
                       side_effect=lambda n: self.prefs.__setitem__("last_project", n)),
            mock.patch("core.config.get_current_user", side_effect=lambda: self.active["name"]),
            mock.patch("core.config.set_current_user",
                       side_effect=lambda n: self.active.__setitem__("name", n)),
            mock.patch("core.paths.set_config_username"),
            mock.patch("routers.settings.set_config_username"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        pr.init_project_roles("PROJ", "SUP")
        pr.init_project_roles("OTHER", "EVA")
        passwords.set_password("BOB", "abcd")
        from routers import folder_manager, project, settings
        app = FastAPI()
        app.include_router(settings.router, prefix="/settings")
        app.include_router(project.router, prefix="/project")
        app.include_router(folder_manager.router, prefix="/fm")
        self.client = TestClient(app)

    def switch(self, name: str, **body):
        return self.client.put("/settings", json={"username": name, **body})

    def journal(self, project: str = "PROJ") -> list[dict]:
        path = pr.roles_path(project).parent / sup_access.JOURNAL_NAME
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


class EntryTests(_Studio):
    def test_supervisor_enters_without_password_and_keeps_his_identity(self):
        self.assertEqual(self.switch("BOB").status_code, 200)
        self.assertEqual(self.active["name"], "BOB")
        self.assertEqual(sup_access.local_identity(), "SUP")
        self.assertEqual(sup_access.current_entry(), {"project": "PROJ", "user": "BOB", "by": "SUP"})

    def test_entry_and_leave_are_logged_without_any_password(self):
        self.switch("BOB", password="abcd")
        self.switch("SUP")
        lines = self.journal()
        self.assertNotIn("abcd", json.dumps(lines))
        self.assertEqual([(x["action"], x["by"], x["user"]) for x in lines],
                         [("enter", "SUP", "BOB"), ("leave", "SUP", "BOB")])

    def test_comes_back_without_password_and_entry_ends(self):
        passwords.set_password("SUP", "wxyz")
        self.switch("BOB")
        self.assertEqual(self.switch("SUP").status_code, 200)
        self.assertEqual(self.active["name"], "SUP")
        self.assertIsNone(sup_access.current_entry())

    def test_artist_still_needs_the_password(self):
        self.active["name"] = "EVA"
        self.prefs["last_project"] = "PROJ"
        self.assertEqual(self.switch("BOB").status_code, 403)
        self.assertEqual(self.active["name"], "EVA")
        self.assertEqual(self.journal(), [])

    def test_supervisor_of_another_project_needs_the_password_here(self):
        self.prefs["last_project"] = "OTHER"
        self.assertEqual(self.switch("BOB").status_code, 403)

    def test_demoted_supervisor_loses_it_at_once(self):
        pr.set_role("PROJ", "EVA", pr.SUPERVISOR, actor="SUP")
        pr.set_role("PROJ", "SUP", pr.ARTIST, actor="EVA")
        self.assertEqual(self.switch("BOB").status_code, 403)

    def test_password_entry_moves_the_identity(self):
        self.active["name"] = "EVA"
        self.assertEqual(self.switch("BOB", password="abcd").status_code, 200)
        self.assertEqual(sup_access.local_identity(), "BOB")
        self.assertIsNone(sup_access.current_entry())

    def test_journal_failure_falls_back_on_the_password(self):
        with mock.patch.object(sup_access, "_journal", side_effect=OSError("share down")):
            self.assertEqual(self.switch("BOB").status_code, 403)
        self.assertEqual(self.active["name"], "SUP")

    def test_profiles_tell_the_login_what_opens_freely(self):
        by_id = {p["id"]: p for p in self.client.get("/settings/users/profiles").json()["profiles"]}
        self.assertTrue(by_id["BOB"]["has_password"])
        self.assertTrue(by_id["BOB"]["free_entry"])
        self.active["name"] = "EVA"
        by_id = {p["id"]: p for p in self.client.get("/settings/users/profiles").json()["profiles"]}
        self.assertFalse(by_id["BOB"]["free_entry"])
        self.assertTrue(by_id["EVA"]["free_entry"])


class ProjectScopeTests(_Studio):
    def setUp(self):
        super().setUp()
        pr.set_role("OTHER", "BOB", pr.SUPERVISOR, actor="EVA")
        self.switch("BOB")

    def test_rights_of_the_account_apply_on_the_entry_project_only(self):
        self.assertFalse(pr.can("PROJ", "manage_roles"))    # BOB is an artist here
        self.assertFalse(pr.can("OTHER", "manage_roles"))   # BOB is supervisor there, out of the entry
        with self.assertRaises(pr.RoleError):
            pr.require("OTHER", "manage_roles")
        with self.assertRaises(pr.RoleError):
            pr.set_role("OTHER", "EVA", pr.ARTIST)

    def test_other_users_are_not_affected(self):
        self.assertTrue(pr.can("OTHER", "manage_roles", user="EVA"))

    def test_active_project_is_locked(self):
        self.assertEqual(self.client.put("/project/current", json={"project": "OTHER"}).status_code, 403)
        self.assertEqual(self.prefs["last_project"], "PROJ")

    def test_new_project_and_workspace_are_refused(self):
        self.assertEqual(self.client.post("/fm/projects", json={"name": "MINE"}).status_code, 403)
        self.assertFalse((self.root / "DOSSIER_PROJETS" / "MINE").exists())
        self.assertEqual(self.client.put("/settings", json={"workspace": str(self.root)}).status_code, 403)

    def test_everything_is_back_after_leaving(self):
        self.switch("SUP")
        self.assertEqual(self.client.put("/project/current", json={"project": "OTHER"}).status_code, 200)

    def test_settings_expose_the_entry_for_the_banner(self):
        with mock.patch("core.config.is_first_launch", return_value=False), \
                mock.patch("core.config.get_theme", return_value={}), \
                mock.patch("core.config.get_log_colors", return_value={}):
            body = self.client.get("/settings").json()
        self.assertEqual(body["sup_entry"], {"project": "PROJ", "user": "BOB", "by": "SUP"})


class RenameTests(_Studio):
    def test_identity_and_entry_follow_a_rename(self):
        self.switch("BOB")
        self.assertTrue(uu.rename_user("SUP", "SUPER")[0])
        self.assertEqual(sup_access.local_identity(), "SUPER")
        self.assertEqual(sup_access.current_entry()["by"], "SUPER")


class NoEntryTests(_Studio):
    def test_install_before_this_feature_uses_the_active_user(self):
        self.assertEqual(sup_access.local_identity(), "SUP")
        self.assertNotIn(sup_access.IDENTITY_KEY, self.prefs)

    def test_stale_entry_of_another_user_is_ignored(self):
        self.prefs[sup_access.ENTRY_KEY] = {"project": "PROJ", "user": "EVA", "by": "SUP"}
        self.assertIsNone(sup_access.current_entry())
        self.assertIsNone(sup_access.refusal("OTHER"))


if __name__ == "__main__":
    unittest.main()
