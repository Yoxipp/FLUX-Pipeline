# Studio environment file (ADR 0063): neutral defaults, link handling, validation, precedence over render.json.
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import studio_config
from features.render import farm_limits, farm_targets, studio_env
from features.render import team_settings as ts
from features.roles import project_roles
from routers import render
from tests.render.studio_fixture import SAMPLE_FARM, write_env


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.render_json = self.tmp / "render.json"
        self.env_file = None  # None = the studio has no link
        for p in (mock.patch("core.paths.get_project_render_path", return_value=self.render_json),
                  mock.patch.object(studio_env, "environment_file", side_effect=self._env),
                  mock.patch.dict("os.environ", {"TRACTOR_ENGINE": ""})):
            p.start()
            self.addCleanup(p.stop)

    def _env(self):
        return self.env_file


class Defaults(Base):
    def test_no_link_is_all_neutral(self):
        env = studio_env.read_environment()
        self.assertEqual(env["schema_version"], 1)
        self.assertEqual(env["farm"], studio_env.FARM_DEFAULTS)
        for key in ("engine", "engine_user", "engine_config_dir", "bridge_python", "blade_tractor_python",
                    "houdini_path", "denoise_path", "renderer", "denoise_tag", "room_pattern"):
            self.assertEqual(env["farm"][key], "", key)
        self.assertFalse(env["farm"]["forbid_drive_letters"])
        self.assertEqual((env["farm"]["render_tag"], env["farm"]["default_share"]), ("husk", "default"))

    def test_missing_or_broken_file_never_raises(self):
        self.env_file = self.tmp / "nope.json"
        self.assertEqual(studio_env.read_environment()["farm"], studio_env.FARM_DEFAULTS)
        self.env_file.write_text("{not json", encoding="utf-8")
        self.assertEqual(studio_env.read_environment()["farm"], studio_env.FARM_DEFAULTS)
        self.env_file.write_text(json.dumps({"farm": {"engine": "bad host!", "houdini_path": "D:\\H21\\", "x": 1}}),
                                 encoding="utf-8")
        farm = studio_env.read_environment()["farm"]
        self.assertEqual((farm["engine"], farm["houdini_path"]), ("", "D:/H21"))  # bad value = neutral, good one kept

    def test_write_needs_a_link(self):
        with self.assertRaises(studio_env.StudioEnvError) as cm:
            studio_env.write_environment({"farm": {"engine": "eng:1"}})
        self.assertIn("lie", str(cm.exception))

    def test_write_roundtrip_merges(self):
        self.env_file = self.tmp / "env.json"
        studio_env.write_environment({"name": "Studio A", "farm": {"engine": "eng:5600", "houdini_path": "D:\\H\\"}})
        out = studio_env.write_environment({"farm": {"denoise_tag": "Denoise"}})
        self.assertEqual((out["name"], out["farm"]["engine"], out["farm"]["houdini_path"], out["farm"]["denoise_tag"]),
                         ("Studio A", "eng:5600", "D:/H", "Denoise"))
        self.assertEqual(json.loads(self.env_file.read_text("utf-8"))["schema_version"], 1)

    def test_validation_messages_are_french_and_nothing_is_written(self):
        self.env_file = self.tmp / "env.json"
        bad = ({"engine": "a b"}, {"engine_user": "x" * 65}, {"renderer": "arnold"}, {"priority": 0},
               {"priority": True}, {"forbid_drive_letters": "oui"}, {"envkeys": "x"}, {"render_tag": "a b"},
               {"denoise_tag": "{x}"}, {"room_pattern": "("}, {"room_pattern": "^abc$"}, {"bogus": 1},
               {"houdini_path": 3})
        for farm in bad:
            with self.assertRaises(studio_env.StudioEnvError, msg=str(farm)):
                studio_env.write_environment({"farm": farm})
        self.assertFalse(self.env_file.exists())
        with self.assertRaises(studio_env.StudioEnvError) as cm:
            studio_env.write_environment({"farm": {"renderer": "arnold"}})
        self.assertIn("Moteur de rendu", str(cm.exception))

    def test_room_pattern(self):
        pattern = SAMPLE_FARM["room_pattern"]
        self.assertEqual(studio_env.room_of("ROOM1701", pattern), "ROOM17")
        self.assertEqual(studio_env.room_of("room17PROF", pattern), "ROOM17")
        self.assertIsNone(studio_env.room_of("WIN-ABC", pattern))
        self.assertIsNone(studio_env.room_of("ROOM1701", ""))  # no pattern, no room
        self.assertEqual(farm_targets.room_of("ROOM1701", ""), "")
        self.assertEqual(farm_targets.room_of("WIN-ABC", pattern), farm_targets.OTHER_GROUP)


class Precedence(Base):
    def test_nothing_stored_nothing_linked_is_empty(self):
        s = ts.effective_settings("proj")
        for key in ("houdini_path", "denoise_path", "renderer", "bridge_python", "engine", "engine_user",
                    "blade_tractor_python", "denoise_tag", "room_pattern"):
            self.assertEqual(s[key], "", key)
        self.assertEqual((s["husk_path"], s["priority"], s["forbid_drive_letters"]), ("husk", 1, False))
        self.assertEqual(set(s["value_sources"].values()), {""})

    def test_render_json_over_environment_over_empty(self):
        self.env_file = write_env(self.tmp, houdini_path="D:/EnvH", renderer="karma", engine="env:1")
        s = ts.effective_settings("proj")
        self.assertEqual((s["houdini_path"], s["renderer"], s["engine"]), ("D:/EnvH", "karma", "env:1"))
        self.assertEqual(s["value_sources"]["houdini_path"], "studio")
        self.render_json.write_text(json.dumps({"houdini_path": "D:/OwnH"}), encoding="utf-8")
        s = ts.effective_settings("proj")
        self.assertEqual((s["houdini_path"], s["value_sources"]["houdini_path"]), ("D:/OwnH", "project"))
        self.assertEqual(s["renderer"], "karma")  # not stored: still the environment's

    def test_empty_stored_value_follows_the_environment(self):
        self.env_file = write_env(self.tmp, denoise_path="D:/dn.exe")
        self.render_json.write_text(json.dumps({"denoise_path": ""}), encoding="utf-8")
        self.assertEqual(ts.effective_settings("proj")["denoise_path"], "D:/dn.exe")

    def test_old_render_json_keeps_its_values(self):
        # a project that stored the former hardcoded defaults keeps them whatever the environment says
        self.env_file = write_env(self.tmp, houdini_path="D:/EnvH")
        self.render_json.write_text(json.dumps({"schema_version": 2, "renderer": "renderman",
                                                "houdini_path": "C:/Houdini 20.5.445"}), encoding="utf-8")
        s = ts.effective_settings("proj")
        self.assertEqual((s["renderer"], s["houdini_path"]), ("renderman", "C:/Houdini 20.5.445"))

    def test_saving_other_settings_does_not_pin_environment_values(self):
        self.env_file = write_env(self.tmp, houdini_path="D:/EnvH")
        ts.write_settings("proj", {"chunk_size": 9, "houdini_path": "D:/EnvH", "priority": 1})
        stored = json.loads(self.render_json.read_text("utf-8"))
        self.assertNotIn("houdini_path", stored)
        self.assertNotIn("priority", stored)
        self.assertEqual(stored["chunk_size"], 9)
        self.env_file = write_env(self.tmp, houdini_path="D:/Other")
        self.assertEqual(ts.effective_settings("proj")["houdini_path"], "D:/Other")  # still follows
        ts.write_settings("proj", {"houdini_path": "D:/Mine"})
        self.assertEqual(ts.effective_settings("proj")["houdini_path"], "D:/Mine")

    def test_requirements_name_the_setting(self):
        s = ts.effective_settings("proj")
        with self.assertRaises(ValueError) as cm:
            ts.require_houdini(s)
        self.assertIn("houdini_path", str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            ts.require_denoise(s)
        self.assertIn("denoise_path", str(cm.exception))
        self.env_file = write_env(self.tmp)
        s = ts.effective_settings("proj")
        self.assertTrue(ts.require_houdini(s))
        self.assertTrue(ts.require_denoise(s))

    def test_priority_warning_is_neutral(self):
        text = ts.priority_warning({"priority": 5})
        self.assertNotIn("ecole", text.lower())
        self.assertIsNone(ts.priority_warning({"priority": 1}))


class SharesUseTheEnvironmentNames(unittest.TestCase):
    SHARES = {"render": {"A": {"nominal": 0.2, "cap": 0.9}, "other": {"nominal": 0.1, "cap": 0.1}}}

    def test_tag_and_default_share_are_parameters(self):
        self.assertEqual(farm_limits.teams(self.SHARES, "render", "other"), ["A"])
        self.assertIsNone(farm_limits.team_warning("A", self.SHARES, "render", "other"))
        warning = farm_limits.team_warning("Z", self.SHARES, "render", "other")
        self.assertIn("'other'", warning)
        with self.assertRaises(farm_limits.LimitsError):
            farm_limits.check_teams({"A": {"nominal": 0.2, "cap": 0.5}}, "other")


class Routes(Base):
    """Real studio.json in a temp folder: link -> environment file, with project roles mocked."""

    def _env(self):
        return studio_config.environment_path()

    def setUp(self):
        super().setUp()
        self.render_json.write_text('{"dry_run": true}', encoding="utf-8")
        (self.tmp / "CONFIG").mkdir()
        self.denied = False

        def require(project, action, user=None):
            if self.denied:
                raise project_roles.RoleError(f"Role Lead requis sur {project}")

        app = FastAPI()
        app.include_router(render.router, prefix="/render")
        self.client = TestClient(app)
        for p in (mock.patch.object(render.project_utils, "project_exists", return_value=True),
                  mock.patch.object(render.project_utils, "get_project_path", return_value=str(self.tmp)),
                  mock.patch.object(render.config, "get_current_user", return_value="adam"),
                  mock.patch.object(render.project_roles, "require", side_effect=require),
                  mock.patch.object(studio_config, "studio_path", return_value=self.tmp / "CONFIG" / "studio.json"),
                  mock.patch.object(studio_config.paths, "get_flux_root", return_value=str(self.tmp))):
            p.start()
            self.addCleanup(p.stop)

    def test_state_without_link(self):
        body = self.client.get("/render/studio-env", params={"project": "P"}).json()
        self.assertEqual((body["link"], body["path"], body["exists"]), ("", "", False))
        self.assertEqual(body["values"], studio_env.FARM_DEFAULTS)

    def test_link_create_edit_and_roles(self):
        r = self.client.put("/render/studio-env", params={"project": "P"}, json={"farm": {"engine": "e:1"}})
        self.assertEqual(r.status_code, 400)  # no link yet
        link = "CONFIG/env.json"
        r = self.client.put("/render/studio-env/link", params={"project": "P"}, json={"link": link})
        self.assertEqual(r.status_code, 400)  # file missing, create not asked
        r = self.client.put("/render/studio-env/link", params={"project": "P"}, json={"link": link, "create": True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["exists"])
        r = self.client.put("/render/studio-env", params={"project": "P"},
                            json={"farm": {"engine": "e:1", "room_pattern": "^([A-Z]+)(\\d{2})"}})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["values"]["engine"], "e:1")
        r = self.client.put("/render/studio-env", params={"project": "P"}, json={"farm": {"priority": 0}})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Priorite", r.json()["detail"])
        self.denied = True
        for call in (lambda: self.client.put("/render/studio-env", params={"project": "P"}, json={"farm": {}}),
                     lambda: self.client.put("/render/studio-env/link", params={"project": "P"}, json={"link": ""}),
                     lambda: self.client.put("/render/settings", params={"project": "P"}, json={"chunk_size": 3}),
                     lambda: self.client.post("/render/env/state", params={"project": "P"}, json={"phrase": "Understand"}),
                     lambda: self.client.post("/render/env/reload", params={"project": "P"}, json={"phrase": "Understand"}),
                     lambda: self.client.put("/render/env/shares", params={"project": "P"},
                                             json={"phrase": "Understand", "teams": {}})):
            r = call()
            self.assertEqual(r.status_code, 403)
            self.assertIn("Role Lead requis", r.json()["detail"])
        self.assertEqual(self.client.get("/render/studio-env", params={"project": "P"}).status_code, 200)  # reading is open

    def test_missing_denoise_path_is_a_clear_400(self):
        r = self.client.post("/render/denoise", json={"project": "P", "path": str(self.tmp)})
        self.assertEqual(r.status_code, 400)
        self.assertIn("denoise_path", r.json()["detail"])


if __name__ == "__main__":
    unittest.main()
