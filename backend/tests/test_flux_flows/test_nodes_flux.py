# P3 (2026-10-23): flux family nodes (02_NODES §7). Bodies and simulate called
# directly with a fake ctx; a temp dir is FLUX_ROOT. Feature calls (publishes_between,
# run_publish_action, send_message, log_event...) are mocked.

from __future__ import annotations

import asyncio
import importlib.util
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from flux_flows.nodes import registry
from flux_flows.nodes.contract import NodeError

_HAS_PXR = importlib.util.find_spec("pxr") is not None


def _spec(node_type):
    spec = registry.get_node(node_type)
    assert spec is not None, node_type
    return spec


def _tree(root: Path):
    out = {}
    for p in sorted(root.rglob("*")):
        st = p.stat()
        out[p.relative_to(root).as_posix()] = (p.is_dir(), st.st_size, st.st_mtime_ns)
    return out


PUBLISHES = [
    {"id": "1", "date": "2026-10-23", "time": "09-00-00", "user": "ADAM", "file": "CHAR_ANIM_HERO_null_v003.mov",
     "dest_folder": ""},
    {"id": "2", "date": "2026-10-23", "time": "10-00-00", "user": "TOM", "file": "CHAR_MOD_HERO_null_LAST.ma",
     "dest_folder": ""},
    {"id": "3", "date": "2026-10-23", "time": "11-00-00", "user": "ADAM", "file": "SEQ010_SHOT010_FX_null_v001.hip",
     "dest_folder": ""},
    {"id": "4", "date": "2026-10-23", "time": "12-00-00", "user": "ADAM", "file": "CHAR_MOD_HERO_null_v002.usd",
     "dest_folder": ""},
]

class DailyRenderExample(unittest.TestCase):
    """shipped/example_daily_render (02 §12 example 3, button only): real run and dry run."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="flux_daily_"))
        self.pub = self.root / "DOSSIER_PROJETS" / "DEMO" / "shots" / "publish"
        self.pub.mkdir(parents=True)
        (self.pub / "SEQ010_SHOT010_ANIM_null_v003.mov").write_bytes(b"mov")
        self.events = [{"id": "1", "date": "2026-10-23", "time": "10-00-00", "user": "ADAM",
                        "file": "SEQ010_SHOT010_ANIM_null_v003.mov", "dest_folder": str(self.pub)},
                       {"id": "2", "date": "2026-10-23", "time": "10-00-00", "user": "ADAM",
                        "file": "CHAR_MOD_HERO_null_v002.usd", "dest_folder": str(self.pub)}]
        self.patches = [mock.patch("core.paths.get_flux_root", return_value=self.root),
                        mock.patch("features.calendar.publishes.publishes_between", return_value=self.events),
                        mock.patch("features.activity.activity_writer.log_event", return_value=True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def _run(self, mode):
        from flux_flows import engine, locations
        from flux_flows.model import load_flow_text

        flow = load_flow_text((locations.shipped_dir() / "example_daily_render.flow.yml").read_text(encoding="utf-8"))

        async def scenario():
            mgr = engine.manager()
            rec = await mgr.submit(engine.Run(flow, scope="team", project="DEMO", user="ADAM", mode=mode,
                                              folder=self.root / "runs"))
            return await mgr.wait(rec["run_id"])

        return asyncio.run(scenario())

    def test_dry_run_writes_nothing(self):
        rec = self._run("dry")
        self.assertEqual(rec["status"], "ok", rec.get("error"))
        self.assertFalse((self.root / "DAILY").exists())

    def test_real_run_copies_the_capture_only(self):
        rec = self._run("real")
        self.assertEqual(rec["status"], "ok", rec.get("error"))
        copied = [p.name for p in (self.root / "DAILY").rglob("*") if p.is_file()]
        self.assertEqual(copied, ["SEQ010_SHOT010_ANIM_null_v003.mov"])


PRODUCTION = {
    "sequences": [{"id": "s1", "name": "SEQ010"}, {"id": "s2", "name": "SEQ020"}],
    "shots": [{"id": "h1", "seq_id": "s1", "name": "SHOT010"}, {"id": "h2", "seq_id": "s2", "name": "SHOT010"}],
    "assets": [{"id": "a1", "class": "CHAR", "name": "HERO"}, {"id": "a2", "class": "PROP", "name": "TREE"},
               {"id": "a3", "class": "SET", "name": "TREE"}],
    "asset_groups": [],
}


class FluxNodesTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="flux_fluxnodes_"))
        self.project = self.root / "DOSSIER_PROJETS" / "DEMO"
        self.project.mkdir(parents=True)
        self.patch = mock.patch("core.paths.get_flux_root", return_value=self.root)
        self.patch.start()
        self.logs = []
        self.ctx = SimpleNamespace(
            context={"project": "DEMO", "project_path": str(self.project), "user": "ADAM",
                     "date": "2026-10-23", "time": "10-00-00"},
            dry=False, log=lambda text, level="info": self.logs.append((level, text)),
            cancelled=threading.Event())
        events = [dict(e, dest_folder=str(self.project / "pub")) for e in PUBLISHES]
        self.events = events

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.root, ignore_errors=True)

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
        effects = ["flux.ping", "flux.log_activity", "flux.archive", "flux.publish_file", "flux.call_function",
                   "flux.conform_texture", "flux.generate_proxy", "flux.usd_flatten", "flux.refresh_component",
                   "flux.refresh_shot_stage"]
        readers = ["flux.find_publishes", "flux.publish_fields", "flux.resolve_path", "flux.project_info",
                   "flux.asset_info", "flux.shot_info", "flux.list_assets", "flux.list_shots", "flux.usd_check"]
        for t in effects:
            spec = _spec(t)
            self.assertTrue(spec.effect, t)
            self.assertIsNotNone(spec.simulate, t)
            self.assertIn("on_error", [p.name for p in spec.outputs], t)
        for t in readers:
            self.assertFalse(_spec(t).effect, t)
        refuse = _spec("flux.refuse_publish")   # P8: effect, simulated, no exit (the run stops there)
        self.assertTrue(refuse.effect)
        self.assertIsNotNone(refuse.simulate)
        self.assertEqual([p.name for p in refuse.outputs], [])
        self.assertIs(_spec("flux.call_function").destructive, True)
        self.assertEqual(_spec("flux.usd_flatten").destructive, {"param": "overwrite", "equals": True})
        self.assertEqual(_spec("flux.conform_texture").destructive, {"param": "force", "equals": True})
        self.assertEqual(_spec("flux.generate_proxy").destructive, {"param": "force", "equals": True})
        self.assertIsNone(_spec("flux.archive").destructive)
        for t in ("flux.find_publishes", "flux.resolve_path"):
            self.assertFalse([p for p in _spec(t).inputs if p.name == "exec"][0].required, t)
        self.assertNotIn("exec", [p.name for p in _spec("flux.publish_fields").inputs])

    # -- find_publishes / publish_fields ----------------------------------------
    def find(self, **params):
        with mock.patch("features.calendar.publishes.publishes_between", return_value=self.events) as pb:
            out = self.call("flux.find_publishes", {}, params)
        return out, pb

    def test_find_publishes_no_filter_and_dates(self):
        out, pb = self.find(date="2026-10-20", date_to="2026-10-23")
        pb.assert_called_once_with("DEMO", "2026-10-20", "2026-10-23")
        self.assertEqual(out["count"], 4)
        first = out["first"]
        self.assertEqual(first["file"], "CHAR_ANIM_HERO_null_v003.mov")
        self.assertEqual(first["version"], 3)
        self.assertEqual(first["type"], "video")
        self.assertEqual(first["soft"], "")
        self.assertEqual(first["name"], "CHAR_ANIM_HERO_null")
        self.assertEqual(Path(first["path"]), self.project / "pub" / "CHAR_ANIM_HERO_null_v003.mov")
        # empty filters = no filter (an empty pattern would keep nothing)
        out, _ = self.find(soft="", type="", name="", user="")
        self.assertEqual(out["count"], 4)

    def test_find_publishes_today_default(self):
        from datetime import date

        _out, pb = self.find()
        today = date.today().isoformat()
        pb.assert_called_once_with("DEMO", today, today)

    def test_find_publishes_filters(self):
        out, _ = self.find(soft="maya houdini", type="capture")
        self.assertEqual([r["file"] for r in out["items"]], ["CHAR_ANIM_HERO_null_v003.mov"])
        out, _ = self.find(soft="maya houdini")   # the video has no known soft: kept
        self.assertEqual([r["id"] for r in out["items"]], ["1", "2", "3"])
        out, _ = self.find(soft="houdini", type="scene")
        self.assertEqual([r["id"] for r in out["items"]], ["3"])
        out, _ = self.find(user="ADAM", name="CHAR_* ^*.mov")
        self.assertEqual([r["id"] for r in out["items"]], ["4"])
        self.assertEqual(out["items"][0]["type"], "usd")
        out, _ = self.find(type="cache")
        self.assertEqual(out["count"], 0)
        self.assertIsNone(out["first"])

    def test_find_publishes_bad_params(self):
        with self.assertRaises(NodeError) as cm:
            self.find(date="hier soir")
        self.assertEqual(cm.exception.code, "E_PARAM_INVALID")
        with mock.patch("features.calendar.publishes.publishes_between", side_effect=ValueError("Plage trop longue")):
            with self.assertRaises(NodeError):
                self.call("flux.find_publishes", {}, {"date": "2020-01-01"})

    def test_publish_fields(self):
        out, _ = self.find()
        rec = out["items"][1]
        f = self.call("flux.publish_fields", {"publish": rec})
        self.assertEqual(f["user"], "TOM")
        self.assertEqual(f["soft"], "maya")
        self.assertEqual(f["type"], "scene")
        self.assertIsNone(f["version"])
        self.assertEqual(f["name"], "CHAR_MOD_HERO_null")
        self.assertEqual(Path(f["dir"]), self.project / "pub")
        f = self.call("flux.publish_fields", {"publish": str(self.project / "x" / "A_B_C_null_v012.abc")})
        self.assertEqual((f["version"], f["type"]), (12, "cache"))
        with self.assertRaises(NodeError):
            self.call("flux.publish_fields", {"publish": None})

    # -- resolve_path ------------------------------------------------------------
    def test_resolve_path_last_and_version(self):
        folder = self.project / "assets" / "CHAR" / "HERO" / "mod" / "null"
        last = folder / "CHAR_MOD_HERO_null_LAST.usd"
        ver = folder / "CHAR_MOD_HERO_null_v002.usd"
        for p in (last, ver):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("#usda 1.0", encoding="utf-8")
        params = {"class": "char", "type": "mod", "name": "hero"}
        with mock.patch("features.publisher.publish_core.resolve_publish_path", return_value=folder) as rp:
            out = self.call("flux.resolve_path", {}, params)
            self.assertEqual(rp.call_args[0][1], "CHAR_MOD_HERO_null_LAST.usd")
            self.assertEqual((Path(out["path"]), out["exists"]), (last, True))
            out = self.call("flux.resolve_path", {}, {**params, "iter": "v002"})
            self.assertEqual(Path(out["path"]), ver)
            out = self.call("flux.resolve_path", {}, {**params, "iter": "v009"})
            self.assertEqual((out["path"], out["exists"], Path(out["dir"])), (None, False, folder))
            with self.assertRaises(NodeError):
                self.call("flux.resolve_path", {}, {**params, "iter": "latest"})
            with self.assertRaises(NodeError):
                self.call("flux.resolve_path", {}, {"class": "CHAR", "type": "MOD"})
        with mock.patch("features.publisher.publish_core.resolve_publish_path", return_value=None):
            with self.assertRaises(NodeError):
                self.call("flux.resolve_path", {}, params)

    # -- project / production readers ---------------------------------------------
    def test_project_info(self):
        with mock.patch("features.folder_manager.tokens.load_tokens", return_value={"CLASS": {}}) as lt:
            out = self.call("flux.project_info", {})
        lt.assert_called_once_with(self.project)
        self.assertEqual(out["name"], "DEMO")
        self.assertEqual(Path(out["path"]), self.project)
        # another project resolves under FLUX_ROOT
        other = self.root / "DOSSIER_PROJETS" / "OTHER"
        other.mkdir()
        with mock.patch("core.paths.get_project_path", return_value=other), \
                mock.patch("features.folder_manager.tokens.load_tokens", return_value={}):
            self.assertEqual(Path(self.call("flux.project_info", {"project": "OTHER"})["path"]), other)
        with mock.patch("core.paths.get_project_path", return_value=self.root / "nope"):
            with self.assertRaises(NodeError):
                self.call("flux.project_info", {"project": "NOPE"})

    def prod(self):
        return mock.patch("features.production.production_store.load_production", return_value=PRODUCTION)

    def test_asset_and_shot_info(self):
        with self.prod(), mock.patch("features.production.archive.resolve_entity_rel",
                                     return_value="assets/CHAR/HERO") as rel:
            out = self.call("flux.asset_info", {"asset": "hero"})
            self.assertTrue(out["found"])
            self.assertEqual(out["class"], "CHAR")
            self.assertEqual(Path(out["folder"]), self.project / "assets" / "CHAR" / "HERO")
            rel.assert_called_with(self.project, "asset", class_token="CHAR", name="HERO")
            self.assertEqual(self.call("flux.asset_info", {"asset": "SET/TREE"})["record"]["id"], "a3")
            with self.assertRaises(NodeError):     # TREE is PROP and SET
                self.call("flux.asset_info", {"asset": "TREE"})
            self.assertFalse(self.call("flux.asset_info", {"asset": "GHOST"})["found"])
            out = self.call("flux.shot_info", {"seq": "seq020", "shot": "shot010"})
            self.assertTrue(out["found"])
            self.assertEqual((out["record"]["id"], out["record"]["seq"]), ("h2", "SEQ020"))
            self.assertFalse(self.call("flux.shot_info", {"seq": "SEQ030", "shot": "SHOT010"})["found"])

    def test_list_assets_and_shots(self):
        with self.prod():
            out = self.call("flux.list_assets", {})
            self.assertEqual(out["names"], ["HERO", "TREE", "TREE"])
            out = self.call("flux.list_assets", {}, {"class": "CHAR PROP"})
            self.assertEqual((out["names"], out["count"]), (["HERO", "TREE"], 2))
            out = self.call("flux.list_shots", {})
            self.assertEqual(out["names"], ["SEQ010/SHOT010", "SEQ020/SHOT010"])
            out = self.call("flux.list_shots", {}, {"seq": "^SEQ01*"})
            self.assertEqual(out["names"], ["SEQ020/SHOT010"])
            with self.assertRaises(NodeError):
                self.call("flux.list_shots", {}, {"seq": "[abc"})

    # -- ping / log_activity --------------------------------------------------------
    def test_ping_writes_a_chat_message(self):
        with mock.patch("features.activity.chat_manager.get_user_list", return_value=["ADAM", "Tom"]), \
                mock.patch("features.activity.chat_manager.send_message", return_value=True) as send, \
                mock.patch("features.activity.activity_writer.log_event") as log_event:
            res = self.sim("flux.ping", {"user": "tom", "text": "daily pret"})
            self.assertIn("@Tom", res["lines"][0]["text_fr"])
            send.assert_not_called()
            self.call("flux.ping", {"user": "@tom", "text": "daily pret"})
            send.assert_called_once_with("ADAM", "@Tom daily pret", "DEMO")
            log_event.assert_not_called()
            with self.assertRaises(NodeError):
                self.call("flux.ping", {"user": "ghost", "text": "x"})
        with mock.patch("features.activity.chat_manager.get_user_list", return_value=["ADAM"]), \
                mock.patch("features.activity.chat_manager.send_message", return_value=False):
            with self.assertRaises(NodeError):
                self.call("flux.ping", {"user": "ADAM", "text": "x"})

    def test_log_activity(self):
        with mock.patch("features.activity.activity_writer.log_event", return_value=True) as log_event:
            self.sim("flux.log_activity", {"text": "Daily copie"})
            log_event.assert_not_called()
            self.call("flux.log_activity", {"text": "Daily copie", "folder": "review"}, {"action": "import"})
            log_event.assert_called_once_with("ADAM", "import", "DEMO", filename="Daily copie",
                                              dest_folder=self.project / "review")
            with self.assertRaises(NodeError):
                self.call("flux.log_activity", {"text": "x"}, {"action": "publish"})

    # -- archive ------------------------------------------------------------------
    def test_archive_moves_into_project_archive(self):
        self.write("shot/SEQ010/tmp/a.txt")
        res = self.sim("flux.archive", {"path": "shot/SEQ010/tmp"})
        dest = Path(res["outputs"]["archived_to"])
        self.assertIn("ARCHIVE", dest.parts)
        out = self.call("flux.archive", {"path": "shot/SEQ010/tmp"})
        self.assertEqual(Path(out["archived_to"]), dest)
        self.assertTrue((dest / "a.txt").is_file())
        self.assertFalse((self.project / "shot" / "SEQ010" / "tmp").exists())

    def test_archive_outside_project_is_an_error(self):
        outside = self.root / "elsewhere"
        outside.mkdir()
        for fn in (self.sim, self.call):
            with self.assertRaises(NodeError) as cm:
                fn("flux.archive", {"path": str(outside)})
            self.assertEqual(cm.exception.code, "E_PATH_OUTSIDE")
        self.assertTrue(outside.is_dir())

    # -- publish_file ---------------------------------------------------------------
    def test_publish_file_simulate_and_run(self):
        src = self.write("work/CHAR_MOD_HERO_null.usd")
        dest_folder = self.project / "assets" / "CHAR" / "HERO" / "mod" / "null"
        with mock.patch("flux_actions.runner.preview_publish_action", return_value=dest_folder) as prev, \
                mock.patch("flux_actions.runner.run_publish_action") as run:
            res = self.sim("flux.publish_file", {"source": "work/CHAR_MOD_HERO_null.usd"})
            run.assert_not_called()
            prev.assert_called_once()
            self.assertIn("v001", res["lines"][0]["text_fr"])
            self.assertEqual(Path(res["outputs"]["path"]), dest_folder / "CHAR_MOD_HERO_null_LAST.usd")
        last = dest_folder / "CHAR_MOD_HERO_null_LAST.usd"
        with mock.patch("flux_actions.runner.run_publish_action", return_value=last) as run:
            out = self.call("flux.publish_file", {"source": str(src)},
                            {"description": "retake", "target_name": "CHAR_MOD_HERO_null.usd"})
        args = run.call_args
        self.assertEqual(args[0][:6], (src, self.project, "retake", "ADAM", "DEMO", "CHAR_MOD_HERO_null.usd"))
        self.assertEqual(Path(out["path"]), last)
        self.assertEqual(out["publish"]["name"], "CHAR_MOD_HERO_null")
        self.assertEqual(out["publish"]["user"], "ADAM")
        with mock.patch("flux_actions.runner.run_publish_action", return_value=None):
            with self.assertRaises(NodeError):
                self.call("flux.publish_file", {"source": str(src)})
        with self.assertRaises(NodeError):
            self.call("flux.publish_file", {"source": "work/missing.usd"})

    # -- call_function ---------------------------------------------------------------
    def test_call_function_refuses_outside_flux_packages(self):
        with mock.patch("os.system") as system:
            for fn in (self.sim, self.call):
                with self.assertRaises(NodeError) as cm:
                    fn("flux.call_function", {"args": {"command": "echo"}}, {"function": "os:system"})
                self.assertEqual(cm.exception.code, "E_PARAM_INVALID")
            for ref in ("subprocess:run", "features._x:y", "features.calendar.publishes:_months", ""):
                with self.assertRaises(NodeError):
                    self.call("flux.call_function", {}, {"function": ref})
            system.assert_not_called()

    def test_call_function_runs_and_simulate_does_not(self):
        ref = "features.folder_manager.naming_validator:format_token"
        with mock.patch("features.folder_manager.naming_validator.format_token") as fake:
            res = self.sim("flux.call_function", {"args": {"raw": "x"}}, {"function": ref})
            self.assertIn("format_token", res["lines"][0]["text_fr"])
            fake.assert_not_called()
        out = self.call("flux.call_function", {"args": {"raw": "hero model"}}, {"function": ref})
        self.assertEqual(out["result"], "HERO_MODEL")
        with self.assertRaises(NodeError):
            self.call("flux.call_function", {"args": {"nope": 1}}, {"function": ref})
        # a missing argument takes the context value of the same name
        out = self.call("flux.call_function", {}, {"function": "features.production.archive:archive_label"})
        self.assertTrue(out["result"].endswith("_ADAM"))

    # -- conform_texture / generate_proxy --------------------------------------------
    def test_conform_texture(self):
        self.write("tex/a.exr")
        self.write("tex/b.png")
        self.write("tex/notes.txt")
        res = self.sim("flux.conform_texture", {"source": "tex"})
        self.assertEqual(res["outputs"]["converted"], 2)
        self.assertEqual(sorted(Path(p).name for p in res["outputs"]["tx_paths"]), ["a.tx", "b.tx"])
        summary = {"tx_paths": [str(self.project / "tex" / "a.tx")], "converted": 1, "skipped": 1, "ignored": 0}
        with mock.patch("flux_actions.runner.run_conform_texture_action", return_value=summary) as run:
            out = self.call("flux.conform_texture", {"source": "tex"}, {"colorconvert": False})
        self.assertEqual(run.call_args[0][:6], (self.project / "tex", None, False, None, None, False))
        self.assertEqual((out["converted"], out["skipped"]), (1, 1))
        with mock.patch("flux_actions.runner.run_conform_texture_action", return_value=None):
            with self.assertRaises(NodeError):
                self.call("flux.conform_texture", {"source": "tex"})
        outside = Path(tempfile.mkdtemp(prefix="flux_out_"))
        try:
            with self.assertRaises(NodeError) as cm:
                self.sim("flux.conform_texture", {"source": "tex"}, {"out_dir": str(outside), "force": True})
            self.assertEqual(cm.exception.code, "E_PATH_OUTSIDE")
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_generate_proxy(self):
        src = self.write("assets/HERO_LAST.usda", "#usda 1.0")
        res = self.sim("flux.generate_proxy", {"source": str(src)})
        self.assertEqual(Path(res["outputs"]["proxy_path"]), src.with_suffix(".proxy.usda"))
        result = {"proxy_path": str(src.with_suffix(".proxy.usda")), "meshes": 3, "tris_out": 900}
        with mock.patch("flux_actions.runner.run_generate_proxy_action", return_value=result) as run:
            out = self.call("flux.generate_proxy", {"source": str(src)}, {"target_reduction": "0.5"})
        self.assertEqual(run.call_args[0][:5], (src, src.with_suffix(".proxy.usda"), 0.5, None, False))
        self.assertEqual((out["mesh_count"], out["tri_count"]), (3, 900))
        with self.assertRaises(NodeError):
            self.call("flux.generate_proxy", {"source": str(src)}, {"min_tris": "beaucoup"})

    # -- usd_check / usd_flatten / refresh -----------------------------------------
    def test_usd_check_uses_v1_command(self):
        src = self.write("assets/HERO_LAST.usda", "#usda 1.0")
        with mock.patch("flux_flows.nodes.flux._run_v1",
                        return_value={"issues": ["pas de defaultPrim"], "count": 1, "ok": False}) as v1:
            out = self.call("flux.usd_check", {"source": str(src)})
        v1.assert_called_once_with(self.ctx, "usd_check", {"source": str(src)})
        self.assertEqual((out["count"], out["ok"]), (1, False))
        with self.assertRaises(NodeError):
            self.call("flux.usd_check", {"source": "assets/none.usda"})

    def test_usd_flatten_create_mode(self):
        src = self.write("stage.usda", "#usda 1.0")
        dest = self.write("deliver/flat.usda", "old")
        with self.assertRaises(NodeError) as cm:
            self.sim("flux.usd_flatten", {"source": str(src), "dest": str(dest)})
        self.assertEqual(cm.exception.code, "E_EXISTS")
        with self.assertRaises(NodeError):
            self.call("flux.usd_flatten", {"source": str(src), "dest": str(dest)})
        self.assertEqual(dest.read_text(encoding="utf-8"), "old")
        with self.assertRaises(NodeError):
            self.sim("flux.usd_flatten", {"source": str(src), "dest": "deliver/flat.txt"})
        res = self.sim("flux.usd_flatten", {"source": str(src), "dest": str(dest)}, {"overwrite": True})
        self.assertIn("ecrase", res["lines"][0]["text_fr"])
        with mock.patch("flux_flows.nodes.flux._run_v1", return_value={"path": str(dest)}) as v1:
            self.call("flux.usd_flatten", {"source": str(src), "dest": str(dest)}, {"overwrite": True})
        v1.assert_called_once_with(self.ctx, "usd_flatten", {"source": str(src), "destination": str(dest)})

    def test_usd_flatten_reports_missing_references(self):
        # T1: a shot stage whose character LAST was archived flattens without it: say so.
        src = self.write("shot/stage.usda", '#usda 1.0\n\ndef "hero" (\n    references = @../assets/HERO_LAST.usda@\n)\n{\n}\n')
        dest = self.project / "deliver" / "flat.usdc"
        res = self.sim("flux.usd_flatten", {"source": str(src), "dest": str(dest)})
        self.assertFalse(res["outputs"]["complete"])
        self.assertTrue(res["outputs"]["missing"][0].endswith("assets/HERO_LAST.usda"), res["outputs"])
        self.assertIn("introuvable", res["lines"][-1]["text_fr"])
        with mock.patch("flux_flows.nodes.flux._run_v1", return_value={"path": str(dest)}):
            out = self.call("flux.usd_flatten", {"source": str(src), "dest": str(dest)})
        self.assertEqual((len(out["missing"]), out["complete"]), (1, False))
        self.write("assets/HERO_LAST.usda", "#usda 1.0\n")
        with mock.patch("flux_flows.nodes.flux._run_v1", return_value={"path": str(dest)}):
            out = self.call("flux.usd_flatten", {"source": str(src), "dest": str(dest)})
        self.assertEqual((out["missing"], out["complete"]), ([], True))

    def test_usd_flatten_refuses_overwrite_outside_pipe(self):
        outside = Path(tempfile.mkdtemp(prefix="flux_out_"))
        try:
            src = self.write("stage.usda", "#usda 1.0")
            dest = outside / "flat.usda"
            dest.write_text("old", encoding="utf-8")
            with self.assertRaises(NodeError) as cm:
                self.call("flux.usd_flatten", {"source": str(src), "dest": str(dest)}, {"overwrite": True})
            self.assertEqual(cm.exception.code, "E_PATH_OUTSIDE")
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    @unittest.skipUnless(_HAS_PXR, "usd-core not installed")
    def test_usd_flatten_real_v1_body(self):
        src = self.write("stage.usda", '#usda 1.0\n(\n    defaultPrim = "World"\n)\ndef Xform "World"\n{\n}\n')
        out = self.call("flux.usd_flatten", {"source": str(src), "dest": "deliver/flat.usda"})
        flat = self.project / "deliver" / "flat.usda"
        self.assertEqual(Path(out["path"]), flat)
        self.assertIn("World", flat.read_text(encoding="utf-8"))

    def test_refresh_nodes(self):
        folder = self.project / "assets" / "CHAR" / "HERO" / "mod" / "null"
        folder.mkdir(parents=True)
        for node_type, key in (("flux.refresh_component", "refresh_component"),
                               ("flux.refresh_shot_stage", "refresh_shot_stage")):
            with mock.patch("flux_flows.nodes.flux._run_v1", return_value={"updated": True}) as v1:
                self.sim(node_type, {"folder": str(folder)}, {"base": "CHAR_MOD_HERO_null"})
                v1.assert_not_called()
                out = self.call(node_type, {"folder": str(folder)}, {"base": "CHAR_MOD_HERO_null", "ext": "usda"})
            v1.assert_called_once_with(self.ctx, key, {"folder": str(folder), "base": "CHAR_MOD_HERO_null",
                                                       "ext": ".usda"})
            self.assertTrue(out["updated"])
            with self.assertRaises(NodeError):
                self.call(node_type, {"folder": str(folder)}, {})

    def test_run_v1_shim_reaches_the_command(self):
        from flux_flows.nodes.flux import _run_v1

        # the v1 command reads the run context through the shim (project_name added)
        out = _run_v1(self.ctx, "format_text", {"template": "{project_name}-{a}", "values": {"a": "x"}})
        self.assertEqual(out, {"text": "DEMO-x"})
        with self.assertRaises(NodeError):
            _run_v1(self.ctx, "no_such_command", {})


if __name__ == "__main__":
    unittest.main()
