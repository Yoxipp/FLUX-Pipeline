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

    def test_split_team_cap_even(self):
        jobs = [{"jid": 2, "remaining": 50}, {"jid": 1, "remaining": 50}, {"jid": 3, "remaining": 50}]
        self.assertEqual(ft.split_team_cap(10, jobs), {1: 4, 2: 3, 3: 3})

    def test_split_team_cap_small_jobs_release_budget(self):
        jobs = [{"jid": 1, "remaining": 2}, {"jid": 2, "remaining": 100}, {"jid": 3, "remaining": 100, "cap": 3}]
        self.assertEqual(ft.split_team_cap(20, jobs), {1: 2, 2: 15, 3: 3})

    def test_split_team_cap_each_job_keeps_one(self):
        jobs = [{"jid": i, "remaining": 10} for i in range(1, 6)]
        self.assertEqual(ft.split_team_cap(2, jobs), {i: 1 for i in range(1, 6)})
        self.assertEqual(ft.split_team_cap(0, jobs), {})
        self.assertEqual(ft.split_team_cap(5, [{"jid": 1, "remaining": 0}]), {})


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

    def test_team_cap_bounds_the_job(self):
        team_settings.write_settings("P", {"team_cap": {"percent": 5}, "job_share": {"percent": 50}},
                                     path=self.render_json)
        body = self._submit().json()
        self.assertEqual(body["maxactive"], 10)  # 5 % of 200 alive, under the 100 of the job share

    def test_unknown_group_is_400(self):
        self.assertEqual(self._submit(groups=["nope"]).status_code, 400)
        self.assertEqual(self._submit(hosts=["a b"]).status_code, 400)

    def test_balancer_only_touches_team_flux_jobs(self):
        team_settings.write_settings("P", {"team_cap": {"percent": 5}, "dry_run": False}, path=self.render_json)

        def job(jid, project="P", flux="P", state="active", done=0, maxactive=0):
            return {"jid": jid, "projects": [project], "state": state, "numTasks": 40, "numDone": done,
                    "numActive": 2, "maxactive": maxactive, "metadata": {"flux_project": flux} if flux else {}}
        listing = {"jobs": [job(1), job(2, maxactive=5), job(3, flux=None), job(4, project="FIE"),
                            job(5, state="done"), job(6, state="paused")]}
        with mock.patch.object(render.tractor_bridge, "jobs", return_value=listing), \
                mock.patch.object(render.tractor_bridge, "set_maxactive") as setter:
            r = self.client.get("/render/farm", params={"project": "P"})
        self.assertEqual(r.status_code, 200, r.text)
        cap = r.json()["team_cap"]
        self.assertEqual(cap["slots"], 10)
        self.assertEqual(cap["targets"], {"1": 5, "2": 5})
        self.assertEqual(cap["used"], 6)  # jobs 1, 2 and the paused 6
        setter.assert_called_once_with(mock.ANY, "adam", 1, 5)  # job 2 already at 5

    def test_balancer_never_writes_in_simulation(self):
        team_settings.write_settings("P", {"team_cap": {"percent": 5}}, path=self.render_json)
        listing = {"jobs": [{"jid": 1, "projects": ["P"], "state": "active", "numTasks": 9, "numDone": 0,
                             "maxactive": 0, "metadata": {"flux_project": "P"}}]}
        with mock.patch.object(render.tractor_bridge, "jobs", return_value=listing), \
                mock.patch.object(render.tractor_bridge, "set_maxactive") as setter:
            r = self.client.get("/render/farm", params={"project": "P"})
        self.assertEqual(r.json()["team_cap"]["targets"], {"1": 9})
        setter.assert_not_called()


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
