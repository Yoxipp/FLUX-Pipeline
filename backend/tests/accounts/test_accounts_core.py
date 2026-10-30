# test_accounts_core.py - artist identifier, optional password, aliases, account routes.
# Runs on a temporary USER/ (core.paths.get_users_dir patched) and an in-memory prefs
# dict, so nothing touches the real workspace or config.json.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from features.accounts import aliases, identity, passwords
from utils import user_utils as uu


class _TempWorkspace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.users = self.root / "USER"
        self.users.mkdir()
        self.prefs: dict = {}
        self.active = {"name": "ALICE"}
        patches = [
            mock.patch("core.paths.get_users_dir", return_value=self.users),
            mock.patch("core.config.get", side_effect=lambda k, d=None: self.prefs.get(k, d)),
            mock.patch("core.config.set", side_effect=lambda k, v: self.prefs.__setitem__(k, v)),
            mock.patch("core.config.get_current_user", side_effect=lambda: self.active["name"]),
            mock.patch("core.config.set_current_user",
                       side_effect=lambda n: self.active.__setitem__("name", n)),
            mock.patch("core.paths.set_config_username"),
            mock.patch("routers.settings.set_config_username"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        for name in ("ALICE", "BOB"):
            (self.users / name).mkdir()


class IdentifierTests(unittest.TestCase):
    def test_ascii_upper(self):
        self.assertEqual(identity.ascii_upper("Élodie-Anne"), "ELODIEANNE")
        self.assertEqual(identity.ascii_upper("Lætitia Œuvre"), "LAETITIAOEUVRE")
        self.assertEqual(identity.ascii_upper("  "), "")

    def test_initials_of_each_last_name_word(self):
        self.assertEqual(identity.make_user_id("Adam", "Fresne-Roux", set()), "ADAM_FR")
        self.assertEqual(identity.make_user_id("Eva", "de la Tour", set()), "EVA_DLT")
        self.assertEqual(identity.make_user_id("Léa", "Le Bœuf", set()), "LEA_LB")
        # Initials taken: back to the shortest free prefix of the whole last name.
        self.assertEqual(identity.make_user_id("Adam", "Fresne-Roux", {"ADAM_FR"}), "ADAM_F")
        self.assertEqual(identity.make_user_id("Adam", "Fresne-Roux", {"ADAM_FR", "ADAM_F"}), "ADAM_FRE")

    def test_shortest_free_prefix_then_suffix(self):
        self.assertEqual(identity.make_user_id("Adam", "Colin", set()), "ADAM_C")
        taken = {"ADAM_C"}
        self.assertEqual(identity.make_user_id("Adam", "Carlier", taken), "ADAM_CA")
        taken |= {"ADAM_CA", "ADAM_CE"}
        self.assertEqual(identity.make_user_id("Adam", "Cellier", taken), "ADAM_CEL")
        full = {"BO_L", "BO_LI", "BO_LIN"}
        self.assertEqual(identity.make_user_id("Bo", "Lin", full), "BO_LIN_1")
        self.assertEqual(identity.make_user_id("Bo", "Lin", full | {"BO_LIN_1"}), "BO_LIN_2")

    def test_accents_and_validity(self):
        user_id = identity.make_user_id("Hélène", "Éluard", {"helene_e"})
        self.assertEqual(user_id, "HELENE_EL")
        self.assertTrue(uu.is_valid_user_name(user_id))

    def test_empty_parts_refused(self):
        with self.assertRaises(ValueError):
            identity.make_user_id("", "Colin", set())
        with self.assertRaises(ValueError):
            identity.make_user_id("Adam", "---", set())


class PasswordTests(_TempWorkspace):
    def test_hash_never_plain_and_verifies(self):
        record = passwords.hash_password("secret1")
        self.assertNotIn("secret1", str(record))
        self.assertTrue(passwords.verify_password("secret1", record))
        self.assertFalse(passwords.verify_password("secret2", record))
        self.assertNotEqual(record["salt"], passwords.hash_password("secret1")["salt"])

    def test_malformed_records_refused(self):
        for bad in (None, {}, {"algo": "md5"}, {"algo": "scrypt", "salt": "zz", "hash": "00",
                                               "n": 16384, "r": 8, "p": 1},
                    {"algo": "scrypt", "salt": "00", "hash": "00", "n": 2 ** 30, "r": 8, "p": 1}):
            self.assertFalse(passwords.verify_password("x", bad))

    def test_no_password_is_current_behaviour(self):
        self.assertFalse(passwords.has_password("ALICE"))
        self.assertTrue(passwords.check_password("ALICE", None))
        self.assertTrue(passwords.can_enter("ALICE", None))

    def test_set_change_remove(self):
        passwords.set_password("ALICE", "abcd")
        self.assertTrue(passwords.has_password("ALICE"))
        self.assertFalse(passwords.can_enter("ALICE", "nope"))
        self.assertTrue(passwords.can_enter("ALICE", "abcd"))
        self.assertNotIn("abcd", (self.users / "ALICE" / "UserSettings" / "User.json").read_text("utf-8"))
        passwords.set_password("ALICE", None)
        self.assertTrue(passwords.can_enter("ALICE", None))
        with self.assertRaises(ValueError):
            passwords.set_password("ALICE", "ab")

    def test_remember_revoked_by_new_password(self):
        passwords.set_password("BOB", "first")
        passwords.remember_on_this_pc("BOB")
        self.assertTrue(passwords.can_enter("BOB", None))
        passwords.set_password("BOB", "second")       # reset / change -> new salt
        self.assertFalse(passwords.can_enter("BOB", None))


class AliasTests(_TempWorkspace):
    def test_chain_is_flattened_and_rename_back(self):
        aliases.record_rename("A", "B")
        aliases.record_rename("B", "C")
        self.assertEqual(aliases.load_aliases(), {"A": "C", "B": "C"})
        self.assertTrue(aliases.same_user("a", "C"))
        aliases.record_rename("C", "A")
        self.assertEqual(aliases.load_aliases(), {"B": "A", "C": "A"})
        self.assertEqual(aliases.resolve_user("A"), "A")

    def test_retired_name_not_reusable(self):
        ok, _ = uu.rename_user("BOB", "ROBERT")
        self.assertTrue(ok)
        self.assertEqual(aliases.resolve_user("BOB"), "ROBERT")
        ok, msg = uu.rename_user("ALICE", "BOB")
        self.assertFalse(ok, msg)
        ok, _ = uu.rename_user("ROBERT", "BOB")       # his own old name: allowed
        self.assertTrue(ok)
        self.assertEqual(aliases.load_aliases(), {"ROBERT": "BOB"})

    def test_other_machine_follows_rename(self):
        # Another machine still has the old name saved: it follows the alias.
        ok, _ = uu.rename_user("BOB", "ROBERT")
        self.assertTrue(ok)
        self.assertEqual(uu.follow_rename("BOB"), "ROBERT")
        self.assertEqual(uu.follow_rename("bob"), "ROBERT")
        self.assertEqual(uu.follow_rename("ALICE"), "ALICE")
        self.assertIsNone(uu.follow_rename(None))
        (self.users / "BOB").mkdir()                   # a live BOB folder again: keep it
        self.assertEqual(uu.follow_rename("BOB"), "BOB")


class AccountRouteTests(_TempWorkspace):
    def setUp(self):
        super().setUp()
        from routers import settings as settings_router
        app = FastAPI()
        app.include_router(settings_router.router, prefix="/settings")
        self.client = TestClient(app)

    def test_create_artist_with_profile_and_password(self):
        res = self.client.post("/settings/users", json={
            "first_name": "Adam", "last_name": "Colin", "password": "abcd", "switch": False})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["id"], "ADAM_C")
        profile = identity.read_profile("ADAM_C")
        self.assertEqual((profile["first_name"], profile["last_name"]), ("Adam", "Colin"))
        self.assertTrue(profile["has_password"])
        preview = self.client.post("/settings/users/id-preview",
                                   json={"first_name": "Adam", "last_name": "Carlier"})
        self.assertEqual(preview.json()["id"], "ADAM_CA")

    def test_switch_needs_password(self):
        passwords.set_password("BOB", "abcd")
        res = self.client.put("/settings", json={"username": "BOB"})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.active["name"], "ALICE")
        res = self.client.put("/settings", json={"username": "BOB", "password": "abcd", "remember": True})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.active["name"], "BOB")
        self.active["name"] = "ALICE"
        self.assertEqual(self.client.put("/settings", json={"username": "BOB"}).status_code, 200)

    def test_user_data_never_exposes_or_takes_the_hash(self):
        passwords.set_password("ALICE", "abcd")
        self.client.put("/settings/user-data", json={"password": {"hash": "00"}, "x": 1})
        data = self.client.get("/settings/user-data").json()
        self.assertNotIn("password", data)
        self.assertEqual(data["x"], 1)
        self.assertTrue(passwords.check_password("ALICE", "abcd"))

    def test_own_password_change_needs_current(self):
        passwords.set_password("ALICE", "abcd")
        res = self.client.put("/settings/user/password", json={"current": "bad", "new": "efgh"})
        self.assertEqual(res.status_code, 403)
        res = self.client.put("/settings/user/password", json={"current": "abcd", "new": ""})
        self.assertEqual(res.json(), {"has_password": False})

    def test_reset_and_manage_need_a_role(self):
        passwords.set_password("BOB", "abcd")
        refuse = mock.patch("features.roles.project_roles.require",
                            side_effect=PermissionError("Réservé aux leads et superviseurs."))
        with refuse:
            res = self.client.post("/settings/users/BOB/reset-password", json={"project": "P"})
            self.assertEqual(res.status_code, 403)
            self.assertIn("superviseurs", res.json()["detail"])
            self.assertEqual(self.client.put("/settings/users/rename",
                                             json={"old": "BOB", "new": "X", "project": "P"}).status_code, 403)
            self.assertEqual(self.client.delete("/settings/users/BOB?project=P").status_code, 403)
            # Own account stays yours.
            self.assertEqual(self.client.put("/settings/users/rename",
                                             json={"old": "ALICE", "new": "ALICIA"}).status_code, 200)
        self.assertTrue(passwords.has_password("BOB"))
        self.assertEqual(self.client.post("/settings/users/BOB/reset-password", json={}).status_code, 403)
        with mock.patch("features.roles.project_roles.require", return_value=None):
            res = self.client.post("/settings/users/BOB/reset-password", json={"project": "P"})
            self.assertEqual(res.status_code, 200, res.text)
        self.assertFalse(passwords.has_password("BOB"))

    def test_rename_by_first_and_last_name(self):
        # ADR 0079: a lead renames from first / last name, the id comes from the initials.
        allow = mock.patch("features.roles.project_roles.require", return_value=None)
        with allow:
            res = self.client.post("/settings/users/rename-preview",
                                   json={"old": "BOB", "first_name": "Bob", "last_name": "Le Gall"})
            self.assertEqual(res.json()["id"], "BOB_LG")
            res = self.client.put("/settings/users/rename-by-name",
                                  json={"old": "BOB", "first_name": "Bob", "last_name": "Le Gall", "project": "P"})
            self.assertEqual(res.status_code, 200, res.text)
            self.assertEqual(res.json()["id"], "BOB_LG")
            self.assertTrue(uu.user_exists("BOB_LG"))
            self.assertFalse(uu.user_exists("BOB"))
            self.assertEqual(aliases.resolve_user("BOB"), "BOB_LG")
            profile = identity.read_profile("BOB_LG")
            self.assertEqual((profile["first_name"], profile["last_name"]), ("Bob", "Le Gall"))
            # Same person, same name: keeps the id (not BOB_L because BOB_LG is "taken").
            res = self.client.put("/settings/users/rename-by-name",
                                  json={"old": "BOB_LG", "first_name": "Bob", "last_name": "le gall", "project": "P"})
            self.assertEqual(res.json()["id"], "BOB_LG")
            self.assertEqual(identity.read_profile("BOB_LG")["last_name"], "le gall")
            # No last name = the first name alone (his own old name BOB is his to take back).
            res = self.client.put("/settings/users/rename-by-name",
                                  json={"old": "BOB_LG", "first_name": "Bob", "last_name": "", "project": "P"})
            self.assertEqual(res.json()["id"], "BOB")
            # Someone else's name is never reused.
            res = self.client.post("/settings/users/rename-preview",
                                   json={"old": "BOB", "first_name": "Alice", "last_name": ""})
            self.assertEqual(res.json()["id"], "ALICE_1")
        refuse = mock.patch("features.roles.project_roles.require", side_effect=PermissionError("Réservé aux leads."))
        with refuse:
            res = self.client.put("/settings/users/rename-by-name",
                                  json={"old": "BOB", "first_name": "Robert", "last_name": "X", "project": "P"})
            self.assertEqual(res.status_code, 403)


if __name__ == "__main__":
    unittest.main()
