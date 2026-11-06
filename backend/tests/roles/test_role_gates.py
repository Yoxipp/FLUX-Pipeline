# test_role_gates.py - routes guarded by the project role (ADR 0064), on a temporary FLUX_ROOT.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

import main
from features.production import lock
from features.roles import project_roles as pr


class _Gates(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "DOSSIER_PROJETS" / "PROJ" / "_flux_setup").mkdir(parents=True)
        (self.root / "CONFIG").mkdir()
        (self.root / "USER" / "ADAM").mkdir(parents=True)
        (self.root / "USER" / "EVA").mkdir()
        self.user = "ADAM"
        for p in (mock.patch("core.paths.get_flux_root", return_value=self.root),
                  mock.patch("core.config.get_current_user", side_effect=lambda: self.user)):
            p.start()
            self.addCleanup(p.stop)
        pr.init_project_roles("PROJ", "ADAM")
        pr.set_role("PROJ", "JUN", "junior", actor="ADAM")
        self.client = TestClient(main.app)


class RouteGateTests(_Gates):
    def test_roles_routes(self):
        body = self.client.get("/roles/PROJ").json()
        self.assertEqual(body["me"]["role"], "supervisor")
        self.assertIn("EVA", [m["name"] for m in body["members"]])
        r = self.client.put("/roles/PROJ", json={"user": "EVA", "role": "lead"})
        self.assertEqual(r.status_code, 200, r.text)
        self.user = "JUN"
        r = self.client.put("/roles/PROJ", json={"user": "EVA", "role": "junior"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.post("/roles/PROJ/claim").status_code, 403)
        self.assertEqual(self.client.get("/roles/NOPE").status_code, 404)

    def test_junior_cannot_rename_or_delete_seq_shot(self):
        self.user = "JUN"
        for route in ("delete-seq-shot", "rename-seq-shot"):
            r = self.client.post(f"/production/PROJ/{route}", json={"kind": "seq", "seq": "SEQ0010", "new": "SEQ0020"})
            self.assertEqual(r.status_code, 403, route)
            self.assertIn("Artist", r.json()["detail"])

    def test_artist_cannot_delete_project_or_edit_project_config(self):
        self.user = "EVA"
        self.assertEqual(self.client.delete("/folder/projects/PROJ").status_code, 403)
        r = self.client.put("/folder/projects/PROJ/config", json={"settings": {"fps": 25}})
        self.assertEqual(r.status_code, 403)
        self.assertTrue((self.root / "DOSSIER_PROJETS" / "PROJ").is_dir())

    def test_artist_cannot_empty_archives(self):
        self.user = "EVA"
        arch = self.root / "DOSSIER_PROJETS" / "PROJ" / "ARCHIVE" / "2026-10-24_EVA"
        arch.mkdir(parents=True)
        r = self.client.request("DELETE", "/folder/items",
                                json={"project": "PROJ", "subpath": "ARCHIVE", "name": "2026-10-24_EVA"})
        self.assertEqual(r.status_code, 403)
        self.assertTrue(arch.is_dir())


class JuniorSaveTests(unittest.TestCase):
    def test_existing_records_come_back_new_ones_pass(self):
        prev = {"sequences": [{"id": 1, "name": "SEQ0010"}],
                "shots": [{"id": 2, "seq_id": 1, "name": "SHOT0010", "frame_end": 1050,
                           "task_details": {"anim": {"status": "wip"}}}]}
        new = {"sequences": [{"id": 1, "name": "SEQ9990"}, {"id": 3, "name": "SEQ0020"}],
               "shots": [{"id": 2, "seq_id": 1, "name": "SHOT0010", "frame_end": 2000,
                          "task_details": {"anim": {"status": "done"}}}]}
        restored = lock.keep_all_records(new, prev)
        self.assertEqual(sorted(restored), ["SEQ0010", "SHOT0010"])
        self.assertEqual(new["sequences"][0]["name"], "SEQ0010")
        self.assertEqual(new["sequences"][1]["name"], "SEQ0020")
        self.assertEqual(new["shots"][0]["frame_end"], 1050)
        self.assertEqual(new["shots"][0]["task_details"]["anim"]["status"], "done")

    def test_removed_record_comes_back(self):
        prev = {"sequences": [{"id": 1, "name": "SEQ0010"}], "shots": []}
        new = {"sequences": [], "shots": []}
        lock.keep_all_records(new, prev)
        self.assertEqual([s["name"] for s in new["sequences"]], ["SEQ0010"])


if __name__ == "__main__":
    unittest.main()
