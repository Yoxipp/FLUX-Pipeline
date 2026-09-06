# test_dcc_instances.py — multi-instance discovery (cluster C, phase 1).
#
# Discovery must report exactly the reachable ports of a DCC's range as distinct
# instances, ordered, with a stable id, and never invent an instance for a closed
# port. The probe is injected so these are deterministic (no real DCC needed); one
# real-socket test pins the default transport (socket_manager.probe_port).

from __future__ import annotations

import socket
import unittest

from core import dcc_instances
from core.constants import DCC_PORT_RANGES, dcc_for_port, dcc_port_range
from core.socket_manager import socket_manager


class PortRangeModel(unittest.TestCase):
    """The range model: back-compat base ports + no overlap between DCCs."""

    def test_legacy_base_ports_preserved(self):
        # Live DCCs must keep their historical single-instance port as range base,
        # so a lone, not-yet-updated instance still lands where FLUX expects it.
        self.assertEqual(DCC_PORT_RANGES["Maya"][0], 7001)
        self.assertEqual(DCC_PORT_RANGES["Houdini"][0], 48884)
        self.assertEqual(DCC_PORT_RANGES["ZBrush"][0], 9876)

    def test_ranges_never_overlap(self):
        seen: dict[int, str] = {}
        for dcc in DCC_PORT_RANGES:
            for port in dcc_port_range(dcc):
                self.assertNotIn(port, seen, f"{dcc} port {port} collides with {seen.get(port)}")
                seen[port] = dcc

    def test_dcc_for_port_roundtrips(self):
        for dcc in DCC_PORT_RANGES:
            for port in dcc_port_range(dcc):
                self.assertEqual(dcc_for_port(port), dcc)

    def test_dcc_for_port_out_of_range(self):
        self.assertIsNone(dcc_for_port(1))
        self.assertIsNone(dcc_for_port(65000))


class InstanceRecord(unittest.TestCase):
    def test_instance_id_uses_port(self):
        self.assertEqual(dcc_instances.instance_id("Maya", 7002), "Maya:7002")

    def test_make_instance_shape(self):
        rec = dcc_instances.make_instance("Maya", 7001)
        self.assertEqual(rec["id"], "Maya:7001")
        self.assertEqual(rec["dcc"], "Maya")
        self.assertEqual(rec["port"], 7001)
        self.assertTrue(rec["connected"])
        # Rich identity fields are stable-but-empty until the DCC-side bridge fills them.
        for k in ("pid", "scene", "version"):
            self.assertIsNone(rec[k])


class ScanInstances(unittest.TestCase):
    """scan_instances with an injected probe — deterministic, no real DCC."""

    def _probe_only(self, *open_ports):
        wanted = set(open_ports)
        return lambda port, timeout=0.3: port in wanted

    def test_no_instances_when_range_closed(self):
        got = dcc_instances.scan_instances("Maya", probe=lambda p, t=0.3: False)
        self.assertEqual(got, [])

    def test_reports_only_open_ports(self):
        got = dcc_instances.scan_instances("Maya", probe=self._probe_only(7001, 7003))
        self.assertEqual([r["port"] for r in got], [7001, 7003])
        self.assertEqual([r["id"] for r in got], ["Maya:7001", "Maya:7003"])

    def test_ordered_by_port_ascending(self):
        # Lowest open port must come first (stable default "active" instance).
        got = dcc_instances.scan_instances("Maya", probe=self._probe_only(7005, 7001, 7002))
        self.assertEqual([r["port"] for r in got], [7001, 7002, 7005])

    def test_only_scans_own_range(self):
        # A port outside Maya's range is never reported for Maya even if "open".
        got = dcc_instances.scan_instances("Maya", probe=self._probe_only(48884))
        self.assertEqual(got, [])

    def test_unknown_dcc_returns_empty(self):
        self.assertEqual(dcc_instances.scan_instances("Blender", probe=lambda p, t=0.3: True), [])

    def test_scan_all_covers_every_dcc(self):
        allinst = dcc_instances.scan_all_instances(probe=lambda p, t=0.3: False)
        self.assertEqual(set(allinst), set(DCC_PORT_RANGES))
        self.assertTrue(all(v == [] for v in allinst.values()))


class RealProbeTransport(unittest.TestCase):
    """Pin the default probe (socket_manager.probe_port) the scan relies on."""

    def test_bound_listener_is_reachable_and_closed_is_not(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))   # OS picks a free port
        srv.listen(1)
        port = srv.getsockname()[1]
        try:
            self.assertTrue(socket_manager.probe_port(port, timeout=0.5))
        finally:
            srv.close()
        # Same port after close — nothing listening now.
        self.assertFalse(socket_manager.probe_port(port, timeout=0.3))


if __name__ == "__main__":
    unittest.main()
