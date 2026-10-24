# P6b (2026-10-23): Nuke, Painter, Designer, Marvelous, ZBrush and Mari nodes against fake
# bridges (TCP JSON on a free port, a temporary mailbox): calls, errors, closed port, ZBrush
# always released, publish black boxes in a thread on the Publisher's instance. Never the softs.

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from flux_flows.bridges import primitives, softs
from tests.test_flux_flows import _flow_helpers as h
from tests.test_flux_flows._fake_bridges import FakeTcpJson, free_port

setUpModule = h.setUpModule        # noqa: N816
tearDownModule = h.tearDownModule  # noqa: N816


def run_node(soft: str, node_type: str, port, params=None, inputs=None, out=None, mode="real", project=None):
    prefix = softs.get(soft).prefix
    nodes = {"ev": "event.manual", "inst": f"session.{prefix}_instance",
             "n": (node_type, {**(params or {}), **(inputs or {})}), "rec": "action.t_record"}
    links = ["ev.then->inst.exec", "inst.then->n.exec", "inst.session->n.session", "n.then->rec.exec"]
    if out:
        links.append(f"n.{out}->rec.value")
    flow = h.flow(nodes, links)
    instances = [] if port is None else [{"port": port, "pid": 1}]
    with mock.patch.object(primitives, "scan_ports", return_value=instances), \
            mock.patch("core.dcc_instances.resolve_port", return_value=port):
        if project is None:
            rec = h.run_flow(flow, mode=mode, checked=False)
        else:
            import asyncio
            from flux_flows import engine

            async def scenario():
                mgr = engine.manager()
                run = engine.Run(flow, scope="team", project=project, user="ADAM", mode=mode, checked=True)
                return await mgr.wait((await mgr.submit(run))["run_id"])

            rec = asyncio.run(scenario())
    return rec, (h.CALLS[-1][1] if h.CALLS else None)


class Registry(unittest.TestCase):
    def test_prefixes_and_ranges(self) -> None:
        from core.constants import DCC_PORT_RANGES

        self.assertEqual(len({s.prefix for s in softs.SOFTS.values()}), len(softs.SOFTS))
        spans = sorted((b, b + n) for b, n in DCC_PORT_RANGES.values())
        for (a0, a1), (b0, _b1) in zip(spans, spans[1:]):
            self.assertLessEqual(a1, b0)
        for s in softs.SOFTS.values():
            self.assertIn(s.dcc_key, DCC_PORT_RANGES)

    def test_bridge_plus_verbs_are_nodes(self) -> None:
        # P6b step 9 (2026-10-24): the 24 "bridge+" verbs got their bridge command.
        from flux_flows.nodes import registry

        for prefix in ("sp", "sd", "zb", "mari", "mvd"):
            verbs = ("open_scene", "save_scene", "save_as", "run_script") + (("import",) if prefix != "mvd" else ())
            for verb in verbs:
                self.assertIsNotNone(registry.get_node(f"dcc.{prefix}_{verb}"), f"{prefix}_{verb}")
        self.assertIsNotNone(registry.get_node("dcc.nk_run_script"))


class Nuke(unittest.TestCase):
    def setUp(self) -> None:
        h.reset()
        self.codes = []

        def handler(req):
            if req.get("cmd") == "ping":
                return {"ok": True, "version": "15.1"}
            code = req.get("code", "")
            self.codes.append(code)
            if "allNodes" in code:
                return {"ok": True, "result": [["Write1", "Write"], ["Read1", "Read"], ["Write_tmp", "Write"]]}
            if "boom" in code:
                return {"ok": False, "error": "NameError: boom"}
            return {"ok": True, "result": "/p/out.exr"}

        self.srv = FakeTcpJson(handler).start()

    def tearDown(self) -> None:
        self.srv.close()

    def test_run_script_find_export_and_errors(self) -> None:
        rec, value = run_node("nuke", "dcc.nk_run_script", self.srv.port, inputs={"code": "result = 1"}, out="result")
        self.assertEqual((rec["status"], value), ("ok", "/p/out.exr"))
        self.assertIn("args = ", self.codes[-1])
        rec, value = run_node("nuke", "dcc.nk_find_nodes", self.srv.port, {"pattern": "Write* ^*_tmp", "class": "Write"},
                              out="nodes")
        self.assertEqual(value, ["Write1"])
        tmp = Path(tempfile.mkdtemp())
        try:
            rec, value = run_node("nuke", "dcc.nk_export", self.srv.port, {"frame_range": "1-3"},
                                  {"path": str(tmp / "out.%04d.exr"), "node": "Merge1"}, "files")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn("nuke.execute(_w, 1, 3)", self.codes[-1])
        self.assertIn('nuke.toNode("Merge1")', self.codes[-1])
        rec, _ = run_node("nuke", "dcc.nk_run_script", self.srv.port, inputs={"code": "boom"})
        self.assertIn("boom", rec["nodes"]["n"]["error"])

    def test_closed_port(self) -> None:
        rec, _ = run_node("nuke", "dcc.nk_run_script", free_port(), inputs={"code": "result = 1"})
        self.assertEqual(rec["status"], "error")


class TcpBridges(unittest.TestCase):
    """Painter, Designer, Mari, ZBrush: {"action"} bridges on a free port."""

    def setUp(self) -> None:
        h.reset()
        self.requests = []

        def handler(req):
            self.requests.append(req)
            action = req.get("action")
            if action == "ping":
                return {"status": "ok", "version": "test"}
            if action == "info":
                return {"status": "ok", "project": "chair.spp", "texture_sets": [{"name": "body"}], "geo": "chair",
                        "channels": ["BaseColor", "Roughness"]}
            if action == "get_mesh_info":
                return {"status": "ok", "points": 12, "polys": 10}
            if action and action.startswith("export"):
                return {"status": "ok", "files": ["/t/a.png"]}
            if action == "stop":
                return {"status": "ok"}
            return {"status": "error", "msg": "unknown"}

        self.srv = FakeTcpJson(handler).start()
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_tcp_softs_"))

    def tearDown(self) -> None:
        self.srv.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_exports_and_infos_on_the_session_port(self) -> None:
        for soft, node, params, out, expected in (
                ("painter", "dcc.sp_export", {"format": "exr"}, "files", ["/t/a.png"]),
                ("designer", "dcc.sd_export", {"sbsar": True}, "files", ["/t/a.png"]),
                ("mari", "dcc.mari_export", {"channels": ["BaseColor"]}, "files", ["/t/a.png"])):
            with self.subTest(soft=soft):
                rec, value = run_node(soft, node, self.srv.port, params, {"path": str(self.tmp)}, out)
                self.assertEqual((rec["status"], value), ("ok", expected), rec.get("error"))
        self.assertEqual(run_node("painter", "dcc.sp_info", self.srv.port, out="texture_sets")[1], ["body"])
        self.assertEqual(run_node("mari", "dcc.mari_info", self.srv.port, out="channels")[1], ["BaseColor", "Roughness"])
        self.assertEqual(run_node("zbrush", "dcc.zb_mesh_info", self.srv.port, out="info")[1]["points"], 12)
        self.assertTrue(any(r.get("export_path") == str(self.tmp).replace("\\", "/") or r.get("export_path") == str(self.tmp)
                            for r in self.requests if r.get("action") == "export"))

    def test_zbrush_is_released_after_an_export_and_on_error(self) -> None:
        rec, value = run_node("zbrush", "dcc.zb_export", self.srv.port, inputs={"path": str(self.tmp / "head.obj")},
                              out="files")
        self.assertEqual(rec["status"], "ok", rec.get("error"))
        actions = [r["action"] for r in self.requests]
        self.assertEqual(actions.count("export_obj"), 1)
        self.assertGreaterEqual(actions.count("stop"), 2)             # after the call + the run's cleanup
        self.requests.clear()
        rec, _ = run_node("zbrush", "dcc.zb_export", self.srv.port, inputs={"path": str(self.tmp / "head.abc")})
        self.assertIn("extension", rec["nodes"]["n"]["error"])
        self.assertNotIn("export_abc", [r["action"] for r in self.requests])   # refused before any call

    def test_zbrush_released_when_the_export_fails(self) -> None:
        def handler(req):
            if req.get("action") == "ping":
                return {"status": "ok"}
            if req.get("action") == "stop":
                stops.append(1)
                return {"status": "ok"}
            return {"status": "error", "msg": "ZBrush a refuse"}

        stops = []
        with FakeTcpJson(handler) as srv:
            rec, _ = run_node("zbrush", "dcc.zb_export", srv.port, inputs={"path": str(self.tmp / "head.ztl")})
        self.assertIn("ZBrush a refuse", rec["nodes"]["n"]["error"])
        self.assertGreaterEqual(len(stops), 2)

    def test_dry_run_sends_no_export(self) -> None:
        rec, _ = run_node("painter", "dcc.sp_export", self.srv.port, inputs={"path": str(self.tmp)}, mode="dry")
        self.assertEqual(rec["status"], "ok", rec.get("error"))
        self.assertFalse([r for r in self.requests if r.get("action") == "export"])


class Marvelous(unittest.TestCase):
    def setUp(self) -> None:
        h.reset()
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_mvd_"))
        self.box = self.tmp / "flux_marvelous_bridge"
        self.box.mkdir()
        self._env = mock.patch.dict(os.environ, {"FLUX_MD_MAILBOX_ROOT": str(self.tmp)})
        self._env.start()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self._beat()
        self.thread.start()

    def tearDown(self) -> None:
        self.stop.set()
        self.thread.join(2)
        self._env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _beat(self) -> None:
        tmp = self.box / "alive.json.tmp"
        tmp.write_text(json.dumps({"time": time.time(), "pid": os.getpid(), "version": "MD 2024"}), encoding="utf-8")
        os.replace(tmp, self.box / "alive.json")

    def _serve(self) -> None:
        while not self.stop.is_set():
            self._beat()
            for req in list(self.box.glob("*.req")):
                payload = json.loads(req.read_text(encoding="utf-8"))
                req.unlink()
                action = payload.get("action")
                answer = {"info": {"status": "ok", "project": "dress.zprj", "formats": ["abc", "obj"]},
                          "export": {"status": "ok", "files": ["/c/dress.abc"], "warnings": ["sim courte"]},
                          "import": {"status": "ok", "function": "import_obj"}}.get(action, {"status": "error"})
                (self.box / (req.name[:-4] + ".resp")).write_text(json.dumps(answer), encoding="utf-8")
            time.sleep(0.02)

    def test_mailbox_session_info_export_import(self) -> None:
        rec, value = run_node("marvelous", "dcc.mvd_info", None, out="formats")
        self.assertEqual((rec["status"], value), ("ok", ["abc", "obj"]), rec.get("error"))
        rec, value = run_node("marvelous", "dcc.mvd_export", None, inputs={"path": str(self.tmp / "out"), "name": "dress"},
                              out="files")
        self.assertEqual(value, ["/c/dress.abc"])
        self.assertTrue(any("sim courte" in l["text"] for l in rec["nodes"]["n"].get("logs", [])))
        rec, value = run_node("marvelous", "dcc.mvd_import", None, inputs={"path": str(self.tmp / "body.obj")}, out="nodes")
        self.assertEqual(value, ["import_obj"])


class Publish(unittest.TestCase):
    def setUp(self) -> None:
        h.reset()
        self.srv = FakeTcpJson(lambda req: {"status": "ok"}).start()
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_pub_softs_"))
        (self.tmp / "PROJ").mkdir()
        self._p = [mock.patch("core.paths.get_project_path", side_effect=lambda name: self.tmp / name),
                   mock.patch.object(primitives, "ping", side_effect=lambda soft, port=None: {"ok": True, "version": "t",
                                                                                              "port": port})]
        for p in self._p:
            p.start()

    def tearDown(self) -> None:
        for p in self._p:
            p.stop()
        self.srv.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_black_boxes_call_the_publisher_in_a_thread(self) -> None:
        cases = (("painter", "dcc.sp_publish", "dcc.substance_painter.substance_export.publish_painter",
                  {"class": "PROP", "task": "TEXTURE", "name": "chair"}),
                 ("designer", "dcc.sd_publish", "dcc.substance_designer.designer_export.publish_designer",
                  {"class": "PROP", "task": "TEXTURE", "name": "rock"}),
                 ("mari", "dcc.mari_publish", "dcc.mari.mari_export.publish_mari",
                  {"class": "PROP", "task": "TEXTURE", "name": "chair"}),
                 ("nuke", "dcc.nk_publish", "dcc.nuke.nuke_publish.publish_from_nuke", {"name": "SH010_COMP_main"}),
                 ("zbrush", "dcc.zb_publish", "dcc.zbrush.zbrush_export.publish_zbrush", {"name": "CHAR_SCULPT_head"}))
        for soft, node, target, inputs in cases:
            with self.subTest(soft=soft):
                seen = {}

                def fake(*args, **kwargs):
                    seen.update(thread=threading.current_thread().name, args=args, kwargs=kwargs)
                    return {"ok": True, "published": [str(self.tmp / "x_v004.png")], "version": 4}

                base = softs.port_range(soft).start
                with mock.patch(target, side_effect=fake), mock.patch("dcc.zbrush.client.zbrush_client.release"):
                    h.reset()
                    rec, value = run_node(soft, node, base, inputs=inputs, out="version", project="PROJ")
                self.assertEqual(rec["status"], "ok", rec.get("error"))
                self.assertEqual(value, 4)
                self.assertTrue(seen["thread"].startswith("flux-flows"), seen["thread"])

    def test_another_instance_than_the_publisher_is_refused(self) -> None:
        with mock.patch("dcc.mari.mari_export.publish_mari") as pub:
            rec, _ = run_node("mari", "dcc.mari_publish", 7071, inputs={"class": "A", "task": "B", "name": "c"},
                              project="PROJ")
        pub.assert_not_called()
        self.assertIn("port 7070", rec["nodes"]["n"]["error"])


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(os.name == "nt", "fake sbscooker is a shell script")
class SdCook(unittest.TestCase):
    def test_cook_with_sbscooker_and_guards(self) -> None:
        h.reset()
        tmp = Path(tempfile.mkdtemp(prefix="flux_sdcook_"))
        try:
            cooker = tmp / "sbscooker"
            cooker.write_text('#!/bin/sh\n# --inputs SRC --output-path DIR --output-name NAME\n'
                              'touch "$4/$6.sbsar"\n', encoding="utf-8")
            cooker.chmod(0o755)
            src = tmp / "rock.sbs"
            src.write_text("<sbs/>", encoding="utf-8")
            flow = h.flow({"ev": "event.manual", "cook": ("dcc.sd_cook", {"source": str(src),
                                                                          "dest": str(tmp / "out" / "rock.sbsar")}),
                           "rec": "action.t_record"},
                          ["ev.then->cook.exec", "cook.then->rec.exec", "cook.path->rec.value"])
            with mock.patch("flux_flows.nodes.dcc_softs.find_sbscooker", return_value=cooker):
                rec = h.run_flow(flow)
                self.assertEqual(rec["status"], "ok", rec.get("error"))
                self.assertTrue((tmp / "out" / "rock.sbsar").is_file())
                again = h.run_flow(flow)
            self.assertIn("existe deja", again["nodes"]["cook"]["error"])
            with mock.patch("flux_flows.nodes.dcc_softs.find_sbscooker", return_value=None):
                (tmp / "out" / "rock.sbsar").unlink()
                rec = h.run_flow(flow)
            self.assertIn("sbscooker introuvable", rec["nodes"]["cook"]["error"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
