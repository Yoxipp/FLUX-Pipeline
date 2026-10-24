# P3 (2026-10-23): action nodes (02_NODES §6). Bodies and simulate called directly
# with a fake ctx; a temp dir is FLUX_ROOT (containment of erase / overwrite).

from __future__ import annotations

import json
import shutil
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from flux_flows.nodes import registry
from flux_flows.nodes.contract import NodeError


def _spec(node_type):
    spec = registry.get_node(node_type)
    assert spec is not None, node_type
    return spec


def _tree(root: Path):
    """Snapshot: every entry under root with its size and mtime."""
    out = {}
    for p in sorted(root.rglob("*")):
        st = p.stat()
        out[p.relative_to(root).as_posix()] = (p.is_dir(), st.st_size, st.st_mtime_ns)
    return out


class ActionNodesTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="flux_action_"))
        self.project = self.root / "DOSSIER_PROJETS" / "DEMO"
        self.project.mkdir(parents=True)
        self.patch = mock.patch("core.paths.get_flux_root", return_value=self.root)
        self.patch.start()
        self.ctx = SimpleNamespace(
            context={"project": "DEMO", "project_path": str(self.project), "user": "ADAM",
                     "date": "2026-10-23", "time": "10-00-00"},
            dry=False, log=lambda *a, **k: None, cancelled=threading.Event())

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    # helpers
    def call(self, node_type, inputs=None, params=None):
        return _spec(node_type).func(self.ctx, dict(inputs or {}), dict(params or {}))

    def sim(self, node_type, inputs=None, params=None):
        before = _tree(self.root)
        res = _spec(node_type).simulate(self.ctx, dict(inputs or {}), dict(params or {}))
        self.assertEqual(before, _tree(self.root), f"{node_type} simulate wrote something")
        self.assertIn("lines", res)
        self.assertIn("outputs", res)
        return res

    def write(self, rel, text="x"):
        p = self.project / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    # -- registry --------------------------------------------------------------
    def test_all_types_declared(self):
        types = ["action.run", "action.rename", "action.move", "action.copy", "action.make_dir",
                 "action.delete", "action.write_json", "action.write_text", "action.list_files",
                 "action.wait", "action.zip_folder", "action.convert_image"]
        for t in types:
            spec = _spec(t)
            outs = [p.name for p in spec.outputs]
            self.assertIn("then", outs, t)
            if t != "action.list_files":
                self.assertTrue(spec.effect, t)
                self.assertIsNotNone(spec.simulate, t)
                self.assertIn("on_error", outs, t)
        self.assertFalse(_spec("action.list_files").effect)
        self.assertFalse([p for p in _spec("action.list_files").inputs if p.name == "exec"][0].required)
        self.assertEqual(_spec("action.copy").destructive, {"param": "overwrite", "equals": True})
        self.assertEqual(_spec("action.delete").destructive, {"param": "mode", "equals": "erase"})
        self.assertEqual(_spec("action.write_text").destructive, {"param": "mode", "equals": "overwrite"})

    # -- delete ----------------------------------------------------------------
    def test_delete_archive_folder_and_file(self):
        self.write("shot/SEQ010/SH010/a.txt")
        f = self.write("shot/SEQ010/notes.txt")
        sim = self.sim("action.delete", {"path": "shot/SEQ010/SH010"})
        self.assertIn("deplacerait", sim["lines"][0]["text_fr"])
        self.assertIn("ARCHIVE", sim["lines"][0]["text_fr"])
        out = self.call("action.delete", {"path": "shot/SEQ010/SH010"})
        dest = Path(out["archived_to"])
        self.assertTrue((dest / "a.txt").is_file())
        self.assertFalse((self.project / "shot/SEQ010/SH010").exists())
        self.assertTrue(dest.is_relative_to(self.project / "ARCHIVE"))
        self.assertTrue(dest.relative_to(self.project / "ARCHIVE").parts[0].endswith("_ADAM"))
        # a single file is archived too
        out = self.call("action.delete", {"path": str(f)})
        self.assertTrue(Path(out["archived_to"]).is_file())
        self.assertFalse(f.exists())

    def test_delete_archive_refuses_outside_project_and_root(self):
        other = self.root / "elsewhere" / "x.txt"
        other.parent.mkdir(parents=True)
        other.write_text("x")
        with self.assertRaises(NodeError):
            self.call("action.delete", {"path": str(other)})
        with self.assertRaises(NodeError):
            self.call("action.delete", {"path": str(self.project)})
        with self.assertRaises(NodeError):
            self.sim("action.delete", {"path": str(other)})
        self.assertTrue(other.exists())

    def test_delete_erase(self):
        self.write("tmp/a.txt")
        self.write("tmp/sub/b.txt")
        sim = self.sim("action.delete", {"path": "tmp"}, {"mode": "erase"})
        self.assertIn("supprimerait 2 fichiers", sim["lines"][0]["text_fr"])
        out = self.call("action.delete", {"path": "tmp"}, {"mode": "erase"})
        self.assertIsNone(out["archived_to"])
        self.assertFalse((self.project / "tmp").exists())

    def test_erase_containment(self):
        outside = Path(tempfile.mkdtemp(prefix="flux_outside_"))
        try:
            (outside / "keep.txt").write_text("x")
            for target in (str(outside), str(self.project), str(self.root / "DOSSIER_PROJETS"), str(self.root)):
                with self.assertRaises(NodeError) as cm:
                    self.call("action.delete", {"path": target}, {"mode": "erase"})
                self.assertEqual(cm.exception.code, "E_PATH_OUTSIDE")
                with self.assertRaises(NodeError):
                    self.sim("action.delete", {"path": target}, {"mode": "erase"})
            self.assertTrue((outside / "keep.txt").exists())
            self.assertTrue(self.project.exists())
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_delete_unknown_mode(self):
        with self.assertRaises(NodeError):
            self.call("action.delete", {"path": "x"}, {"mode": "nuke"})

    # -- copy ------------------------------------------------------------------
    def test_copy_never_overwrites_by_default(self):
        src = self.write("a.txt", "new")
        dst = self.write("b.txt", "old")
        with self.assertRaises(NodeError):
            self.call("action.copy", {"source": str(src), "dest": str(dst)})
        with self.assertRaises(NodeError):
            self.sim("action.copy", {"source": str(src), "dest": str(dst)})
        self.assertEqual(dst.read_text(), "old")
        sim = self.sim("action.copy", {"source": str(src), "dest": str(dst)}, {"overwrite": True})
        self.assertIn("en ecraserait 1", sim["lines"][0]["text_fr"])
        out = self.call("action.copy", {"source": str(src), "dest": str(dst)}, {"overwrite": True})
        self.assertEqual(Path(out["path"]), dst)
        self.assertEqual(dst.read_text(), "new")

    def test_copy_into_existing_folder_keeps_name(self):
        self.write("pub/LAST/a.usd")
        self.write("pub/LAST/b.usd")
        (self.project / "deliv").mkdir()
        sim = self.sim("action.copy", {"source": "pub/LAST", "dest": "deliv"})
        self.assertIn("copierait 2 fichiers", sim["lines"][0]["text_fr"])
        out = self.call("action.copy", {"source": "pub/LAST", "dest": "deliv"})
        self.assertEqual(Path(out["path"]), self.project / "deliv" / "LAST")
        self.assertTrue((self.project / "deliv/LAST/b.usd").is_file())
        f = self.write("one.txt")
        out = self.call("action.copy", {"source": str(f), "dest": "deliv"})
        self.assertEqual(Path(out["path"]), self.project / "deliv" / "one.txt")

    def test_copy_overwrite_outside_root_refused(self):
        outside = Path(tempfile.mkdtemp(prefix="flux_outside_"))
        try:
            (outside / "b.txt").write_text("old")
            src = self.write("a.txt", "new")
            with self.assertRaises(NodeError):
                self.call("action.copy", {"source": str(src), "dest": str(outside / "b.txt")}, {"overwrite": True})
            self.assertEqual((outside / "b.txt").read_text(), "old")
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    # -- move / rename ---------------------------------------------------------
    def test_move_refuses_existing_target(self):
        src = self.write("a.txt", "a")
        dst = self.write("b.txt", "b")
        with self.assertRaises(NodeError):
            self.call("action.move", {"source": str(src), "dest": str(dst)})
        self.assertTrue(src.exists())
        self.sim("action.move", {"source": str(src), "dest": "old/a.txt"})
        out = self.call("action.move", {"source": str(src), "dest": "old/a.txt"})
        self.assertEqual(Path(out["path"]), self.project / "old" / "a.txt")
        self.assertFalse(src.exists())

    def test_rename(self):
        src = self.write("dir/a.txt")
        self.write("dir/b.txt")
        with self.assertRaises(NodeError):
            self.call("action.rename", {"path": str(src), "new_name": "b.txt"})
        with self.assertRaises(NodeError):
            self.sim("action.rename", {"path": str(src), "new_name": "b.txt"})
        with self.assertRaises(NodeError):
            self.call("action.rename", {"path": str(src), "new_name": "sub/c.txt"})
        sim = self.sim("action.rename", {"path": str(src), "new_name": "c.txt"})
        self.assertIn("renommerait", sim["lines"][0]["text_fr"])
        out = self.call("action.rename", {"path": str(src), "new_name": "c.txt"})
        self.assertEqual(Path(out["path"]), self.project / "dir" / "c.txt")
        self.assertTrue((self.project / "dir/c.txt").exists())

    # -- make_dir --------------------------------------------------------------
    def test_make_dir(self):
        self.sim("action.make_dir", {"path": "a/b/c"})
        self.assertFalse((self.project / "a").exists())
        out = self.call("action.make_dir", {"path": "a/b/c"})
        self.assertTrue(Path(out["dir"]).is_dir())
        self.call("action.make_dir", {"path": "a/b/c"})  # exists already: ok
        f = self.write("file.txt")
        with self.assertRaises(NodeError):
            self.call("action.make_dir", {"path": str(f)})

    # -- write_json / write_text -----------------------------------------------
    def test_write_json_modes(self):
        self.sim("action.write_json", {"path": "r/data.json", "data": {"a": 1}})
        out = self.call("action.write_json", {"path": "r/data.json", "data": {"a": 1}})
        p = Path(out["path"])
        self.assertEqual(json.loads(p.read_text(encoding="utf-8")), {"a": 1})
        with self.assertRaises(NodeError):
            self.call("action.write_json", {"path": "r/data.json", "data": {"a": 2}})
        self.call("action.write_json", {"path": "r/data.json", "data": {"a": 2}}, {"mode": "overwrite"})
        self.assertEqual(json.loads(p.read_text(encoding="utf-8")), {"a": 2})
        self.assertFalse(p.with_suffix(".json.tmp").exists())
        with self.assertRaises(NodeError):
            self.call("action.write_json", {"path": "r/x.json", "data": {"a": object()}})
        # T1: dir linked to Path.dir of a folder not created yet arrives empty: say why
        with self.assertRaisesRegex(NodeError, "relie mais vide"):
            self.call("action.write_json", {"dir": "", "data": {"a": 1}}, {"name": "x.json"})

    def test_write_text_modes(self):
        sim = self.sim("action.write_text", {"path": "n.txt", "text": "a"})
        self.assertIn("ecrirait", sim["lines"][0]["text_fr"])
        p = Path(self.call("action.write_text", {"path": "n.txt", "text": "a"})["path"])
        with self.assertRaises(NodeError):
            self.call("action.write_text", {"path": "n.txt", "text": "b"})
        sim = self.sim("action.write_text", {"path": "n.txt", "text": "b"}, {"mode": "append"})
        self.assertIn("ajouterait", sim["lines"][0]["text_fr"])
        self.call("action.write_text", {"path": "n.txt", "text": "b"}, {"mode": "append"})
        self.assertEqual(p.read_text(encoding="utf-8"), "ab\n")      # T1: append = one line per write
        self.call("action.write_text", {"path": "n.txt", "text": "d\n"}, {"mode": "append"})
        self.assertEqual(p.read_text(encoding="utf-8"), "ab\nd\n")
        self.sim("action.write_text", {"path": "n.txt", "text": "c"}, {"mode": "overwrite"})
        self.call("action.write_text", {"path": "n.txt", "text": "c"}, {"mode": "overwrite"})
        self.assertEqual(p.read_text(encoding="utf-8"), "c")
        with self.assertRaises(NodeError):
            self.call("action.write_text", {"path": "n.txt", "text": "c"}, {"mode": "bad"})

    def test_write_overwrite_outside_root_refused(self):
        outside = Path(tempfile.mkdtemp(prefix="flux_outside_"))
        try:
            (outside / "n.txt").write_text("old")
            with self.assertRaises(NodeError):
                self.call("action.write_text", {"path": str(outside / "n.txt"), "text": "x"}, {"mode": "overwrite"})
            self.assertEqual((outside / "n.txt").read_text(), "old")
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    # -- list_files ------------------------------------------------------------
    def test_list_files_pattern_exclusion(self):
        for rel in ("r/b.exr", "r/a.exr", "r/a_tmp.exr", "r/c.png", "r/sub/d.exr"):
            self.write(rel)
        out = self.call("action.list_files", {"folder": "r"}, {"pattern": "*.exr ^*_tmp*"})
        self.assertEqual([Path(p).name for p in out["files"]], ["a.exr", "b.exr"])
        self.assertEqual(out["count"], 2)
        self.assertEqual(Path(out["first"]).name, "a.exr")
        out = self.call("action.list_files", {"folder": "r"}, {"pattern": "*.exr ^*_tmp*", "recursive": True})
        self.assertEqual(sorted(Path(p).name for p in out["files"]), ["a.exr", "b.exr", "d.exr"])
        self.assertEqual(out["files"], sorted(out["files"]))
        out = self.call("action.list_files", {"folder": "r"}, {"kind": "dir"})
        self.assertEqual([Path(p).name for p in out["files"]], ["sub"])
        out = self.call("action.list_files", {"folder": "r"}, {"kind": "both"})
        self.assertEqual(out["count"], 5)
        out = self.call("action.list_files", {"folder": "r"}, {"pattern": "*.mov"})
        self.assertEqual((out["count"], out["first"]), (0, None))
        with self.assertRaises(NodeError) as cm:
            self.call("action.list_files", {"folder": "r"}, {"pattern": "[abc"})
        self.assertEqual(cm.exception.code, "E_PARAM_INVALID")
        with self.assertRaises(NodeError):
            self.call("action.list_files", {"folder": "missing"})

    # -- wait ------------------------------------------------------------------
    def test_wait_honours_cancel(self):
        sim = self.sim("action.wait", {"seconds": 30})
        self.assertIn("attendrait 30 s", sim["lines"][0]["text_fr"])
        threading.Timer(0.1, self.ctx.cancelled.set).start()
        t0 = time.monotonic()
        self.call("action.wait", {"seconds": 30})
        self.assertLess(time.monotonic() - t0, 5)
        with self.assertRaises(NodeError):
            self.call("action.wait", {"seconds": -1})

    def test_wait_waits(self):
        t0 = time.monotonic()
        self.call("action.wait", {"seconds": 0.2})
        self.assertGreaterEqual(time.monotonic() - t0, 0.15)

    # -- zip -------------------------------------------------------------------
    def test_zip_folder(self):
        self.write("pub/a.txt")
        self.write("pub/sub/b.txt")
        sim = self.sim("action.zip_folder", {"folder": "pub", "dest": "deliv/pub.zip"})
        self.assertIn("zipperait", sim["lines"][0]["text_fr"])
        out = self.call("action.zip_folder", {"folder": "pub", "dest": "deliv/pub.zip"})
        z = Path(out["zip"])
        self.assertEqual(z, self.project / "deliv" / "pub.zip")
        with zipfile.ZipFile(z) as zf:
            self.assertEqual(len([n for n in zf.namelist() if not n.endswith("/")]), 2)
        with self.assertRaises(NodeError):
            self.call("action.zip_folder", {"folder": "pub", "dest": "deliv/pub"})
        self.call("action.zip_folder", {"folder": "pub", "dest": "deliv/pub"}, {"overwrite": True})
        with self.assertRaises(NodeError):
            self.call("action.zip_folder", {"folder": "pub", "dest": "pub/self.zip"})

    # -- convert_image ---------------------------------------------------------
    def test_convert_image(self):
        src = self.write("img/a.png")
        sim = self.sim("action.convert_image", {"source": str(src), "dest": "img/a.jpg"})
        self.assertIn("convertirait", sim["lines"][0]["text_fr"])
        with self.assertRaises(NodeError):
            self.sim("action.convert_image", {"source": str(src), "dest": str(src)})
        with self.assertRaises(NodeError):
            self.sim("action.convert_image", {"source": str(src), "dest": "img/noext"})
        try:
            import OpenImageIO as oiio
        except ImportError:
            self.skipTest("OpenImageIO missing")
        buf = oiio.ImageBuf(oiio.ImageSpec(4, 4, 3, oiio.UINT8))
        self.assertTrue(buf.write(str(src)))
        out = self.call("action.convert_image", {"source": str(src), "dest": "img/a.jpg"})
        self.assertTrue(Path(out["path"]).is_file())

    # -- run -------------------------------------------------------------------
    def test_run_simulate_does_not_launch(self):
        scene = self.write("scenes/hero.ma")
        with mock.patch("features.launcher.launcher_core.launch_dcc", return_value=True) as launch:
            sim = self.sim("action.run", {"path": str(scene)})
            launch.assert_not_called()
            self.assertIn("ouvrirait", sim["lines"][0]["text_fr"])
            self.assertIn("maya", sim["lines"][0]["text_fr"])
            out = self.call("action.run", {"path": str(scene)})
            launch.assert_called_once_with("maya", str(scene))
            self.assertTrue(out["launched"])
            hip = self.write("scenes/fx.hipnc")
            self.call("action.run", {"path": str(hip)})
            self.assertEqual(launch.call_args.args[0], "houdini")
            spp = self.write("scenes/tex.spp")
            self.call("action.run", {"path": str(spp)}, {"soft": "painter"})
            self.assertEqual(launch.call_args.args[0], "substance_painter")
        with mock.patch("features.launcher.launcher_core.launch_dcc", return_value=False):
            with self.assertRaises(NodeError):
                self.call("action.run", {"path": str(scene)})
        with self.assertRaises(NodeError):
            self.sim("action.run", {"path": str(self.write("x.unknown"))})


if __name__ == "__main__":
    unittest.main()
