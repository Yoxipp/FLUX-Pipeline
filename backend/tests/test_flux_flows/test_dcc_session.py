# P6a (2026-10-23): sessions and Instance nodes (02 §8, decision 24): live Houdini /
# Maya against fake bridges, pick active / scene / pid, open then wait_ready, connect
# only, dry run (no soft started, null session, DCC nodes skipped), headless refusal.

from __future__ import annotations

import unittest
from unittest import mock

from flux_flows.bridges import primitives, session as sess
from flux_flows.bridges.primitives import BridgeError
from tests.test_flux_flows import _flow_helpers as h
from tests.test_flux_flows._fake_bridges import FakeCommandPort, FakeHttp
from tests.test_flux_flows._fake_dcc import (FakeCmds, FakeHou, install_fake_maya, maya_command_port_handler,
                                             restore_modules)

setUpModule = h.setUpModule        # noqa: N816
tearDownModule = h.tearDownModule  # noqa: N816


class LiveSessions(unittest.TestCase):
    def test_houdini_run_contract(self) -> None:
        hou = FakeHou()
        with FakeHttp(hou.run) as srv:
            s = sess.HoudiniLiveSession(srv.port)
            self.assertEqual(s.run("result = hou.frame()"), {"ok": True, "result": 1001})
            self.assertEqual(s.call("result = hou.hipFile.path()"), "untitled.hip")
            with self.assertRaisesRegex(BridgeError, "boom"):
                s.call("raise RuntimeError('boom')")

    def test_maya_run_contract_through_the_command_port(self) -> None:
        cmds = FakeCmds()
        cmds.scene = "C:/p/shot010_anim_v003.ma"
        saved = install_fake_maya(cmds)
        try:
            with FakeCommandPort(maya_command_port_handler) as srv:
                s = sess.MayaLiveSession(srv.port)
                self.assertEqual(s.run("result = cmds.file(q=True, sceneName=True)"),
                                 {"ok": True, "result": "C:/p/shot010_anim_v003.ma"})
                bad = s.run("raise ValueError('no')")
                self.assertFalse(bad["ok"])
                self.assertIn("ValueError: no", bad["error"])
                self.assertEqual(s.run("result = {1, 2}")["ok"], True)   # not JSON: repr
                line = srv.commands[0]
                self.assertTrue(line.isascii())
                self.assertNotIn("\n", line)
        finally:
            restore_modules(saved)

    def test_closed_ports(self) -> None:
        from tests.test_flux_flows._fake_bridges import free_port

        self.assertFalse(sess.MayaLiveSession(free_port()).run("result = 1")["ok"])
        self.assertFalse(sess.HoudiniLiveSession(free_port()).run("result = 1")["ok"])


INSTANCES = [{"port": 48884, "pid": 11}, {"port": 48885, "pid": 22}]


class FindInstance(unittest.TestCase):
    def test_pick_active_scene_pid(self) -> None:
        scenes = {48884: "/p/a.hip", 48885: "/p/b.hip"}
        with mock.patch("core.dcc_instances.check_active", return_value=48885):
            self.assertEqual(sess.find_instance("houdini", instances=INSTANCES)["port"], 48885)
        got = sess.find_instance("houdini", pick="scene", scene="/p/a.hip", instances=INSTANCES,
                                 scene_fn=lambda soft, port: scenes[port])
        self.assertEqual(got["pid"], 11)
        self.assertEqual(sess.find_instance("houdini", pick="pid", pid=22, instances=INSTANCES)["port"], 48885)
        self.assertIsNone(sess.find_instance("houdini", pick="pid", pid=99, instances=INSTANCES))
        self.assertIsNone(sess.find_instance("houdini", instances=[]))
        with self.assertRaises(BridgeError):
            sess.find_instance("houdini", pick="scene", instances=INSTANCES)

    def test_connect_only_and_open_then_wait(self) -> None:
        with mock.patch.object(primitives, "scan_ports", return_value=[]), \
             mock.patch.object(primitives, "launch", return_value=True) as launch, \
             mock.patch.object(primitives, "wait_ready", return_value={"ok": True, "port": 48886}) as wait, \
             mock.patch.object(primitives, "ping", return_value={"ok": True, "version": "20.5"}), \
             mock.patch.object(sess, "scene_of", return_value="/p/c.hip"):
            with self.assertRaisesRegex(BridgeError, "aucune instance"):
                sess.connect_live("houdini", mode="live_connect_only")
            launch.assert_not_called()
            s = sess.connect_live("houdini", scene="/p/c.hip", wait_s=180)
        launch.assert_called_once_with("houdini", "/p/c.hip")
        self.assertEqual(wait.call_args.kwargs["timeout"], 180)
        self.assertEqual((s.port, s.version, s.scene, s.live), (48886, "20.5", "/p/c.hip", True))


def _instance_flow(mode: str = "live_connect_or_open", **extra):
    return h.flow({"ev": "event.manual", "inst": ("session.hou_instance", {"mode": mode, **extra}),
                   "find": ("dcc.hou_find_nodes", {"pattern": "OUT"}), "rec": "action.t_record",
                   "save": ("dcc.hou_save_scene", {})},
                  ["ev.then->inst.exec", "inst.then->find.exec", "inst.session->find.session",
                   "find.then->save.exec", "inst.session->save.session", "save.then->rec.exec",
                   "find.nodes->rec.value"])


class InstanceNode(unittest.TestCase):
    def setUp(self) -> None:
        h.reset()

    def test_live_run_and_dry_run_reads_but_never_writes(self) -> None:
        hou = FakeHou()
        hou.add("/obj/geo1", "geo", "Object")
        hou.add("/obj/geo1/OUT", "null")
        with FakeHttp(hou.run) as srv, \
                mock.patch.object(primitives, "scan_ports", return_value=[{"port": srv.port, "pid": 1}]), \
                mock.patch("core.dcc_instances.resolve_port", return_value=srv.port):
            rec = h.run_flow(_instance_flow())
            self.assertEqual(rec["status"], "ok", rec.get("error"))
            self.assertEqual(h.CALLS[-1][1], ["/obj/geo1/OUT"])
            self.assertEqual(hou.saved, ["untitled.hip"])
            h.reset()
            dry = h.run_flow(_instance_flow(), mode="dry")
        self.assertEqual(dry["status"], "ok", dry.get("error"))
        self.assertEqual(hou.saved, ["untitled.hip"])            # the dry run saved nothing
        self.assertTrue(any("se connecterait" in r["text_fr"] for r in dry["report"]))
        self.assertEqual(h.CALLS, [])                             # t_record simulated

    def test_dry_run_without_instance_starts_nothing(self) -> None:
        with mock.patch.object(primitives, "scan_ports", return_value=[]), \
             mock.patch.object(primitives, "launch") as launch:
            dry = h.run_flow(_instance_flow(), mode="dry")
            dry_headless = h.run_flow(_instance_flow("headless"), mode="dry")
        launch.assert_not_called()
        self.assertEqual((dry["status"], dry_headless["status"]), ("ok", "ok"))
        texts = [r["text_fr"] for r in dry["report"]]
        self.assertTrue(any("ouvrirait Houdini" in t for t in texts))
        self.assertTrue(any("saute (essai a blanc)" in t for t in texts))
        self.assertTrue(any("lancerait hython" in r["text_fr"] for r in dry_headless["report"]))

    def test_connect_only_fails_without_instance(self) -> None:
        with mock.patch.object(primitives, "scan_ports", return_value=[]):
            rec = h.run_flow(_instance_flow("live_connect_only"))
        self.assertEqual((rec["status"], rec["nodes"]["inst"]["state"]), ("error", "error"))
        self.assertIn("aucune instance", rec["nodes"]["inst"]["error"])

    def test_validation_flags(self) -> None:
        from flux_flows import validate

        flow = h.flow({"ev": "event.manual", "inst": ("session.hou_instance", {"mode": "headless"}),
                       "sel": "dcc.hou_selected", "orphan": "dcc.hou_get_parm"},
                      ["ev.then->inst.exec", "inst.session->sel.session"])
        codes = {(i.code, i.node) for i in validate.validate(flow, validate.Env())}
        self.assertIn(("W_LICENCE", "inst"), codes)
        self.assertIn(("E_LIVE_ONLY", "sel"), codes)
        self.assertIn(("E_NO_SESSION", "orphan"), codes)

    def test_farm_is_refused(self) -> None:
        rec = h.run_flow(_instance_flow("farm"), checked=False)
        self.assertIn("farm", rec["nodes"]["inst"]["error"])


if __name__ == "__main__":
    unittest.main()
