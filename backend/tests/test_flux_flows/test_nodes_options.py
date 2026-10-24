# 2026-10-23: param metadata of the catalog (choices / wirable / tokens) and the
# nodes that use it: action.copy into a folder, action.create_file, write_text with a
# folder, data.token_path. Bodies and simulate called directly with a fake ctx; a temp
# dir is FLUX_ROOT. A promoted (linked) param reaches the body in ``inputs``.

from __future__ import annotations

import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from flux_flows.nodes import registry
from flux_flows.nodes.contract import NodeError
from flux_flows.validate import validate
from tests.test_flux_flows import _flow_helpers as helpers
from tests.test_flux_flows._flow_helpers import flow


def setUpModule() -> None:  # noqa: N802 (unittest API)
    helpers.setUpModule()


def tearDownModule() -> None:  # noqa: N802 (unittest API)
    helpers.tearDownModule()


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


TOKENS = {
    "CLASS": {"CHAR": "assets/chara", "PROPS": "assets/props"},
    "TYPE": {"MOD": "modeling"},
    "TYPE_SHOT": {"ANIM": "shot/{seq}/{shot}/anim"},
    "NAME": {"TREE": "assets/props/TREE_custom"},
    "INSTANCE": {"null": ""},
    "SEQ": {"SEQ010": "shot/SEQ010"},
    "SHOT": {},
}


class CatalogTest(unittest.TestCase):
    def test_port_fields_are_serialised(self):
        params = {p["name"]: p for p in _spec("action.delete").to_dict()["params"]}
        self.assertEqual(params["mode"]["choices"], ["archive", "erase"])
        self.assertTrue(params["mode"]["wirable"])
        self.assertIsNone(params["mode"]["tokens"])
        path = {p["name"]: p for p in _spec("data.path").to_dict()["params"]}
        self.assertFalse(path["value"]["wirable"])
        self.assertIsNone(path["value"]["choices"])
        token = {p["name"]: p for p in _spec("data.token_path").to_dict()["params"]}
        self.assertEqual(token["class"]["tokens"], "CLASS")
        self.assertEqual(token["task"]["tokens"], "TYPE_SHOT")
        self.assertEqual(token["level"]["choices"], ["publish", "last", "entity"])

    def test_default_is_the_first_choice(self):
        for spec in registry.all_nodes():
            for p in spec.params:
                if p.choices and p.default is not None:
                    self.assertEqual(p.choices[0], p.default, f"{spec.type}.{p.name}")

    def test_link_into_a_constant_is_an_error(self):
        f = flow({"ev": "event.manual", "v": ("data.value", {"value": "x"}), "p": ("data.path", {"value": "a"})},
                 ["v.value->p.value"])
        issues = [i for i in validate(f) if i.code == "E_LINK_INVALID"]
        self.assertEqual([(i.node, i.port) for i in issues], [("p", "value")])
        self.assertIn("constante", issues[0].message_fr)
        self.assertEqual(issues[0].fix["kind"], "remove_link")

    def test_value_out_of_choices(self):
        f = flow({"ev": "event.manual", "d": ("action.delete", {"path": "a", "mode": "burn"}),
                  "v": ("data.value", {"type": "float"}), "t": ("action.delete", {"path": "a", "mode": "${m}"})},
                 ["ev.then->d.exec", "d.then->t.exec"], variables=[{"name": "m", "type": "str", "default": "archive"}])
        issues = [(i.node, i.port) for i in validate(f) if i.code == "E_PARAM_INVALID"]
        self.assertEqual(issues, [("d", "mode")])
        f = flow({"ev": "event.manual", "v": ("data.value", {"type": "nope"})}, [])
        self.assertIn(("v", "type"), [(i.node, i.port) for i in validate(f) if i.code == "E_PARAM_INVALID"])


class ChoiceLabelsTest(unittest.TestCase):
    """R1 retake 4: menus keep the declaration order, with readable labels and reserved options."""

    def test_instance_modes_ordered_labelled_farm_reserved(self):
        for node_type in ("session.may_instance", "session.may_instance_core"):
            mode = {p["name"]: p for p in _spec(node_type).to_dict()["params"]}["mode"]
            self.assertEqual(mode["choices"], ["live_connect_or_open", "live_connect_only", "headless", "farm"])
            self.assertEqual(mode["reserved"], ["farm"], node_type)
            self.assertIn("defaut", mode["choice_labels"]["live_connect_or_open"]["fr"])
            self.assertIn("mayapy", mode["choice_labels"]["headless"]["fr"])
            self.assertNotEqual(mode["doc_fr"], "Mode", node_type)   # the subflow node takes the core doc

    def test_label_outside_choices_is_refused(self):
        with self.assertRaises(registry.NodeDefinitionError):
            registry.flow_node("data.tst_bad_label", "TstBadLabel",
                               params=[registry.port("m", "str", choices=("a",), labels={"b": ("B", "B")})])(lambda *a: {})

    def test_plain_port_has_no_labels(self):
        params = {p["name"]: p for p in _spec("action.delete").to_dict()["params"]}
        self.assertIsNone(params["mode"]["choice_labels"])
        self.assertIsNone(params["mode"]["reserved"])

    def test_reserved_choice_is_a_validation_error(self):
        f = flow({"ev": ("event.manual", {}), "n1": ("session.may_instance", {"mode": "farm"})},
                 ["ev.then->n1.exec"])
        self.assertTrue([i for i in validate(f) if i.code == "E_PARAM_INVALID" and i.node == "n1"])

    def test_reserved_choice_generic_message(self):
        registry.flow_node("data.tst_reserved", "TstReserved", outputs=[registry.port("v", "str")],
                           params=[registry.port("m", "str", choices=("a", "b"), reserved=("b",), wirable=False)],
                           )(lambda ctx, inputs, params: {"v": params.get("m")})
        self.addCleanup(registry._REGISTRY.pop, "data.tst_reserved", None)
        f = flow({"ev": ("event.manual", {}), "n1": ("data.tst_reserved", {"m": "b"})}, [])
        issues = [i for i in validate(f) if i.code == "E_PARAM_INVALID" and i.node == "n1"]
        self.assertIn("pas encore disponible", issues[0].message_fr)


class _FsCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="flux_opts_"))
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

    def call(self, node_type, inputs=None, params=None):
        return _spec(node_type).func(self.ctx, dict(inputs or {}), dict(params or {}))

    def sim(self, node_type, inputs=None, params=None):
        before = _tree(self.root)
        res = _spec(node_type).simulate(self.ctx, dict(inputs or {}), dict(params or {}))
        self.assertEqual(before, _tree(self.root), f"{node_type} simulate wrote something")
        return res

    def write(self, rel, text="x"):
        p = self.project / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p


class CopyIntoFolderTest(_FsCase):
    def test_auto_trailing_slash_creates_the_folder(self):
        src = self.write("a.txt", "A")
        sim = self.sim("action.copy", {"source": str(src), "dest": "deliv/day/"})
        self.assertIn("creerait le dossier", sim["lines"][0]["text_fr"])
        out = self.call("action.copy", {"source": str(src), "dest": "deliv/day/"})
        self.assertEqual(Path(out["path"]), self.project / "deliv" / "day" / "a.txt")
        self.assertEqual((self.project / "deliv/day/a.txt").read_text(), "A")

    def test_auto_without_slash_is_a_file(self):
        src = self.write("a.txt", "A")
        out = self.call("action.copy", {"source": str(src), "dest": "deliv/b.txt"})
        self.assertTrue(Path(out["path"]).is_file())
        self.assertEqual(Path(out["path"]).name, "b.txt")

    def test_folder_mode(self):
        src = self.write("a.txt", "A")
        out = self.call("action.copy", {"source": str(src), "dest": "deliv"}, {"dest_is": "folder"})
        self.assertEqual(Path(out["path"]), self.project / "deliv" / "a.txt")
        self.write("pub/LAST/x.usd")
        out = self.call("action.copy", {"source": "pub/LAST", "dest": "out/pub"}, {"dest_is": "folder"})
        self.assertTrue((self.project / "out/pub/LAST/x.usd").is_file())

    def test_file_mode_and_make_dirs_off(self):
        src = self.write("a.txt", "A")
        with self.assertRaises(NodeError):
            self.call("action.copy", {"source": str(src), "dest": "x/y/"}, {"make_dirs": False})
        with self.assertRaises(NodeError):
            self.sim("action.copy", {"source": str(src), "dest": "x/c.txt"}, {"dest_is": "file", "make_dirs": False})
        self.assertFalse((self.project / "x").exists())
        out = self.call("action.copy", {"source": str(src), "dest": "x/y/"}, {"dest_is": "file"})
        self.assertEqual(Path(out["path"]), self.project / "x" / "y")
        self.assertTrue((self.project / "x" / "y").is_file())
        (self.project / "dir").mkdir()
        with self.assertRaises(NodeError):
            self.call("action.copy", {"source": str(src), "dest": "dir"}, {"dest_is": "file"})

    def test_folder_mode_onto_a_file_refused(self):
        src = self.write("a.txt")
        self.write("f.txt")
        with self.assertRaises(NodeError):
            self.call("action.copy", {"source": str(src), "dest": "f.txt"}, {"dest_is": "folder"})


class CreateFileTest(_FsCase):
    def test_name_and_ext(self):
        out = self.call("action.create_file", {"dir": "notes/new"}, {"name": "README", "ext": ".txt", "text": "hi"})
        p = Path(out["path"])
        self.assertEqual(p, self.project / "notes" / "new" / "README.txt")
        self.assertEqual(p.read_text(encoding="utf-8"), "hi")
        out = self.call("action.create_file", {"dir": "notes"}, {"name": "LICENSE", "ext": ""})
        self.assertEqual(Path(out["path"]).name, "LICENSE")
        self.assertEqual(Path(out["path"]).read_text(encoding="utf-8"), "")

    def test_wired_name_wins_over_the_param(self):
        out = self.call("action.create_file", {"dir": "n", "name": "wired"}, {"name": "typed", "ext": "md"})
        self.assertEqual(Path(out["path"]).name, "wired.md")

    def test_exists_refused_in_create_mode(self):
        self.write("n/a.txt", "old")
        with self.assertRaises(NodeError):
            self.call("action.create_file", {"dir": "n"}, {"name": "a", "ext": "txt"})
        self.call("action.create_file", {"dir": "n"}, {"name": "a", "ext": "txt", "text": "new", "mode": "overwrite"})
        self.assertEqual((self.project / "n/a.txt").read_text(encoding="utf-8"), "new")

    def test_bad_names_and_make_dirs_off(self):
        for name in ("", "a/b", "..", "c:d"):
            with self.assertRaises(NodeError, msg=name):
                self.call("action.create_file", {"dir": "n"}, {"name": name, "ext": "txt"})
        with self.assertRaises(NodeError):
            self.call("action.create_file", {"dir": "n"}, {"name": "a", "ext": "t/x"})
        with self.assertRaises(NodeError):
            self.call("action.create_file", {"dir": "missing"}, {"name": "a", "make_dirs": False})

    def test_simulate_writes_nothing(self):
        res = self.sim("action.create_file", {"dir": "deep/er"}, {"name": "a", "ext": "txt"})
        self.assertEqual(res["outputs"]["path"], str(self.project / "deep" / "er" / "a.txt"))
        self.assertEqual([l["kind"] for l in res["lines"]], ["make_dir", "write"])

    def test_flags(self):
        spec = _spec("action.create_file")
        self.assertTrue(spec.effect)
        self.assertTrue(registry.flag_on(spec.destructive, spec, {"mode": "overwrite"}))
        self.assertFalse(registry.flag_on(spec.destructive, spec, {}))

    def test_engine_wires_a_promoted_name(self):
        folder = self.project / "wired"
        f = flow({"ev": "event.manual", "v": ("data.value", {"type": "str", "value": "report"}),
                  "c": ("action.create_file", {"dir": str(folder), "ext": "txt"})},
                 ["ev.then->c.exec", "v.value->c.name"])
        self.assertEqual([i.code for i in validate(f) if i.level == "error"], [])
        rec = helpers.run_flow(f, folder=self.root / "runs")
        self.assertEqual(rec["status"], "ok", rec.get("error"))
        self.assertTrue((folder / "report.txt").is_file())

    def test_engine_passes_a_linked_param_to_params(self):
        # Most bodies read their params from `params`: a linked param must land there too.
        self.write("l/a.txt", "")
        self.write("l/sub/b.txt", "")
        out = self.project / "count.json"
        f = flow({"ev": "event.manual", "v": ("data.value", {"type": "bool", "value": True}),
                  "l": ("action.list_files", {"folder": str(self.project / "l")}),
                  "w": ("action.write_json", {"path": str(out)})},
                 ["ev.then->w.exec", "v.value->l.recursive", "l.count->w.data"])
        rec = helpers.run_flow(f, folder=self.root / "runs")
        self.assertEqual(rec["status"], "ok", rec.get("error"))
        self.assertEqual(out.read_text(encoding="utf-8").strip(), "2")

class WriteTextFolderTest(_FsCase):
    def test_dir_and_name(self):
        out = self.call("action.write_text", {"dir": "r/new", "text": "a"}, {"name": "n.txt"})
        self.assertEqual(Path(out["path"]), self.project / "r" / "new" / "n.txt")
        with self.assertRaises(NodeError):
            self.call("action.write_text", {"dir": "r", "text": "a"})

    def test_path_is_an_existing_folder(self):
        (self.project / "r").mkdir()
        out = self.call("action.write_text", {"path": "r", "text": "a"}, {"name": "n.txt"})
        self.assertEqual(Path(out["path"]), self.project / "r" / "n.txt")
        with self.assertRaises(NodeError):
            self.call("action.write_text", {"path": "r", "text": "a"})

    def test_neither_path_nor_dir(self):
        with self.assertRaises(NodeError):
            self.call("action.write_text", {"text": "a"}, {"name": "n.txt"})

    def test_make_dirs_off(self):
        with self.assertRaises(NodeError):
            self.call("action.write_text", {"path": "no/such/n.txt", "text": "a"}, {"make_dirs": False})
        sim = self.sim("action.write_text", {"path": "no/such/n.txt", "text": "a"})
        self.assertIn("creerait le dossier", sim["lines"][0]["text_fr"])

    def test_write_json_dir_and_name(self):
        out = self.call("action.write_json", {"dir": "j", "data": {"a": 1}}, {"name": "d.json"})
        self.assertTrue(Path(out["path"]).is_file())


class TokenPathTest(_FsCase):
    def setUp(self):
        super().setUp()
        self.tokens = mock.patch("features.folder_manager.tokens.load_tokens", return_value=TOKENS)
        self.tokens.start()

    def tearDown(self):
        self.tokens.stop()
        super().tearDown()

    def test_asset_publish_folder(self):
        out = self.call("data.token_path", {}, {"class": "char", "name": "hero", "type": "MOD"})
        folder = self.project / "assets" / "chara" / "HERO" / "modeling" / "null"
        self.assertEqual(Path(out["path"]), folder)
        self.assertEqual((out["dir"], out["exists"]), ("", False))
        folder.mkdir(parents=True)
        out = self.call("data.token_path", {}, {"class": "CHAR", "name": "HERO", "type": "MOD", "instance": "Body"})
        self.assertEqual(Path(out["path"]).name, "body")
        out = self.call("data.token_path", {}, {"class": "CHAR", "name": "HERO", "type": "MOD"})
        self.assertEqual((Path(out["dir"]), out["exists"]), (folder, True))

    def test_asset_name_token_and_unknown_type(self):
        out = self.call("data.token_path", {}, {"name": "TREE", "type": "SURF"})
        self.assertEqual(Path(out["path"]), self.project / "assets/props/TREE_custom/surf/null")
        with self.assertRaises(NodeError):
            self.call("data.token_path", {}, {"class": "NOPE", "name": "X", "type": "MOD"})
        with self.assertRaises(NodeError):
            self.call("data.token_path", {}, {"class": "CHAR", "name": "HERO"})

    def test_asset_entity_and_last(self):
        out = self.call("data.token_path", {}, {"class": "CHAR", "name": "HERO", "level": "entity"})
        self.assertEqual(Path(out["path"]), self.project / "assets" / "chara" / "HERO")
        params = {"class": "CHAR", "name": "HERO", "type": "MOD", "level": "last"}
        self.assertEqual(self.call("data.token_path", {}, params), {"path": "", "dir": "", "exists": False})
        out = self.call("data.token_path", {}, {**params, "ext": ".usd"})
        self.assertEqual(Path(out["path"]).name, "CHAR_MOD_HERO_null_LAST.usd")
        self.assertFalse(out["exists"])
        last = self.write("assets/chara/HERO/modeling/null/CHAR_MOD_HERO_null_LAST.usd", "#usda 1.0")
        out = self.call("data.token_path", {}, {**params, "ext": "usd"})
        self.assertEqual((Path(out["path"]), out["exists"]), (last, True))

    def test_shot(self):
        params = {"mode": "shot", "seq": "SEQ010", "shot": "SHOT020", "task": "anim"}
        out = self.call("data.token_path", {}, params)
        self.assertEqual(Path(out["path"]), self.project / "shot/SEQ010/SHOT020/anim/null")
        out = self.call("data.token_path", {}, {"mode": "shot", "shot": "SEQ010/SHOT020", "task": "ANIM",
                                                 "level": "entity"})
        self.assertEqual(Path(out["path"]), self.project / "shot/SEQ010/SHOT020")
        out = self.call("data.token_path", {}, {**params, "level": "last", "ext": "usd"})
        self.assertEqual(Path(out["path"]).name, "SEQ010_SHOT020_ANIM_null_LAST.usd")
        with self.assertRaises(NodeError):
            self.call("data.token_path", {}, {**params, "task": "NOPE"})
        with self.assertRaises(NodeError):
            self.call("data.token_path", {}, {"mode": "shot", "seq": "SEQ010", "task": "ANIM"})

    def test_wired_values_and_bad_choices(self):
        out = self.call("data.token_path", {"name": "HERO"}, {"class": "CHAR", "name": "OTHER", "type": "MOD"})
        self.assertIn("/HERO/", out["path"])
        with self.assertRaises(NodeError):
            self.call("data.token_path", {}, {"mode": "prop", "name": "HERO"})
        with self.assertRaises(NodeError):
            self.call("data.token_path", {}, {"level": "deep", "name": "HERO"})

    def test_no_project(self):
        self.ctx.context = {"user": "ADAM"}
        with self.assertRaises(NodeError):
            self.call("data.token_path", {}, {"class": "CHAR", "name": "HERO", "type": "MOD"})

    def test_pure_read_node(self):
        spec = _spec("data.token_path")
        self.assertFalse(spec.effect)
        self.assertEqual([p.name for p in spec.inputs], [])


if __name__ == "__main__":
    unittest.main()


class TokenPathModeTest(_FsCase):
    """R1 retake 2: TokenPath shows its inputs by mode, takes an optional project, and an
    old flow (every param set, links into the other mode) still loads and runs."""

    def setUp(self):
        super().setUp()
        self.tokens = mock.patch("features.folder_manager.tokens.load_tokens", return_value=TOKENS)
        self.tokens.start()

    def tearDown(self):
        self.tokens.stop()
        super().tearDown()

    def test_ports_visible_by_mode(self):
        spec = _spec("data.token_path")
        shown = lambda params: {p.name for p in spec.params if registry.port_visible(spec, p, params)}
        asset, shot = shown({}), shown({"mode": "shot"})
        self.assertTrue({"class", "name", "type", "project", "instance"} <= asset)
        self.assertFalse({"seq", "shot", "task", "ext"} & asset)
        self.assertTrue({"seq", "shot", "task", "project"} <= shot)
        self.assertFalse({"class", "name", "type"} & shot)
        self.assertIn("ext", shown({"level": "last"}))
        self.assertIn("class", shown({"mode": "${mode}"}))     # templated: everything shown
        when = {p["name"]: p["when"] for p in spec.to_dict()["params"]}
        self.assertEqual(when["seq"], {"param": "mode", "in": ["shot"]})
        self.assertIsNone(when["mode"])

    def test_project_param(self):
        other = self.root / "DOSSIER_PROJETS" / "OTHER"
        other.mkdir(parents=True)
        with mock.patch("core.paths.get_project_path", return_value=other):
            out = self.call("data.token_path", {}, {"project": "OTHER", "class": "CHAR", "name": "HERO", "type": "MOD"})
        self.assertEqual(Path(out["path"]), other / "assets" / "chara" / "HERO" / "modeling" / "null")
        out = self.call("data.token_path", {}, {"class": "CHAR", "name": "HERO", "type": "MOD"})
        self.assertTrue(Path(out["path"]).is_relative_to(self.project))

    def test_old_flow_with_every_param_still_runs(self):
        params = {"mode": "shot", "class": "CHAR", "name": "HERO", "type": "MOD",
                  "seq": "SEQ010", "shot": "SHOT010", "task": "ANIM"}
        out = self.call("data.token_path", {}, params)
        self.assertEqual(Path(out["path"]), self.project / "shot" / "SEQ010" / "SHOT010" / "anim" / "null")
        f = flow({"ev": ("event.manual", {}), "t": ("data.token_path", params)}, [])
        self.assertEqual([i for i in validate(f) if i.level == "error"], [])

    def test_link_into_a_hidden_port_is_a_warning(self):
        f = flow({"ev": ("event.manual", {}), "v": ("data.value", {"type": "str", "value": "CHAR"}),
                  "t": ("data.token_path", {"mode": "shot", "seq": "SEQ010", "shot": "SHOT010", "task": "ANIM"})},
                 ["v.value->t.class"])
        hidden = [i for i in validate(f) if i.code == "W_PORT_HIDDEN"]
        self.assertEqual([(i.node, i.port) for i in hidden], [("t", "class")])
        self.assertIn("retire le lien", hidden[0].message_fr)
        f = flow({"ev": ("event.manual", {}), "v": ("data.value", {"type": "str", "value": "CHAR"}),
                  "t": ("data.token_path", {"name": "HERO", "type": "MOD"})}, ["v.value->t.class"])
        self.assertFalse([i for i in validate(f) if i.code == "W_PORT_HIDDEN"])
