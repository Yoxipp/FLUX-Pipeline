"""Farm targeting (machines, rooms, groups) and throttling (% of the farm, team cap)."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from features.render import farm_targets as ft
from features.render import team_settings
from routers import render

NOW = datetime(2026, 10, 23, 11, 0, 0)
FRESH = "2026-10-23 10:58:00.1+02"
OLD = "2026-09-14 08:39:01.5+02"


def blade(name, beat=FRESH, nimby="", busy=None):
    return {"name": name, "heartbeattime": beat, "nimby": nimby, "numslots": 1, "busy": busy}


class BladeStates(unittest.TestCase):
    def test_states(self):
        self.assertEqual(ft.blade_state(blade("A"), NOW), "free")
        self.assertEqual(ft.blade_state(blade("A", beat=OLD), NOW), "offline")
        self.assertEqual(ft.blade_state(blade("A", nimby="/local/A"), NOW), "nimby")
        self.assertEqual(ft.blade_state(blade("A", busy={"jid": 3, "project": "FIE"}), NOW), "busy")
        self.assertEqual(ft.blade_state(blade("A", beat=""), NOW), "offline")

    def test_counts_and_rooms(self):
        rows = ft.classify([blade("ROOM1701"), blade("ROOM1702", nimby="x"), blade("ROOM2601", beat=OLD),
                            blade("ROOM17PROF", busy={"jid": 1, "project": "CEB"}), blade("WIN-ABC")], NOW)
        c = ft.counts(rows)
        self.assertEqual((c["free"], c["nimby"], c["busy"], c["offline"], c["alive"]), (2, 1, 1, 1, 4))
        rooms = ft.rooms(rows)
        self.assertEqual(rooms["ROOM17"], ["ROOM1701", "ROOM1702", "ROOM17PROF"])
        self.assertNotIn("ROOM26", rooms)  # offline only
        self.assertEqual(rooms[ft.OTHER_GROUP], ["WIN-ABC"])


class ServiceExpression(unittest.TestCase):
    def test_any_blade(self):
        self.assertEqual(ft.service_expression("", [], []), "")
        self.assertEqual(ft.service_expression("PixarRender", [], []), "PixarRender")

    def test_include_and_exclude(self):
        self.assertEqual(ft.service_expression("", ["B", "A"], []), "(A || B)")
        self.assertEqual(ft.service_expression("", ["A"], ["C"]), "A && !C")
        self.assertEqual(ft.service_expression("PixarRender", ["A", "B"], ["B", "C"]),
                         "(PixarRender) && (A || B) && !C")  # a picked PC wins over the exclusion

    def test_bad_host_refused(self):
        for bad in ("A B", "A;B", "{A}", "", "A||B"):
            with self.assertRaises(ValueError):
                ft.service_expression("", [bad], [])

    def test_resolve_hosts(self):
        out = ft.resolve_hosts(["X1"], ["nous", "ROOM17"], {"nous": ["N1", "X1"]}, {"ROOM17": ["R1"]})
        self.assertEqual(out, ["N1", "R1", "X1"])
        with self.assertRaises(ValueError):
            ft.resolve_hosts([], ["nope"], {}, {})


class Shares(unittest.TestCase):
    def test_cap_from_percent(self):
        counts = {"alive": 216, "free": 146}
        self.assertEqual(ft.cap_from_percent(0, "alive", counts), 0)
        self.assertEqual(ft.cap_from_percent(20, "alive", counts), 43)
        self.assertEqual(ft.cap_from_percent(10, "free", counts), 14)
        self.assertEqual(ft.cap_from_percent(1, "free", {"free": 0}), 1)  # never 0 = never "no cap"
        with self.assertRaises(ValueError):
            ft.cap_from_percent(10, "nope", counts)


class Settings(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = self.tmp / "render.json"

    def test_new_keys_validated(self):
        s = team_settings.write_settings("P", {"team_cap": {"percent": 30}, "host_groups": {"nous": ["B", "A", "A"]},
                                               "exclude_hosts": ["ROOM0321"]}, path=self.path)
        self.assertEqual(s["team_cap"], {"percent": 30, "of": "alive"})
        self.assertEqual(s["host_groups"], {"nous": ["A", "B"]})
        for bad in ({"team_cap": {"percent": 120}}, {"job_share": {"of": "x"}}, {"exclude_hosts": ["a b"]},
                    {"host_groups": {"g": "A"}}, {"team_cap": {"nope": 1}}):
            with self.assertRaises(ValueError):
                team_settings.write_settings("P", bad, path=self.path)

    def test_bad_stored_subkey_keeps_the_others(self):
        self.path.write_text('{"job_share": {"percent": 999, "of": "free"}}', encoding="utf-8")
        self.assertEqual(team_settings.read_settings("P", path=self.path)["job_share"], {"percent": 0, "of": "free"})


SNAP = {"blades": [], "counts": {"free": 100, "busy": 50, "nimby": 50, "offline": 10, "alive": 200},
        "rooms": {"ROOM17": ["ROOM1701", "ROOM1702"]}, "active_by_project": {}, "dry_run": False}


class RouterTargeting(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.project_dir = self.tmp / "proj"
        self.project_dir.mkdir()
        self.render_json = self.tmp / "render.json"
        self.render_json.write_text('{"dry_run": true}', encoding="utf-8")  # simulation unless a test says otherwise
        render._submits.clear()
        self.addCleanup(render._submits.clear)
        app = FastAPI()
        app.include_router(render.router, prefix="/render")
        self.client = TestClient(app)
        render._snapshot.clear()
        self.addCleanup(render._snapshot.clear)
        patches = [
            mock.patch.object(render.project_utils, "project_exists", return_value=True),
            mock.patch.object(render.project_utils, "get_project_path", return_value=str(self.project_dir)),
            mock.patch("core.paths.get_project_render_path", return_value=self.render_json),
            mock.patch.object(render.config, "get_current_user", return_value="adam"),
            mock.patch.object(render.farm_paths, "_unc_of_drive", return_value=None),
            mock.patch.object(render.team_settings, "TRACTOR_PYTHON_CANDIDATES", ()),
            mock.patch.dict("os.environ", {"TRACTOR_ENGINE": ""}),
            mock.patch.object(render, "_farm_snapshot", return_value=SNAP),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        d = self.tmp / "asset"
        d.mkdir()
        self.usd = d / "thing.usda"
        self.usd.write_text('#usda 1.0\n\ndef Xform "Root"\n{\n}\n', encoding="utf-8")

    def _submit(self, **extra):
        return self.client.post("/render/submit", json={
            "project": "P", "usd_path": str(self.usd), "frame_start": 1, "frame_end": 20, **extra})

    def test_hosts_groups_and_share(self):
        team_settings.write_settings("P", {"exclude_hosts": ["ROOM1702"], "host_groups": {"nous": ["N1"]}},
                                     path=self.render_json)
        r = self._submit(hosts=["H1"], groups=["ROOM17", "nous"], share_percent=10, share_of="free")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        # ROOM1702 is both in the picked room and excluded: picked wins (explicit choice).
        self.assertEqual(body["service"], "(H1 || N1 || ROOM1701 || ROOM1702)")
        self.assertEqual(body["maxactive"], 10)
        self.assertFalse(any("pas encore valide" in w for w in body["warnings"]))  # validated 2026-10-23
        alf = next((self.usd.parent / "render" / "v001" / "_job").glob("*.alf")).read_text(encoding="utf-8")
        self.assertIn("-maxactive 10", alf)
        self.assertIn('"cap": "10"', alf)

    def test_team_cap_never_applied(self):
        # The school's Shares decide (2026-10-23): an old render.json team_cap is read, never applied.
        team_settings.write_settings("P", {"team_cap": {"percent": 5}}, path=self.render_json)
        self.assertEqual(self._submit(share_percent=0).json()["maxactive"], 0)  # was 5 % of 200 = 10
        team_settings.write_settings("P", {"dry_run": False}, path=self.render_json)
        with mock.patch.object(render.tractor_bridge, "jobs") as lister, \
                mock.patch.object(render.tractor_bridge, "set_maxactive") as setter:
            r = self.client.get("/render/farm", params={"project": "P"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn("team_cap", r.json())
        lister.assert_not_called()
        setter.assert_not_called()

    def test_unknown_group_is_400(self):
        self.assertEqual(self._submit(groups=["nope"]).status_code, 400)
        self.assertEqual(self._submit(hosts=["a b"]).status_code, 400)


class TractorProjects(RouterTargeting):
    def test_known_projects_most_used_first(self):
        listing = {"jobs": [{"projects": ["FIE"]}, {"projects": ["CEB"]}, {"projects": ["FIE"]}, {"projects": []}]}
        with mock.patch.object(render.tractor_bridge, "jobs", return_value=listing):
            r = self.client.get("/render/tractor_projects", params={"project": "P"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"projects": [{"name": "FIE", "jobs": 2}, {"name": "CEB", "jobs": 1}], "current": "P"})


class FarmTeams(RouterTargeting):
    """Teams of the farm from the engine limits.config (read only): FLUX warns, Tractor balances."""

    def test_settings_and_submit_warn_outside_the_shares(self):
        from features.render import farm_limits
        from tests.render.test_farm_limits import SAMPLE

        with mock.patch.object(farm_limits, "fetch_shares", return_value=farm_limits.parse_shares(SAMPLE)):
            body = self.client.get("/render/settings", params={"project": "P"}).json()
            self.assertEqual(body["farm_teams"], ["Andhakara", "Hold", "Lum", "MortalKoil"])
            self.assertEqual(body["farm_shares"]["default"], {"nominal": 0.25, "cap": 0.1})  # Farm tab summary
            self.assertIn("'default'", body["team_warning"])  # tractor_project defaults to the FLUX name "P"
            self.assertTrue(any("'default'" in w for w in self._submit().json()["warnings"]))
            self.client.put("/render/settings", params={"project": "P"}, json={"tractor_project": "Lum"})
            self.assertIsNone(self.client.get("/render/settings", params={"project": "P"}).json()["team_warning"])

    def test_priority_per_job(self):
        body = self._submit(priority=7).json()
        self.assertEqual(body["priority"], 7)
        self.assertIn("Priorite 7", body["priority_warning"])
        alf = next((self.usd.parent / "render" / "v001" / "_job").glob("*.alf")).read_text(encoding="utf-8")
        self.assertIn("-priority 7", alf)
        self.assertEqual(self._submit(priority=0).status_code, 400)
        with mock.patch.object(render.tractor_bridge, "set_priority", return_value={"jid": 5, "priority": 3}) as setter:
            r = self.client.post("/render/jobs/5/priority", params={"project": "P"}, json={"priority": 3})
        self.assertEqual(r.status_code, 200, r.text)  # not swallowed by /jobs/{jid}/{action}
        setter.assert_called_once_with(mock.ANY, "adam", 5, 3)

    def test_denoise_after_render(self):
        self.assertEqual(self._submit(renderer="karma", denoise=True).status_code, 400)
        body = self._submit(renderer="renderman", denoise=True).json()
        self.assertTrue(body["denoise"].endswith("denoised"))
        alf = next((self.usd.parent / "render" / "v001" / "_job").glob("*.alf")).read_text(encoding="utf-8")
        self.assertIn("Task -title {denoise} -subtasks {", alf)
        self.assertIn("-cf --frame-include", alf)  # crossframe by default

    def test_denoise_rendered_sequence(self):
        frames = self.tmp / "v003"
        frames.mkdir()
        for f in (1, 2, 3, 5):
            (frames / f"SH010.{f:04d}.exr").write_bytes(b"")
        r = self.client.post("/render/denoise", json={"project": "P", "path": str(frames / "SH010.0002.exr"), "frame_end": 3})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual((body["frames"], body["count"], body["pattern"]), ([1, 3], 3, "SH010.$F4.exr"))
        alf = next((frames / "denoised" / "_job").glob("*.alf")).read_text(encoding="utf-8")
        self.assertIn("SH010.####.exr 1-3", alf)
        self.assertNotIn("husk", alf)
        r = self.client.post("/render/denoise", json={"project": "P", "path": str(frames)})
        self.assertEqual(r.status_code, 400)  # frame 4 missing
        self.assertIn("4", r.json()["detail"])

    def test_env_locked_and_never_in_simulation(self):
        for path in ("/render/env/state", "/render/env/reload"):
            self.assertEqual(self.client.post(path, params={"project": "P"}, json={"phrase": "Understand", "password": "x"}).status_code, 403)
        teams = {"default": {"nominal": 0.1, "cap": 0.1}}
        with mock.patch.object(render.farm_limits, "write_shares") as writer:
            r = self.client.put("/render/env/shares", params={"project": "P"},
                                json={"phrase": "Understand", "password": "root", "teams": teams})
        self.assertEqual(r.status_code, 400)  # setUp: simulation
        writer.assert_not_called()
        with mock.patch.object(render.farm_limits, "engine_text", return_value=None):
            r = self.client.post("/render/env/state", params={"project": "P"}, json={"phrase": "Understand", "password": "root"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["folder_ok"])

    def test_no_engine_no_warning(self):
        body = self.client.get("/render/settings", params={"project": "P"}).json()
        self.assertEqual((body["farm_teams"], body["team_warning"]), ([], None))


class LastForm(RouterTargeting):
    def test_last_form_per_artist(self):
        self.assertEqual(self.client.get("/render/last", params={"project": "P"}).json(), {"last": {}})
        r = self.client.put("/render/last", params={"project": "P"}, json={"seq": "SQ01", "shot": "SH010"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue((self.tmp / "render_last" / "adam.json").is_file())
        self.assertEqual(self.client.get("/render/last", params={"project": "P"}).json()["last"]["shot"], "SH010")
        with mock.patch.object(render.config, "get_current_user", return_value="bob"):
            self.assertEqual(self.client.get("/render/last", params={"project": "P"}).json(), {"last": {}})
        self.assertEqual(self.client.put("/render/last", params={"project": "P"}, json={"x": "a" * 30000}).status_code, 400)


class SafetyGuards(RouterTargeting):
    """Real farm by default (2026-10-23): what keeps FLUX from touching what is not ours."""

    def test_two_submits_never_share_a_render_version(self):
        from features.render import freeze
        a = freeze.reserve_render_dir(self.tmp / "shot")
        b = freeze.reserve_render_dir(self.tmp / "shot")
        self.assertEqual((a.name, b.name), ("v001", "v002"))

    def test_real_submit_needs_a_flux_user(self):
        team_settings.write_settings("P", {"dry_run": False}, path=self.render_json)
        with mock.patch.object(render.config, "get_current_user", return_value=None):
            r = self._submit()
        self.assertEqual(r.status_code, 400)
        self.assertIn("Connecte-toi", r.text)

    def test_actions_refused_without_flux_user(self):
        from features.render import tractor_bridge
        with mock.patch.object(tractor_bridge, "call") as call:
            with self.assertRaises(tractor_bridge.BridgeError):
                tractor_bridge.kill({"dry_run": False}, "unknown", 12)
        call.assert_not_called()

    def test_submit_rate_cap(self):
        team_settings.write_settings("P", {"dry_run": False}, path=self.render_json)
        fake = {"dry_run": False, "jid": 1, "files": {"alf": "x", "json": "y"}}
        with mock.patch.object(render, "_submit", return_value=fake):
            codes = [self._submit().status_code for _ in range(render._SUBMIT_MAX + 1)]
        self.assertEqual(codes[:-1], [200] * render._SUBMIT_MAX)
        self.assertEqual(codes[-1], 429)


if __name__ == "__main__":
    unittest.main()
