# test_dcc_router.py — multi-instance DCC router logic (cluster C, phase 3).
#
# Covers the port-resolution guard and the instance-aware status shape without
# standing up a real server: scan_instances is patched so the probes are
# deterministic and no DCC is required.

from __future__ import annotations

import unittest
from unittest import mock

from fastapi import HTTPException

from core.constants import DCC_PORTS
from routers import dcc as dcc_router


class ResolveTargetPort(unittest.TestCase):
    def test_none_falls_back_to_base_port(self):
        self.assertEqual(dcc_router._resolve_target_port("Maya", None), DCC_PORTS["Maya"])

    def test_in_range_port_is_accepted(self):
        self.assertEqual(dcc_router._resolve_target_port("Maya", 7005), 7005)

    def test_out_of_range_port_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            dcc_router._resolve_target_port("Maya", 7009)   # Maya range is 7001..7008
        self.assertEqual(ctx.exception.status_code, 400)

    def test_unknown_dcc_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            dcc_router._resolve_target_port("Blender", None)
        self.assertEqual(ctx.exception.status_code, 400)


class ProbeAllDccs(unittest.IsolatedAsyncioTestCase):
    async def test_status_carries_instances_and_backcompat_fields(self):
        from core.dcc_instances import make_instance

        def fake_scan(dcc, **_kw):
            if dcc == "Maya":
                return [make_instance("Maya", 7001), make_instance("Maya", 7003)]
            return []

        with mock.patch.object(dcc_router, "scan_instances", side_effect=fake_scan):
            status = await dcc_router._probe_all_dccs()

        maya = status["Maya"]
        self.assertTrue(maya["connected"])
        self.assertEqual(maya["port"], 7001)                 # lowest open instance
        self.assertEqual([i["port"] for i in maya["instances"]], [7001, 7003])

        houdini = status["Houdini"]
        self.assertFalse(houdini["connected"])
        self.assertEqual(houdini["port"], DCC_PORTS["Houdini"])   # base port when none up
        self.assertEqual(houdini["instances"], [])

    async def test_stuck_maya_probed_only_when_no_instance(self):
        with mock.patch.object(dcc_router, "scan_instances", side_effect=lambda d, **k: []), \
             mock.patch.object(dcc_router, "_maya_stuck_throttled", return_value=(True, 4242)) as m:
            status = await dcc_router._probe_all_dccs()
        self.assertTrue(status["Maya"]["stuck"])
        self.assertEqual(status["Maya"]["stuck_pid"], 4242)
        m.assert_called_once()

    async def test_marvelous_connected_by_its_heartbeat(self):
        # Marvelous never opens its port (mailbox bridge): its heartbeat decides.
        from dcc.marvelous import client as md_client

        beat = {"ok": True, "version": "Marvelous Designer 2024", "mode": "live", "pid": 99}
        with mock.patch.object(dcc_router, "scan_instances", side_effect=lambda d, **k: []), \
             mock.patch.object(dcc_router, "_maya_stuck_throttled", return_value=(False, None)), \
             mock.patch.object(md_client.marvelous_client, "ping", return_value=beat):
            status = await dcc_router._probe_all_dccs()
        md = status["Marvelous"]
        self.assertTrue(md["connected"])
        self.assertFalse(md["no_bridge"])
        self.assertEqual(md["instances"][0]["pid"], 99)

        with mock.patch.object(dcc_router, "scan_instances", side_effect=lambda d, **k: []), \
             mock.patch.object(dcc_router, "_maya_stuck_throttled", return_value=(False, None)), \
             mock.patch.object(md_client.marvelous_client, "ping", return_value={"ok": False}):
            status = await dcc_router._probe_all_dccs()
        self.assertFalse(status["Marvelous"]["connected"])


if __name__ == "__main__":
    unittest.main()
