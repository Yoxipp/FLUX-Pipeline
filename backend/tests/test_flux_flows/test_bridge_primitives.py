# P6a (2026-10-23): transport primitives and bridge.* nodes against fake bridges
# (success, refusal, timeout, closed port). Proves the protocols, never a DCC.

from __future__ import annotations

import threading
import unittest
from unittest import mock

from flux_flows.bridges import primitives as prim
from flux_flows.bridges import softs
from tests.test_flux_flows import _flow_helpers as h
from tests.test_flux_flows._fake_bridges import FakeCommandPort, FakeHttp, FakeTcpJson, free_port

setUpModule = h.setUpModule        # noqa: N816
tearDownModule = h.tearDownModule  # noqa: N816


class Softs(unittest.TestCase):
    def test_prefixes_unique_and_lookup(self) -> None:
        prefixes = [s.prefix for s in softs.SOFTS.values()]
        self.assertEqual(len(prefixes), len(set(prefixes)))
        self.assertFalse(set(prefixes) & set(softs.RESERVED_PREFIXES))
        self.assertEqual(softs.get("Houdini").soft, "houdini")
        self.assertEqual(softs.get("substance_painter").prefix, "sp")
        with self.assertRaises(ValueError):
            softs.get("blender")


class TcpJson(unittest.TestCase):
    def test_success_refusal_timeout_closed(self) -> None:
        def handler(req):
            if req.get("cmd") == "slow":
                return None
            if req.get("cmd") == "bad":
                return {"status": "error", "msg": "nope"}
            return {"ok": True, "echo": req}

        with FakeTcpJson(handler) as srv:
            self.assertEqual(prim.tcp_json_call(srv.port, {"cmd": "ping"})["echo"], {"cmd": "ping"})
            with self.assertRaisesRegex(prim.BridgeError, "nope"):
                prim.tcp_json_call(srv.port, {"cmd": "bad"})
            with self.assertRaises(prim.BridgeError):
                prim.tcp_json_call(srv.port, {"cmd": "slow"}, timeout=0.3)
        with self.assertRaises(prim.BridgeError):
            prim.tcp_json_call(free_port(), {"cmd": "ping"}, timeout=0.5)


class Http(unittest.TestCase):
    def test_get_post_and_errors(self) -> None:
        def run(code):
            if "boom" in code:
                raise RuntimeError("boom")
            return 42

        with FakeHttp(run) as srv:
            self.assertTrue(prim.http_call(srv.port, "/ping", method="GET")["ok"])
            self.assertEqual(prim.http_call(srv.port, "/run", {"code": "result = 42"})["result"], 42)
            with self.assertRaisesRegex(prim.BridgeError, "boom"):
                prim.http_call(srv.port, "/run", {"code": "boom"})
            with self.assertRaises(prim.BridgeError):
                prim.http_call(srv.port, "run", {})
            self.assertTrue(prim.ping("houdini", srv.port)["ok"])
        self.assertFalse(prim.ping("houdini", free_port())["ok"])


class CommandPort(unittest.TestCase):
    def test_answer_and_closed(self) -> None:
        with FakeCommandPort(lambda cmd: "2024.2" if "about" in cmd else "ok") as srv:
            self.assertEqual(prim.command_port_call(srv.port, "print(1)"), "ok")
            self.assertEqual(prim.ping("maya", srv.port), {"ok": True, "version": "2024.2", "port": srv.port})
        with self.assertRaisesRegex(prim.BridgeError, "pas de reponse"):
            prim.command_port_call(free_port(), "print(1)", timeout=0.5)


class WaitReady(unittest.TestCase):
    def test_backoff_until_ready_then_timeout_and_cancel(self) -> None:
        answers = iter([{"ok": False}, {"ok": False}, {"ok": True, "version": "20", "port": 1}])
        sleeps = []
        got = prim.wait_ready("houdini", 1, timeout=60, poll=1, ping_fn=lambda s, p: next(answers),
                              sleep=sleeps.append)
        self.assertEqual(got["version"], "20")
        self.assertEqual(sleeps, [1, 1.5])
        clock = iter(range(0, 1000, 10))
        with self.assertRaisesRegex(prim.BridgeError, "ne repond pas"):
            prim.wait_ready("houdini", 1, timeout=25, ping_fn=lambda s, p: {"ok": False}, sleep=lambda s: None,
                            clock=lambda: next(clock))
        cancel = threading.Event()
        cancel.set()
        with self.assertRaisesRegex(prim.BridgeError, "annule"):
            prim.wait_ready("houdini", 1, ping_fn=lambda s, p: {"ok": False}, cancelled=cancel)

    def test_any_port_of_the_range(self) -> None:
        seen = []

        def ping_fn(soft, port):
            seen.append(port)
            return {"ok": port == 48886, "port": port}

        self.assertEqual(prim.wait_ready("houdini", None, ping_fn=ping_fn)["port"], 48886)
        self.assertEqual(seen, [48884, 48885, 48886])


class Nodes(unittest.TestCase):
    def test_tcp_json_node_runs_and_dry_run_sends_nothing(self) -> None:
        with FakeTcpJson(lambda req: {"ok": True, "n": 1}) as srv:
            flow = h.flow({"ev": "event.manual",
                           "call": ("bridge.tcp_json_call", {"port": srv.port, "payload": {"cmd": "ping"}}),
                           "rec": "action.t_record"},
                          ["ev.then->call.exec", "call.then->rec.exec", "call.response->rec.value"])
            rec = h.run_flow(flow)
            self.assertEqual(rec["status"], "ok", rec.get("error"))
            self.assertEqual(h.CALLS[-1][1], {"ok": True, "n": 1})
            h.reset()
            dry = h.run_flow(flow, mode="dry")
            self.assertEqual(dry["status"], "ok")
            self.assertEqual(len(srv.requests), 1)
            self.assertIn("call", dry["nodes_simulated"])

    def test_closed_port_is_a_node_error(self) -> None:
        flow = h.flow({"ev": "event.manual",
                       "call": ("bridge.tcp_json_call", {"port": free_port(), "payload": {"cmd": "ping"},
                                                         "timeout_s": 0.5})},
                      ["ev.then->call.exec"])
        rec = h.run_flow(flow)
        self.assertEqual((rec["status"], rec["nodes"]["call"]["state"]), ("error", "error"))

    def test_scan_ports_and_launch_dry(self) -> None:
        with mock.patch("core.dcc_instances.scan_instances", return_value=[{"port": 48884, "pid": 3}]) as scan:
            flow = h.flow({"ev": "event.manual", "scan": ("bridge.scan_ports", {"soft": "houdini"}),
                           "rec": "action.t_record", "go": ("bridge.launch", {"soft": "houdini"})},
                          ["ev.then->rec.exec", "scan.count->rec.value", "rec.then->go.exec"])
            with mock.patch("features.launcher.launcher_core.launch_dcc") as launch:
                rec = h.run_flow(flow, mode="dry")
        scan.assert_called_once_with("Houdini")
        launch.assert_not_called()
        self.assertEqual(rec["status"], "ok")
        self.assertTrue(any("lancerait houdini" in r["text_fr"] for r in rec["report"]))


if __name__ == "__main__":
    unittest.main()
