# FLUX Work E2 (ADR 0051): work folders per department, wNNN versions taken by an atomic
# create (never reused, never overwritten), commit checked against the cpio on disk,
# indicative lock with takeover, divergence when the newest version is not the loaded one.

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dcc.houdini.hda.flux_work_io import normalized_hash
from features.houdini_work import work_store as ws
from routers import houdini_work


def _cpio(folder: Path, version: str, body: bytes = b"opparm box1 size ( 1 )\n") -> str:
    path = folder / f"{version}.cpio"
    path.write_bytes(body)
    return normalized_hash(body)


class WorkDir(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name) / "PROJ"
        self.project.mkdir()

    def test_shot_task_lives_in_its_department(self) -> None:
        got = ws.work_dir(self.project, "seq010", "sh020", "cfx")
        self.assertEqual(got, self.project / "shot/SEQ010/SH020/cfx/work/houdini/CFX")

    def test_light_lives_in_the_shot(self) -> None:
        # ADR 0055: LIGHT is a shot department like the others.
        got = ws.work_dir(self.project, "SEQ010", "SH020", "LIGHT")
        self.assertEqual(got, self.project / "shot/SEQ010/SH020/lighting/work/houdini/LIGHT")

    def test_department_without_shot_in_its_template_gets_the_shot(self) -> None:
        # A project made before ADR 0055 keeps LIGHT = lighting/{seq}.
        from core.constants import LEGACY_SHOT_ROOT_TOKENS
        from features.folder_manager.tokens import build_default_tokens, save_tokens

        tokens = build_default_tokens()
        tokens["TYPE_SHOT"].update(LEGACY_SHOT_ROOT_TOKENS)
        save_tokens(self.project, tokens)
        got = ws.work_dir(self.project, "SEQ010", "SH020", "LIGHT")
        self.assertEqual(got, self.project / "lighting/SEQ010/SH020/work/houdini/LIGHT")
        self.assertEqual(ws.work_dir(self.project, "SEQ010", "", "LIGHT"),
                         self.project / "lighting/SEQ010/work/houdini/LIGHT")

    def test_sequence_task(self) -> None:
        self.assertEqual(ws.work_dir(self.project, "SEQ010", "", "LIGHT"),
                         self.project / "shot/SEQ010/lighting/work/houdini/LIGHT")
        self.assertEqual(ws.work_dir(self.project, "SEQ010", "", "FX"),
                         self.project / "shot/SEQ010/fx/work/houdini/FX")
        # Token ending with {shot} (render/{seq}/{shot}): the sequence folder itself.
        self.assertEqual(ws.work_dir(self.project, "SEQ010", "", "RENDER"),
                         self.project / "render/SEQ010/work/houdini/RENDER")

    def test_unknown_task_and_bad_names_are_refused(self) -> None:
        with self.assertRaises(ws.WorkError):
            ws.work_dir(self.project, "SEQ010", "SH020", "NOPE")
        with self.assertRaises(ws.WorkError):
            ws.work_dir(self.project, "../x", "SH020", "CFX")


class Versions(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name) / "work"

    def _save(self, **kw) -> dict:
        res = ws.reserve_version(self.folder, author="adam", host="PC1", **kw)
        h = _cpio(self.folder, res["version"], kw.get("comment", "x").encode())
        return ws.commit_version(self.folder, res["version"], hash=h)

    def test_numbers_follow_and_template_is_w000(self) -> None:
        tpl = ws.reserve_version(self.folder, author="flux", template=True)
        self.assertEqual(tpl["version"], "w000")
        ws.commit_version(self.folder, "w000", hash=_cpio(self.folder, "w000"))
        self.assertEqual(self._save(comment="a")["version"], "w001")
        self.assertEqual(self._save(comment="b")["version"], "w002")
        with self.assertRaises(ws.WorkError):
            ws.reserve_version(self.folder, author="flux", template=True)
        self.assertEqual([v["version"] for v in ws.list_versions(self.folder)], ["w000", "w001", "w002"])

    def test_concurrent_reservations_never_share_a_number(self) -> None:
        got, lock = [], threading.Lock()

        def take():
            v = ws.reserve_version(self.folder, author="a", host="h")["version"]
            with lock:
                got.append(v)
        threads = [threading.Thread(target=take) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(set(got)), 12)

    def test_reservation_is_writing_until_commit(self) -> None:
        res = ws.reserve_version(self.folder, author="adam", host="PC1", based_on="w000", comment="first")
        self.assertEqual(res["state"], "writing")
        self.assertTrue(res["cpio"].endswith("/w001.cpio"))
        self.assertIsNone(ws.latest_ok(self.folder))
        with self.assertRaises(ws.WorkError):            # no cpio yet
            ws.commit_version(self.folder, "w001")
        h = _cpio(self.folder, "w001")
        done = ws.commit_version(self.folder, "w001", hash=h, node_types=[{"type": "Sop/box"}])
        self.assertEqual((done["state"], done["hash"], done["based_on"]), ("ok", h, "w000"))
        with self.assertRaises(ws.WorkError):            # committed twice
            ws.commit_version(self.folder, "w001", hash=h)

    def test_commit_refuses_a_cpio_that_is_not_what_houdini_sent(self) -> None:
        ws.reserve_version(self.folder, author="adam", host="PC1")
        _cpio(self.folder, "w001", b"other content")
        with self.assertRaises(ws.WorkError):
            ws.commit_version(self.folder, "w001", hash="0" * 64)

    def test_abort_drops_a_failed_save_but_never_an_ok_version(self) -> None:
        self._save()
        ws.reserve_version(self.folder, author="adam", host="PC1")
        (self.folder / "w002.cpio.tmp").write_bytes(b"half")
        self.assertTrue(ws.abort_version(self.folder, "w002"))
        self.assertFalse((self.folder / "w002.json").exists())
        self.assertFalse((self.folder / "w002.cpio.tmp").exists())
        self.assertFalse(ws.abort_version(self.folder, "w001"))
        self.assertTrue((self.folder / "w001.cpio").exists())

    def test_crashed_reservation_is_stale_and_its_number_is_not_reused(self) -> None:
        ws.reserve_version(self.folder, author="adam", host="PC1")
        old = time.time() - ws.STALE_WRITING_S - 5
        os.utime(self.folder / "w001.json", (old, old))
        self.assertTrue(ws.list_versions(self.folder)[0]["stale"])
        self.assertEqual(ws.reserve_version(self.folder, author="b", host="PC2")["version"], "w002")


class LockAndStatus(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name) / "work"

    def test_lock_is_indicative_with_traced_takeover(self) -> None:
        self.assertTrue(ws.take_lock(self.folder, author="adam", host="PC1")["ok"])
        self.assertTrue(ws.take_lock(self.folder, author="adam", host="PC1")["ok"])     # same holder
        busy = ws.take_lock(self.folder, author="tom", host="PC2")
        self.assertFalse(busy["ok"])
        self.assertEqual(busy["lock"]["author"], "adam")
        taken = ws.take_lock(self.folder, author="tom", host="PC2", force=True)
        self.assertEqual(taken["lock"]["taken_from"]["author"], "adam")
        self.assertFalse(ws.release_lock(self.folder, author="adam", host="PC1"))       # old holder
        self.assertTrue(ws.release_lock(self.folder, author="tom", host="PC2"))
        self.assertIsNone(ws.read_lock(self.folder))

    def test_status_read_only_and_divergence(self) -> None:
        for _ in range(2):
            r = ws.reserve_version(self.folder, author="adam", host="PC1")
            ws.commit_version(self.folder, r["version"], hash=_cpio(self.folder, r["version"]))
        ws.take_lock(self.folder, author="adam", host="PC1")
        st = ws.task_status(self.folder, based_on="w001", author="tom", host="PC2")
        self.assertEqual(st["latest"], "w002")
        self.assertTrue(st["diverged"])
        self.assertTrue(st["read_only"])
        mine = ws.task_status(self.folder, based_on="w002", author="adam", host="PC1")
        self.assertFalse(mine["diverged"])
        self.assertFalse(mine["read_only"])
        self.assertFalse(mine["has_template"])


class Routes(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name) / "PROJ"
        self.project.mkdir()
        patcher = mock.patch("core.paths.get_project_path", return_value=self.project)
        patcher.start()
        self.addCleanup(patcher.stop)
        app = FastAPI()
        app.include_router(houdini_work.router, prefix="/dcc/houdini/work")
        self.client = TestClient(app)
        self.ref = {"project": "PROJ", "seq": "SEQ010", "shot": "SH020", "task": "CFX"}

    def test_save_cycle_over_http(self) -> None:
        self.assertEqual(self.client.get("/dcc/houdini/work/tasks", params={"project": "PROJ"}).json()["tasks"],
                         ["CFX", "FX", "LIGHT", "RENDER"])
        lock = self.client.post("/dcc/houdini/work/lock", json={**self.ref, "author": "adam", "host": "PC1"}).json()
        self.assertTrue(lock["ok"])
        res = self.client.post("/dcc/houdini/work/reserve",
                               json={**self.ref, "author": "adam", "host": "PC1", "category": "Sop"}).json()
        self.assertEqual(res["version"], "w001")
        cpio = Path(res["cpio"])
        self.assertEqual(cpio.parent, self.project / "shot/SEQ010/SH020/cfx/work/houdini/CFX")
        body = b"opparm box1 size ( 2 )\n"
        cpio.write_bytes(body)
        done = self.client.post("/dcc/houdini/work/commit",
                                json={**self.ref, "version": "w001", "hash": normalized_hash(body)})
        self.assertEqual(done.status_code, 200, done.text)
        st = self.client.get("/dcc/houdini/work/status",
                             params={**self.ref, "based_on": "w001", "author": "adam", "host": "PC1"}).json()
        self.assertEqual((st["latest"], st["diverged"], st["read_only"]), ("w001", False, False))
        manifest = json.loads((cpio.parent / "w001.json").read_text(encoding="utf-8"))
        self.assertEqual((manifest["author"], manifest["category"], manifest["state"]), ("adam", "Sop", "ok"))

    def test_served_module_and_production_shots(self) -> None:
        code = self.client.get("/dcc/houdini/work/module").json()["code"]
        compile(code, "<flux_work module>", "exec")
        for name in ("def load(", "def save(", "def take_over(", "def normalized_hash(", "def load_work("):
            self.assertIn(name, code)
        production = {"sequences": [{"id": "s1", "name": "seq010"}, {"id": "s2", "name": "SEQ020"}],
                      "shots": [{"seq_id": "s1", "name": "sh030"}, {"seq_id": "s1", "name": "SH010"},
                                {"seq_id": "zz", "name": "ORPHAN"}]}
        with mock.patch("features.production.production_store.load_production", return_value=production):
            got = self.client.get("/dcc/houdini/work/shots", params={"project": "PROJ"}).json()
        self.assertEqual(got["sequences"], [{"seq": "SEQ010", "shots": ["SH010", "SH030"]},
                                            {"seq": "SEQ020", "shots": []}])

    def test_tasks_by_network_and_templates(self) -> None:
        lop = self.client.get("/dcc/houdini/work/tasks", params={"project": "PROJ", "category": "Lop"}).json()
        self.assertEqual(lop["tasks"], ["LIGHT", "RENDER"])
        sop = self.client.get("/dcc/houdini/work/tasks", params={"project": "PROJ", "category": "Sop"}).json()
        self.assertEqual(sop["tasks"], ["CFX", "FX"])
        with mock.patch("features.folder_manager.houdini_render_scene.sequence_shots",
                        return_value=[{"shot": "SH010"}, {"shot": "SH020"}, {"shot": "SH030"}, {"shot": "SH040"}]):
            tpl = self.client.get("/dcc/houdini/work/template",
                                  params={"project": "PROJ", "task": "RENDER", "seq": "seq010"}).json()
        self.assertEqual(tpl["source"], "flux")              # the maintainer's render scene, shipped
        self.assertTrue(tpl["cpio"].endswith("resources/scenes/houdini/work/RENDER.cpio"))
        self.assertEqual((tpl["setup"]["seq"], tpl["setup"]["blocks"]), ("SEQ010", 4))
        self.assertIn("def grow_to", tpl["setup"]["sequence_module"])
        cfx = self.client.get("/dcc/houdini/work/template", params={"project": "PROJ", "task": "CFX"}).json()
        self.assertEqual((cfx["cpio"], cfx["setup"]), ("", None))
        own = self.project / "template" / "houdini_work" / "CFX.cpio"
        own.parent.mkdir(parents=True)
        own.write_bytes(b"x")
        cfx = self.client.get("/dcc/houdini/work/template", params={"project": "PROJ", "task": "CFX"}).json()
        self.assertEqual(cfx["source"], "project")

    def test_errors_are_http_errors(self) -> None:
        bad = self.client.post("/dcc/houdini/work/reserve", json={**self.ref, "task": "NOPE"})
        self.assertEqual(bad.status_code, 400)
        missing = self.client.post("/dcc/houdini/work/commit", json={**self.ref, "version": "w009"})
        self.assertEqual(missing.status_code, 409)


if __name__ == "__main__":
    unittest.main()
