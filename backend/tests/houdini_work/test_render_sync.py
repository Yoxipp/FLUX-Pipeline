# Render Work <-> Production Timeline (2026-10-10): three-way compare scene / base
# version / Production. Houdini edits are pushed at Save, Timeline edits pulled at opening,
# both sides changed = conflict, unknown shot = create, new Timeline shot = missing block.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from features.houdini_work import render_sync as rsync
from features.houdini_work import work_store as ws
from features.production import production_store as store
from routers import houdini_work


def _production(**ranges) -> dict:
    data = {"sequences": [], "shots": [], "assets": []}
    seq = store.add_sequence(data, "SEQ010")
    for name, rng in ranges.items():
        shot = store.add_shot(data, seq["id"], name)
        if rng:
            shot["frame_start"], shot["frame_end"] = rng
    return data


def _blocks(**ranges) -> list[dict]:
    return [{"block": "SHOT%03d" % (i + 1), "shot": name, "range": list(rng) if rng else None}
            for i, (name, rng) in enumerate(ranges.items())]


class Plan(unittest.TestCase):
    def test_houdini_edit_is_pushed_timeline_edit_is_pulled(self) -> None:
        base = _blocks(SH010=(1001, 1040), SH020=(1001, 1050))
        scene = _blocks(SH010=(1001, 1099), SH020=(1001, 1050))
        prod = _production(SH010=(1001, 1040), SH020=(1001, 1077))
        got = rsync.plan(scene, base, prod, "SEQ010")
        self.assertEqual(got["push"], [{"block": "SHOT001", "shot": "SH010", "range": [1001, 1099]}])
        self.assertEqual(got["pull"], [{"block": "SHOT002", "shot": "SH020", "range": [1001, 1077]}])
        self.assertEqual((got["conflicts"], got["create"], got["missing"]), ([], [], []))

    def test_both_sides_changed_is_a_conflict(self) -> None:
        got = rsync.plan(_blocks(SH010=(1001, 1099)), _blocks(SH010=(1001, 1040)),
                         _production(SH010=(1001, 1077)), "SEQ010")
        self.assertEqual(got["conflicts"], [{"block": "SHOT001", "shot": "SH010",
                                             "houdini": [1001, 1099], "flux": [1001, 1077]}])
        same = rsync.plan(_blocks(SH010=(1001, 1077)), _blocks(SH010=(1001, 1040)),
                          _production(SH010=(1001, 1077)), "SEQ010")
        self.assertEqual(same["conflicts"] + same["push"] + same["pull"], [])

    def test_new_shots_both_ways(self) -> None:
        got = rsync.plan(_blocks(SH010=(1001, 1040), SH060=(1001, 1012)), _blocks(SH010=(1001, 1040)),
                         _production(SH010=(1001, 1040), SH050=(1001, 1033)), "SEQ010")
        self.assertEqual(got["create"], [{"block": "SHOT002", "shot": "SH060", "range": [1001, 1012]}])
        self.assertEqual(got["missing"], [{"shot": "SH050", "range": [1001, 1033]}])

    def test_unresolved_block_never_pushes_and_no_base_means_flux_wins(self) -> None:
        unresolved = rsync.plan(_blocks(SH010=(1, 0)), _blocks(SH010=(1001, 1040)),
                                _production(SH010=(1001, 1040)), "SEQ010")
        self.assertEqual(unresolved["push"] + unresolved["conflicts"], [])
        old_version = rsync.plan(_blocks(SH010=(1001, 1099)), None, _production(SH010=(1001, 1040)), "SEQ010")
        self.assertEqual(old_version["pull"], [{"block": "SHOT001", "shot": "SH010", "range": [1001, 1040]}])
        self.assertEqual(old_version["push"], [])


class Apply(unittest.TestCase):
    def test_push_and_create_respect_locks(self) -> None:
        prod = _production(SH010=(1001, 1040), SH020=(1001, 1050))
        seq_id = prod["sequences"][0]["id"]
        store.find_shot(prod, seq_id, "SH020")["locked"] = {"by": "tom", "at": "x"}
        done = rsync.apply(prod, "SEQ010", [{"shot": "SH010", "range": [1001, 1099]},
                                            {"shot": "SH020", "range": [1001, 1111]}],
                           [{"shot": "sh060", "range": [1001, 1012]}, {"shot": "SH070", "range": [5, 1]}])
        self.assertEqual(done, {"updated": ["SH010"], "created": ["SH060"], "locked": ["SH020"]})
        self.assertEqual(store.find_shot(prod, seq_id, "SH020")["frame_end"], 1050)
        created = store.find_shot(prod, seq_id, "SH060")
        self.assertEqual((created["frame_start"], created["frame_end"], created["origin"]), (1001, 1012, "houdini"))
        self.assertIsNone(store.find_shot(prod, seq_id, "SH070"))

    def test_unknown_sequence_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            rsync.apply(_production(), "SEQ999", [], [])


class Routes(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name) / "PROJ"
        self.project.mkdir()
        mock.patch("core.paths.get_project_path", return_value=self.project).start()
        self.prod = _production(SH010=(1001, 1040), SH020=(1001, 1050))
        mock.patch("features.production.production_store.load_production",
                   side_effect=lambda project: self.prod).start()
        self.addCleanup(mock.patch.stopall)
        app = FastAPI()
        app.include_router(houdini_work.router, prefix="/dcc/houdini/work")
        self.client = TestClient(app)
        self.ref = {"project": "PROJ", "seq": "SEQ010", "shot": "", "task": "RENDER"}

    def test_plan_reads_the_blocks_of_the_base_version(self) -> None:
        folder = ws.work_dir(self.project, "SEQ010", "", "RENDER")
        r = ws.reserve_version(folder, author="adam", host="PC1", template=True)
        Path(r["hip"]).write_bytes(b"x")
        ws.commit_version(folder, "w000", render_blocks=_blocks(SH010=(1001, 1040), SH020=(1001, 1050)))
        got = self.client.post("/dcc/houdini/work/render-sync/plan",
                               json={**self.ref, "base_version": "w000",
                                     "blocks": _blocks(SH010=(1001, 1090), SH020=(1001, 1050))}).json()
        self.assertEqual([p["shot"] for p in got["push"]], ["SH010"])

    def test_apply_goes_through_the_production_save(self) -> None:
        saved = []

        async def fake_put(project, payload):
            saved.append(payload.production)
            return {"success": True, "shot_stages": ["SEQ010_SH010 v002"]}
        with mock.patch("routers.production.put_production", side_effect=fake_put):
            got = self.client.post("/dcc/houdini/work/render-sync/apply",
                                   json={**self.ref, "push": [{"shot": "SH010", "range": [1001, 1090]}],
                                         "create": [{"shot": "SH030", "range": [1001, 1020]}]}).json()
        self.assertEqual((got["updated"], got["created"]), (["SH010"], ["SH030"]))
        self.assertEqual(got["shot_stages"], ["SEQ010_SH010 v002"])
        self.assertEqual(len(saved), 1)
        self.assertEqual(rsync.production_ranges(saved[0], "SEQ010")["SH030"], (1001, 1020))


if __name__ == "__main__":
    unittest.main()
