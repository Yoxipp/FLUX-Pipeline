# P6c (2026-10-23): an extension soft end to end against a fake soft (the tcp_json template
# in a thread): flows created from the bridge (team nodes session.max_instance and
# dcc.max_publish), Instance, ExtRunScript, publish through a temporary file. Proves the
# protocol and the FLUX side, NOT a real 3ds Max.

from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from flux_flows import dcc_nodes, locations, rights, store
from flux_flows.bridges import extension, flow_templates
from flux_flows.bridges.templates import TEMPLATES_DIR
from flux_flows.nodes import registry
from routers import flows as flows_router
from tests.test_flux_flows import _flow_helpers as h
from tests.test_flux_flows._ext_helpers import MAX_YML, ExtFolder
from tests.test_flux_flows.test_bridge_templates import _free_base

setUpModule = h.setUpModule        # noqa: N816
tearDownModule = h.tearDownModule  # noqa: N816

SAVE = "open(args['path'], 'w').write('max scene ' + rt)\nresult = args['path']\n"


class ExtensionFlows(unittest.TestCase):
    def setUp(self) -> None:
        h.reset()
        self.ext = ExtFolder().__enter__()
        self.base = _free_base()
        self._p = [mock.patch("core.constants.DCC_PORT_RANGES", {})]
        for p in self._p:
            p.start()
        folder = self.ext.add("max", MAX_YML.format(target="x").replace("[7100, 4]", f"[{self.base}, 4]"))
        script = folder / "dcc_side" / "flux_max_bridge.py"
        shutil.copy(TEMPLATES_DIR / "tcp_json_server.py", script)
        (script.parent / "flux_max_bridge.json").write_text(json.dumps(
            {"soft": "max", "port_base": self.base, "port_count": 4}), encoding="utf-8")
        spec = importlib.util.spec_from_file_location("flux_test_max_bridge", script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.fake = mod.start(extra_globals={"rt": "runtime"})
        self.team = self.ext.tmp / "flows"
        self.roots = {"shipped": locations.shipped_dir(), "team": self.team, "project": None, "perso": None}
        self._p += [mock.patch.object(dcc_nodes, "_team_dir", side_effect=lambda: self.team),
                    mock.patch.object(locations, "roots_for", side_effect=lambda **_: dict(self.roots))]
        for p in self._p[1:]:
            p.start()
        dcc_nodes.reset_cache()

    def tearDown(self) -> None:
        self.fake.stop()
        for p in self._p:
            p.stop()
        dcc_nodes.reset_cache()
        self.ext.__exit__(None, None, None)

    def _create(self, **kw):
        return flow_templates.create_flows(extension.get("max"), self.roots, user="ADAM", scene_ext=".max", **kw)

    def test_created_flows_are_nodes(self) -> None:
        done = self._create()
        self.assertEqual([(d["name"], d["status"]) for d in done],
                         [("max_instance", "written"), ("max_publish", "written")])
        self.assertEqual([d["status"] for d in self._create()], ["kept", "kept"])
        inst = registry.get_node("session.max_instance")
        self.assertEqual((inst.label, inst.icon, inst.shelf, inst.source), ("3dsMaxInstance", "Plug", 290, "team"))
        self.assertIn("session[max]", [p.type for p in inst.outputs])
        publish = registry.get_node("dcc.max_publish")
        self.assertEqual(publish.icon, "PackagePlus")
        self.assertTrue(publish.effect)
        catalog = {s.type for s in registry.all_nodes()}
        self.assertTrue({"session.max_instance", "dcc.max_publish", "dcc.ext_run_script"} <= catalog)

    def test_bad_scene_ext_and_bridge_own_flows(self) -> None:
        with self.assertRaisesRegex(ValueError, "extension de scene"):
            flow_templates.create_flows(extension.get("max"), self.roots, user="ADAM", scene_ext="max")
        own = extension.get("max").folder / "flows"
        own.mkdir()
        text = flow_templates.INSTANCE.replace("Live seulement.", "Version maison.")
        (own / "session.flow.yml").write_text(text, encoding="utf-8")
        texts = flow_templates.flow_texts(extension.get("max"), ".max")
        self.assertIn("Version maison.", texts["session"])
        self.assertIn("dcc.max_publish", texts["publish"])

    def test_instance_and_run_script_on_the_fake_soft(self) -> None:
        self._create()
        flow = h.flow({"ev": "event.manual", "inst": ("session.max_instance", {"mode": "live_connect_only"}),
                       "run": ("dcc.ext_run_script", {"code": "result = rt + ' ok'"}), "rec": "action.t_record"},
                      ["ev.then->inst.exec", "inst.then->run.exec", "inst.session->run.session",
                       "run.then->rec.exec", "run.result->rec.value"])
        rec = h.run_flow(flow)
        self.assertEqual(rec["status"], "ok", rec)
        self.assertEqual(h.CALLS[-1][1], "runtime ok")

    def test_dry_run_connects_but_runs_nothing(self) -> None:
        self._create()
        flow = h.flow({"ev": "event.manual", "inst": "session.max_instance",
                       "run": ("dcc.ext_run_script", {"code": "result = 1"}), "rec": "action.t_record"},
                      ["ev.then->inst.exec", "inst.then->run.exec", "inst.session->run.session",
                       "run.then->rec.exec", "run.result->rec.value"])
        rec = h.run_flow(flow, mode="dry")
        self.assertEqual(rec["status"], "ok", rec)
        self.assertEqual(h.CALLS, [])

    def test_publish_saves_a_temp_file_then_publishes_it(self) -> None:
        self._create()
        # The team writes the save code of its soft into the publish node (here: the fake one).
        path = store.working_file(self.team, "max_publish")
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        doc["nodes"]["save"]["params"]["code"] = SAVE
        path.write_text(yaml.safe_dump(doc), encoding="utf-8")
        dcc_nodes.reset_cache()
        published = []

        def fake_publish(source, *args, **kwargs):
            published.append((Path(source).name, Path(source).read_text(encoding="utf-8"), Path(source).parent))
            out = self.ext.tmp / "pub" / "SCENE_LAST.max"
            out.parent.mkdir(exist_ok=True)
            out.write_text("x", encoding="utf-8")
            return out

        flow = h.flow({"ev": "event.manual", "inst": ("session.max_instance", {"mode": "live_connect_only"}),
                       "pub": ("dcc.max_publish", {"name": "SCENE.max"}), "rec": "action.t_record"},
                      ["ev.then->inst.exec", "inst.then->pub.exec", "inst.session->pub.session",
                       "pub.then->rec.exec", "pub.path->rec.value"])
        with mock.patch("flux_actions.runner.run_publish_action", side_effect=fake_publish), \
                mock.patch("flux_flows.nodes.flux._publish_args",
                           side_effect=lambda ctx, inputs, params: (Path(inputs["source"]), "SCENE.max", "ADAM",
                                                                   "DEMO", self.ext.tmp)):
            rec = h.run_flow(flow, checked=False)
        self.assertEqual(rec["status"], "ok", rec)
        self.assertEqual([p[:2] for p in published], [("max_scene.max", "max scene runtime")])
        self.assertTrue(str(h.CALLS[-1][1]).endswith("SCENE_LAST.max"))
        self.assertFalse(published[0][2].exists())          # the temporary folder is removed

    def test_unwritten_save_code_fails_clearly(self) -> None:
        self._create()
        flow = h.flow({"ev": "event.manual", "inst": ("session.max_instance", {"mode": "live_connect_only"}),
                       "pub": "dcc.max_publish"},
                      ["ev.then->inst.exec", "inst.then->pub.exec", "inst.session->pub.session"])
        rec = h.run_flow(flow, checked=False)
        self.assertEqual(rec["status"], "error")
        self.assertIn("code d enregistrement", json.dumps(rec))

    def test_ext_instance_refuses_a_shipped_soft(self) -> None:
        flow = h.flow({"ev": "event.manual", "inst": ("session.ext_instance_core", {"soft": "maya"})},
                      ["ev.then->inst.exec"])
        rec = h.run_flow(flow, checked=False)
        self.assertIn("logiciel livre", json.dumps(rec))


class Route(unittest.TestCase):
    def test_flows_route_needs_team_td(self) -> None:
        app = FastAPI()
        app.include_router(flows_router.router, prefix="/flows")
        client = TestClient(app)
        tmp = Path(tempfile.mkdtemp(prefix="flux_ext_route_"))
        roots = {"shipped": locations.shipped_dir(), "team": tmp, "project": None, "perso": None}
        boxes = {"flows_td": True}
        with ExtFolder() as ext, \
                mock.patch.object(locations, "roots_for", side_effect=lambda **_: dict(roots)), \
                mock.patch.object(dcc_nodes, "_team_dir", side_effect=lambda: tmp), \
                mock.patch.object(rights, "current_rights",
                                  side_effect=lambda: rights.rights_from_data("ADAM", boxes)):
            ext.add("max", MAX_YML.format(target="x"))
            self.assertEqual(client.post("/flows/bridges/max/flows", json={"scene_ext": ".max"}).status_code, 403)
            boxes["flows_team_td"] = True
            r = client.post("/flows/bridges/max/flows", json={"scene_ext": ".max"})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(client.post("/flows/bridges/max/flows", json={"scene_ext": "max"}).status_code, 400)
        dcc_nodes.reset_cache()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
