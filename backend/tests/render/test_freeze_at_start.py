# Freeze when a scheduled job starts: blade script, serial Tractor job, router wiring, team setting.
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pxr import Sdf, UsdUtils

from features.publisher import last_pointer as lp
from features.render import job_builder, team_settings
from features.render.blade import flux_freeze_at_start as blade
from tests.render.studio_fixture import write_env

_LEAF = '#usda 1.0\n(\n    defaultPrim = "A"\n)\ndef Xform "A" {}\n'


def _publish(folder: Path, base: str, ver: int) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    version = folder / f"{base}_v{ver:03d}.usda"
    version.write_text(_LEAF, encoding="utf-8")
    return lp.write_last(folder, base, ".usda", version, ver, lp.MODE_LAYER, user="t")


class BladeScript(unittest.TestCase):
    """Shot stage version folder: entry -> dept LAST + ./casting (-> asset LAST)."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.dept_dir = self.root / "anim"
        self.asset_dir = self.root / "asset"
        _publish(self.dept_dir, "anim", 1)
        _publish(self.asset_dir, "tree", 1)
        self.stage = self.root / "SH_v001"
        self.stage.mkdir()
        casting = Sdf.Layer.CreateNew(str(self.stage / "SH_casting.usda"))
        prim = Sdf.PrimSpec(casting, "tree_01", Sdf.SpecifierDef)
        prim.referenceList.prependedItems = [Sdf.Reference("../asset/tree_LAST.usda")]
        casting.Save()
        entry = Sdf.Layer.CreateNew(str(self.stage / "SH.usda"))
        entry.subLayerPaths[:] = ["../anim/anim_LAST.usda", "./SH_casting.usda"]
        entry.Save()
        self.job = self.root / "render" / "v001" / "_job"
        self.job.mkdir(parents=True)
        self.out = self.job / "SH_frozen.usda"

    def test_reads_the_last_of_render_start(self):
        # Published after the click, before the job starts: the render must read it.
        _publish(self.dept_dir, "anim", 2)
        result = blade.freeze(str(self.stage / "SH.usda"), str(self.out))
        self.assertEqual(result["warnings"], [])
        entry = Sdf.Layer.FindOrOpen(str(self.out))
        self.assertTrue(entry.subLayerPaths[0].endswith("anim/anim_v002.usda"), list(entry.subLayerPaths))
        self.assertTrue(entry.subLayerPaths[1].endswith("_job/SH_casting_frozen.usda"))
        self.assertTrue(entry.customLayerData["flux"]["frozen"])
        casting = Sdf.Layer.FindOrOpen(str(self.job / "SH_casting_frozen.usda"))
        ref = casting.GetPrimAtPath("/tree_01").referenceList.prependedItems[0]
        self.assertTrue(ref.assetPath.endswith("asset/tree_v001.usda"))
        layers, _assets, unresolved = UsdUtils.ComputeAllDependencies(str(self.out))
        self.assertFalse([l for l in layers if "_LAST" in l.identifier])
        self.assertEqual(list(unresolved), [])
        # Sources untouched: the stage version keeps following LAST.
        source = Sdf.Layer.FindOrOpen(str(self.stage / "SH.usda"))
        self.assertIn("anim_LAST", source.subLayerPaths[0])

    def test_drive_letter_case_does_not_matter(self):
        # Houdini's pxr 0.24 computes "c:/..." paths: the casting must still be copied and frozen.
        src = str(self.stage / "SH.usda")
        blade.freeze(src[0].swapcase() + src[1:], str(self.out))
        self.assertTrue((self.job / "SH_casting_frozen.usda").is_file())

    def test_source_last_pointer_uses_its_target(self):
        last = lp.write_last(self.root, "SH", ".usda", self.stage, 1, lp.MODE_LAYER, user="t",
                             layer_target="SH_v001/SH.usda")
        result = blade.freeze(str(last), str(self.out))
        self.assertTrue(result["source"].endswith("SH_v001/SH.usda"))
        self.assertTrue((self.job / "SH_casting_frozen.usda").is_file())

    def test_deeper_last_is_a_warning(self):
        deep = self.dept_dir / "anim_v001.usda"
        deep.write_text('#usda 1.0\n(\n    subLayers = [@../asset/tree_LAST.usda@]\n)\n', encoding="utf-8")
        result = blade.freeze(str(self.stage / "SH.usda"), str(self.out))
        self.assertTrue(any("tree_LAST" in w for w in result["warnings"]))

    def test_missing_source_fails_the_task(self):
        with mock.patch("builtins.print"):
            self.assertEqual(blade.main(["x", str(self.root / "nope.usda"), str(self.out)]), 1)
            self.assertEqual(blade.main(["x"]), 2)


def _spec(**kw) -> job_builder.RenderJobSpec:
    base = dict(title="P SH v001", project="P", user="adam", usd_path="//srv/p/sh/render/v001/_job/SH_frozen.usda",
                output_pattern="//srv/p/sh/render/v001/SH.$F4.exr", frame_start=1, frame_end=10,
                chunk_size=5, service="ROOM0321")
    base.update(kw)
    return job_builder.RenderJobSpec(**base)


class SerialJob(unittest.TestCase):
    def test_freeze_task_runs_before_the_chunks(self):
        alf = job_builder.to_alf(_spec(
            freeze_source="//srv/p/sh/usd/SH_v004/SH.usda",
            freeze_script="//srv/p/sh/render/v001/_job/flux_freeze_at_start.py",
            freeze_python="C:\\Program Files\\Pixar\\Tractor-2.4\\bin\\rmanpy.exe",
            freeze_houdini="C:/Program Files/Side Effects Software/Houdini 21.0.440"))
        self.assertIn("-serialsubtasks 1", alf.splitlines()[1])
        freeze_at = alf.index("gel au demarrage")
        self.assertLess(freeze_at, alf.index("Task -title {rendu} -subtasks {"))
        self.assertLess(freeze_at, alf.index("frames 1-5"))
        self.assertIn("{C:/Program Files/Pixar/Tractor-2.4/bin/rmanpy.exe} "
                      "//srv/p/sh/render/v001/_job/flux_freeze_at_start.py --houdini "
                      "{C:/Program Files/Side Effects Software/Houdini 21.0.440} //srv/p/sh/usd/SH_v004/SH.usda "
                      "//srv/p/sh/render/v001/_job/SH_frozen.usda} -service {ROOM0321}", alf)
        self.assertEqual(alf.count("{"), alf.count("}"))

    def test_no_freeze_task_by_default(self):
        alf = job_builder.to_alf(_spec())
        self.assertNotIn("serialsubtasks", alf)
        self.assertNotIn("gel au demarrage", alf)

    def test_freeze_source_drive_letter_is_refused(self):
        with self.assertRaises(job_builder.JobValidationError):
            job_builder.to_alf(_spec(freeze_source="U:/p/SH.usda", freeze_script="//srv/x.py", freeze_python="p.exe",
                                     freeze_houdini="C:/H", forbid_drive_letters=True))
        with self.assertRaises(job_builder.JobValidationError):
            job_builder.to_alf(_spec(freeze_source="//srv/SH.usda", freeze_script="//srv/x.py", freeze_python="p.exe"))


class Settings(unittest.TestCase):
    def test_freeze_when_and_houdini_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "render.json"
            s = team_settings.read_settings("P", path)
            self.assertEqual(s["freeze_when"], "start")
            self.assertEqual(s["houdini_path"], "")  # no studio default in the code
            with self.assertRaises(ValueError):
                team_settings.write_settings("P", {"freeze_when": "later"}, path)
            s = team_settings.write_settings("P", {"freeze_when": "submit", "houdini_path": "D:\\H21\\"}, path)
            self.assertEqual((s["freeze_when"], s["houdini_path"]), ("submit", "D:/H21"))


class HoudiniLookup(unittest.TestCase):
    """Houdini 20.5 to 22: the python3xx folder is found, never assumed."""

    def setUp(self):
        self.sfx = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.sfx, True)
        for version, py in (("Houdini 20.5.445", "python311"), ("Houdini 22.0.100", "python312"),
                            ("Houdini 21.0.440", "python311")):
            (self.sfx / version / py).mkdir(parents=True)
            (self.sfx / version / py / "python.exe").write_bytes(b"")
        (self.sfx / "Houdini 20.5.445" / "python39").mkdir()   # old leftovers: no python.exe
        (self.sfx / "Houdini Server").mkdir()

    def test_own_python_of_the_team_houdini(self):
        python, hfs = blade.houdini_python(str(self.sfx / "Houdini 22.0.100"))
        self.assertTrue(python.endswith("Houdini 22.0.100/python312/python.exe"))
        python, _ = blade.houdini_python(str(self.sfx / "Houdini 20.5.445"))
        self.assertTrue(python.endswith("Houdini 20.5.445/python311/python.exe"))

    def test_missing_houdini_falls_back_to_the_newest(self):
        python, hfs = blade.houdini_python(str(self.sfx / "Houdini 21.5.1"))
        self.assertTrue(hfs.endswith("Houdini 22.0.100"))
        self.assertTrue(python.endswith("python312/python.exe"))

    def test_no_houdini_fails_the_task(self):
        empty = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, empty, True)
        self.assertEqual(blade.houdini_python(str(empty / "Houdini 21")), (None, None))
        with mock.patch("builtins.print"):
            self.assertEqual(blade.main(["x", "--houdini", str(empty / "Houdini 21"), "a.usda", "b.usda"]), 1)


class RouterWiring(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers import render

        self.render = render
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.render_json = self.tmp / "render.json"
        self.render_json.write_text('{"dry_run": true}', encoding="utf-8")
        app = FastAPI()
        app.include_router(render.router, prefix="/render")
        self.client = TestClient(app)
        self.stage = self.tmp / "stage" / "SQ01_SH010.usda"
        self.stage.parent.mkdir()
        self.stage.write_text(_LEAF, encoding="utf-8")
        self.shot_folder = self.tmp / "shot"
        self.shot_folder.mkdir()
        from features.usd_assembler import shot_stage
        patches = [
            mock.patch.object(render.project_utils, "project_exists", return_value=True),
            mock.patch.object(render.project_utils, "get_project_path", return_value=str(self.tmp)),
            mock.patch("core.paths.get_project_render_path", return_value=self.render_json),
            mock.patch.object(render.config, "get_current_user", return_value="adam"),
            mock.patch.object(render.farm_paths, "_unc_of_drive", return_value=None),
            # Hermetic: no studio environment, and the active user may do everything (roles have their own tests).
            mock.patch.object(render.studio_env, "environment_file", return_value=write_env(self.tmp)),
            mock.patch.object(render.project_roles, "require"),
            mock.patch.dict("os.environ", {"TRACTOR_ENGINE": ""}),
            mock.patch.object(shot_stage, "load_project_production", return_value=({}, False)),
            mock.patch.object(shot_stage, "read_frame_range", return_value=(1, 10)),
            mock.patch.object(shot_stage, "shot_dir", return_value=self.shot_folder),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        stage_info = {"usd": str(self.stage), "frozen": False, "warnings": [], "version": "v004", "audit": {}}
        self.live = mock.patch("features.render.freeze.live_shot", return_value=stage_info)
        self.frozen = mock.patch("features.render.freeze.freeze_shot", return_value={**stage_info, "frozen": True})

    def _submit(self, **body) -> tuple[dict, str]:
        with self.live as live, self.frozen as frozen:
            r = self.client.post("/render/submit", json={"project": "P", "seq": "sq01", "shot": "sh010", **body})
            self.calls = (live.call_count, frozen.call_count)
        self.assertEqual(r.status_code, 200, r.text)
        job = Path(r.json()["output"]) / "_job"
        return r.json(), next(job.glob("*.alf")).read_text(encoding="utf-8")

    def test_scheduled_job_freezes_at_start_by_default(self):
        body, alf = self._submit(start_at="2026-10-24T02:00")
        self.assertEqual(self.calls, (1, 0))
        self.assertEqual(body["freeze_when"], "start")
        self.assertTrue(body["usd"].endswith("_job/SQ01_SH010_frozen.usda"))
        self.assertTrue((Path(body["output"]) / "_job" / "flux_freeze_at_start.py").is_file())
        self.assertIn("gel au demarrage", alf)
        self.assertIn('"frozen": "start"', alf)

    def test_scheduled_job_can_freeze_now(self):
        body, alf = self._submit(start_at="2026-10-24T02:00", freeze_when="submit")
        self.assertEqual(self.calls, (0, 1))
        self.assertEqual(body["freeze_when"], "submit")
        self.assertNotIn("gel au demarrage", alf)

    def test_immediate_job_freezes_now(self):
        body, alf = self._submit()
        self.assertEqual(self.calls, (0, 1))
        self.assertNotIn("gel au demarrage", alf)

    def test_team_default_submit(self):
        self.render_json.write_text(json.dumps({"dry_run": True, "freeze_when": "submit"}), encoding="utf-8")
        _body, alf = self._submit(start_at="2026-10-24T02:00")
        self.assertNotIn("gel au demarrage", alf)

    def test_bad_freeze_when_is_400(self):
        r = self.client.post("/render/submit", json={"project": "P", "seq": "sq01", "shot": "sh010",
                                                      "start_at": "2026-10-24T02:00", "freeze_when": "later"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
