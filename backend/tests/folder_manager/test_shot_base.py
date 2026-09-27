# 2026-09-19: a shot has the same folders whether it was made in the Folder Manager
# or in Production: the shot, one folder per shot department (layout, anim, cfx, fx),
# its usd/lighting template and its stage. Sub-task folders only when declared.

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from features.folder_manager import houdini_scene_template as hst
from features.folder_manager import seq_shot_creator as ssc
from features.folder_manager.tokens import build_default_tokens, save_tokens
from features.production.sync import sync_production_to_disk

_NO_HIP = {"ok": False, "error": "test"}


def _subdirs(folder: Path) -> set[str]:
    return {p.name for p in folder.iterdir() if p.is_dir()}


class ShotBase(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp(prefix="flux_shotbase_"))
        save_tokens(self.project, build_default_tokens())
        for name in ("create_sequence_render_scene_async",):
            patcher = mock.patch.object(ssc, name, return_value=_NO_HIP)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self.project, ignore_errors=True)

    def test_departments_inside_the_shot_only(self) -> None:
        dirs = ssc.shot_department_dirs(self.project, "SEQ001", "SHOT010")
        self.assertEqual({d.name for d in dirs}, {"layout", "anim", "fx", "cfx", "crowd"})
        self.assertTrue(all(d.parent == self.project / "shot" / "SEQ001" / "SHOT010" for d in dirs))

    def test_folder_manager_and_production_give_the_same_folders(self) -> None:
        with mock.patch("features.usd_assembler.shot_stage.write_stage") as write_stage:
            fm = ssc.create_shot(self.project, 1, 10)
        write_stage.assert_called_once_with(self.project, "SEQ001", "SHOT010")
        production = {"sequences": [{"id": "s1", "name": "SEQ001"}],
                      "shots": [{"seq_id": "s1", "name": "SHOT020", "tasks": []}]}
        sync_production_to_disk(self.project, production)
        prod = self.project / "shot" / "SEQ001" / "SHOT020"
        self.assertEqual(_subdirs(fm) - {"usd"}, {"layout", "anim", "fx", "cfx", "crowd"})
        self.assertEqual(_subdirs(fm), _subdirs(prod))

    def test_sub_task_folders_only_when_declared(self) -> None:
        production = {"sequences": [{"id": "s1", "name": "SEQ001"}],
                      "shots": [{"seq_id": "s1", "name": "SHOT010",
                                 "tasks": [{"name": "ANIM", "known_subtasks": ["dingo"]}]}]}
        sync_production_to_disk(self.project, production)
        shot = self.project / "shot" / "SEQ001" / "SHOT010"
        self.assertEqual(_subdirs(shot / "anim"), {"dingo"})
        self.assertEqual(_subdirs(shot / "layout"), set())

    def test_an_existing_shot_gets_the_base_without_losing_anything(self) -> None:
        shot = self.project / "shot" / "SEQ001" / "SHOT010"
        (shot / "anim" / "dingo").mkdir(parents=True)
        (shot / "anim" / "dingo" / "keep.txt").write_text("keep", encoding="utf-8")
        created = ssc.ensure_shot_base(self.project, "SEQ001", "SHOT010")
        self.assertEqual({p.name for p in created}, {"layout", "fx", "cfx", "crowd"})
        self.assertEqual((shot / "anim" / "dingo" / "keep.txt").read_text(encoding="utf-8"), "keep")
        self.assertEqual(ssc.ensure_shot_base(self.project, "SEQ001", "SHOT010"), [])


class ShotHipScene(unittest.TestCase):
    """The per-shot .hip was never written: hython loaded the .hipnc seed first, which
    made a commercial session non commercial and its .hip save fail (2026-09-19)."""

    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp(prefix="flux_shothip_"))
        self.shot = self.project / "shot" / "SEQ001" / "SHOT010"
        self.shot.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.project, ignore_errors=True)

    def test_built_from_an_empty_scene_with_the_licence_extension(self) -> None:
        script = hst._gen_script(None, "C:/p/SEQ001_SHOT010_light", "flux_shot",
                                 {"project": "PROJ", "seq": "SEQ001", "shot": "SHOT010"})
        compile(script, "gen", "exec")
        self.assertIn("'flux_shot'", script)
        self.assertIn("'shot': 'SHOT010'", script)
        self.assertIn('createNode("lopnet", "stage")', script)
        self.assertIn("hou.hipFile.clear(", script)
        self.assertIn("licenseCategory()", script)
        self.assertIn("'C:/p/SEQ001_SHOT010_light' + _ext", script)

    def test_a_hipnc_template_is_never_loaded(self) -> None:
        tpl = self.project / "template"
        tpl.mkdir()
        (tpl / "flux_template_shot.hipnc").write_bytes(b"x")
        self.assertIsNone(hst.loadable_template(self.project, hst._SHOT_TEMPLATE_NAMES))
        (tpl / "flux_template_shot.hip").write_bytes(b"x")
        self.assertEqual(hst.loadable_template(self.project, hst._SHOT_TEMPLATE_NAMES),
                         tpl / "flux_template_shot.hip")

    def test_an_existing_scene_of_any_licence_is_kept(self) -> None:
        light = self.shot / "usd" / "lighting"
        light.mkdir(parents=True)
        (light / "SEQ001_SHOT010_light.hipnc").write_bytes(b"artist")
        with mock.patch.object(hst, "_run_offline") as run:
            res = hst.create_shot_hip_scene(self.shot, "SEQ001", "SHOT010")
        run.assert_not_called()
        self.assertTrue(res["ok"])
        self.assertTrue(res["path"].endswith("SEQ001_SHOT010_light.hipnc"))

    def test_the_saved_path_comes_from_hython(self) -> None:
        with mock.patch.object(hst, "_run_offline",
                               return_value={"ok": True, "path": "X/SEQ001_SHOT010_light.hip"}) as run:
            res = hst.create_shot_hip_scene(self.shot, "SEQ001", "SHOT010")
        self.assertEqual(res["created"], ["X/SEQ001_SHOT010_light.hip"])
        self.assertIn("hou.hipFile.clear(", run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
