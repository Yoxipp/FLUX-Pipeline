# FLUX Work autosave (ADR 0090 point 6): rotating slots, the copy proposed at opening,
# recovery as the next version, the interval setting, the HTTP routes.

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from features.houdini_work import autosave as au
from features.houdini_work import work_store as ws
from routers import houdini_work


def _write(path: Path, body: bytes = b"hip", mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


class Slots(unittest.TestCase):
    def test_first_empty_slot_then_oldest(self) -> None:
        self.assertEqual(au.pick_slot({}), 0)
        self.assertEqual(au.pick_slot({0: 10.0}), 1)
        self.assertEqual(au.pick_slot({0: 10.0, 1: None, 2: 5.0}), 1)
        self.assertEqual(au.pick_slot({0: 30.0, 1: 10.0, 2: 20.0}), 1)

    def test_rotation_keeps_three_copies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "key"
            seen = []
            for i in range(7):
                path = au.next_slot_path(directory, ".hip")
                _write(path, mtime=1000.0 + i)
                seen.append(path.name)
            self.assertEqual(seen[:3], ["a0.hip", "a1.hip", "a2.hip"])
            self.assertEqual(seen[3:6], ["a0.hip", "a1.hip", "a2.hip"])      # oldest first
            self.assertEqual(len(list(directory.iterdir())), 3)

    def test_other_extension_replaces_the_slot_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _write(directory / "a0.hip", mtime=1.0)
            _write(directory / "a1.hip", mtime=2.0)
            _write(directory / "a2.hip", mtime=3.0)
            path = au.next_slot_path(directory, ".hipnc")
            self.assertEqual(path.name, "a0.hipnc")
            self.assertFalse((directory / "a0.hip").exists())

    def test_bad_extension_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ws.WorkError):
                au.next_slot_path(Path(tmp), ".exe")

    def test_scene_key_is_a_safe_folder_name(self) -> None:
        self.assertEqual(au.scene_key("Proj x", "seq010", "", "cfx"), "PROJ-X__SEQ010___" + "__CFX")
        self.assertNotIn("/", au.scene_key("a/b", "..", "c\\d", "t"))

    def test_root_is_local_appdata(self) -> None:
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": "C:/Local"}):
            self.assertEqual(au.autosave_root(), Path("C:/Local/FLUX/houdini_autosave"))


class NewerAutosave(unittest.TestCase):
    def test_only_a_copy_newer_than_the_work_file(self) -> None:
        saves = [(Path("a1.hip"), 200.0), (Path("a0.hip"), 150.0), (Path("a2.hip"), 50.0)]
        self.assertEqual(au.newer_autosave(saves, 100.0), Path("a1.hip"))
        self.assertIsNone(au.newer_autosave(saves, 200.0))
        self.assertIsNone(au.newer_autosave(saves, 199.0))        # within the tolerance
        self.assertIsNone(au.newer_autosave([], 100.0))
        self.assertIsNone(au.newer_autosave(saves, None))


class Interval(unittest.TestCase):
    def test_default_zero_and_clamp(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(au.ENV_MINUTES, None)
            self.assertEqual(au.interval_minutes(), 5)
        for raw, want in (("10", 10), ("0", 0), ("999", au.MAX_MINUTES), ("-3", 0), ("abc", 5), ("", 5)):
            with mock.patch.dict(os.environ, {au.ENV_MINUTES: raw}):
                self.assertEqual(au.interval_minutes(), want, raw)

    def test_advanced_switch(self) -> None:
        from features.settings import advanced

        self.assertIn("houdini_autosave_minutes", advanced.SWITCHES)
        self.assertEqual(advanced._check("houdini_autosave_minutes", 0), 0)
        self.assertEqual(advanced._check("houdini_autosave_minutes", 15), 15)
        for bad in (-1, 121, 2.5, True, "5"):
            with self.assertRaises(ValueError):
                advanced._check("houdini_autosave_minutes", bad)
        with mock.patch.dict(os.environ, {au.ENV_MINUTES: "7"}):
            self.assertEqual(advanced._current("houdini_autosave_minutes"), 7)


class Recovery(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.root = tmp / "local" / "houdini_autosave"
        self.folder = tmp / "share" / "work"
        self.ref = dict(project="PROJ", seq="SEQ010", shot="SH020", task="CFX")
        for number in (1, 2):                                         # w001, w002 committed
            r = ws.reserve_version(self.folder, author="a", ext=".hipnc", **self.ref)
            Path(r["hip"]).write_bytes(b"work %d" % number)
            ws.commit_version(self.folder, r["version"])
        self.w2 = Path(ws.latest_ok(self.folder)["hip"])
        os.utime(self.w2, (1000.0, 1000.0))
        self.dir = au.autosave_dir(self.root, **self.ref)

    def test_no_autosave_no_candidate(self) -> None:
        self.assertIsNone(au.candidate(self.root, self.folder, **self.ref))

    def test_older_autosave_not_proposed(self) -> None:
        _write(self.dir / "a0.hipnc", mtime=900.0)
        self.assertIsNone(au.candidate(self.root, self.folder, **self.ref))
        with self.assertRaises(ws.WorkError):
            au.recover(self.root, self.folder, **self.ref)

    def test_newer_autosave_becomes_next_version(self) -> None:
        _write(self.dir / "a0.hipnc", b"old copy", mtime=1100.0)
        _write(self.dir / "a1.hipnc", b"crash copy", mtime=1200.0)
        found = au.candidate(self.root, self.folder, **self.ref)
        self.assertEqual(Path(found["path"]).name, "a1.hipnc")
        self.assertEqual(found["based_on"], "w002")
        done = au.recover(self.root, self.folder, author="adam", host="pc", **self.ref)
        self.assertEqual(done["version"], "w003")
        self.assertEqual(Path(done["hip"]).read_bytes(), b"crash copy")
        self.assertEqual(self.w2.read_bytes(), b"work 2")             # never overwritten
        latest = ws.latest_ok(self.folder)
        self.assertEqual((latest["version"], latest["based_on"]), ("w003", "w002"))
        self.assertTrue((self.dir / "a1.hipnc").exists())             # copy kept

    def test_after_recovery_nothing_is_proposed_again(self) -> None:
        _write(self.dir / "a0.hipnc", b"crash copy", mtime=1200.0)
        au.recover(self.root, self.folder, **self.ref)
        self.assertIsNone(au.candidate(self.root, self.folder, **self.ref))


class Routes(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.project = tmp / "PROJ"
        self.project.mkdir()
        self.local = tmp / "local"
        app = FastAPI()
        app.include_router(houdini_work.router, prefix="/dcc/houdini/work")
        self.client = TestClient(app)
        patches = [
            mock.patch("core.paths.get_project_path", return_value=self.project),
            mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.local), au.ENV_MINUTES: "9"}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.ref = {"project": "PROJ", "seq": "SEQ010", "shot": "SH020", "task": "CFX"}
        self.folder = ws.work_dir(self.project, "SEQ010", "SH020", "CFX")

    def test_config(self) -> None:
        body = self.client.get("/dcc/houdini/work/autosave/config").json()
        self.assertEqual(body["minutes"], 9)
        self.assertTrue(body["dir"].replace("\\", "/").endswith("FLUX/houdini_autosave"))

    def test_slot_returns_local_path_and_rotates(self) -> None:
        names = []
        for i in range(4):
            res = self.client.post("/dcc/houdini/work/autosave/slot", json={**self.ref, "ext": ".hipnc"}).json()
            path = Path(res["path"])
            self.assertTrue(str(path).replace("\\", "/").startswith(str(self.local).replace("\\", "/")))
            self.assertNotIn(str(self.project).replace("\\", "/"), res["path"])
            _write(path, mtime=100.0 + i)
            names.append(path.name)
        self.assertEqual(names, ["a0.hipnc", "a1.hipnc", "a2.hipnc", "a0.hipnc"])

    def test_candidate_and_recover(self) -> None:
        r = ws.reserve_version(self.folder, author="a", ext=".hipnc", **self.ref)
        Path(r["hip"]).write_bytes(b"w1")
        ws.commit_version(self.folder, "w001")
        os.utime(r["hip"], (500.0, 500.0))
        url = "/dcc/houdini/work/autosave/candidate"
        self.assertIsNone(self.client.get(url, params=self.ref).json()["candidate"])
        slot = self.client.post("/dcc/houdini/work/autosave/slot", json={**self.ref, "ext": ".hipnc"}).json()
        _write(Path(slot["path"]), b"crash", mtime=900.0)
        cand = self.client.get(url, params=self.ref).json()["candidate"]
        self.assertEqual(cand["based_on"], "w001")
        res = self.client.post("/dcc/houdini/work/autosave/recover", json=self.ref).json()
        self.assertEqual(res["version"], "w002")
        self.assertEqual(Path(res["hip"]).read_bytes(), b"crash")
        again = self.client.post("/dcc/houdini/work/autosave/recover", json=self.ref)
        self.assertEqual(again.status_code, 409)


class HdaWiring(unittest.TestCase):
    def test_module_is_valid_python_and_wired(self) -> None:
        from dcc.houdini.hda.flux_work_hda import MODULE_FUNCTIONS

        compile(MODULE_FUNCTIONS, "<flux_work_module>", "exec")
        for token in ("autosave/config", "autosave/slot", "autosave/candidate", "autosave/recover",
                      "addEventLoopCallback", "setName", "_keep_dirty"):
            self.assertIn(token, MODULE_FUNCTIONS)


if __name__ == "__main__":
    unittest.main()
