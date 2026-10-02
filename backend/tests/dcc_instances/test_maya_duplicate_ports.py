"""One Maya process is one instance, even with legacy extra commandPorts."""
import unittest
from unittest.mock import patch

from core import dcc_instances as di


class MayaDiscovery(unittest.TestCase):
    def setUp(self):
        self.saved = dict(di._ACTIVE)
        di._ACTIVE.clear()
        self.addCleanup(di._ACTIVE.update, self.saved)
        self.addCleanup(di._ACTIVE.clear)

    def scan(self, listeners, procs):
        with patch("core.dcc_identity.listener_pids", return_value=listeners), \
             patch("core.dcc_identity.process_names", return_value=procs), \
             patch.object(di.socket_manager, "probe_port", return_value=True):
            return di.scan_instances("Maya")

    def test_duplicate_ports_and_foreign_backend_are_not_extra_sessions(self):
        items = self.scan({7001: 101, 7002: 101, 7003: 202},
                          {101: "maya.exe", 202: "flux_backend.exe"})
        self.assertEqual([(i["port"], i["pid"]) for i in items], [(7001, 101)])

    def test_selected_alias_is_preserved_and_real_second_session_remains(self):
        di.set_active_port("Maya", 7002, pid=101)
        items = self.scan({7001: 101, 7002: 101, 7003: 303},
                          {101: "maya.exe", 303: "maya.exe"})
        self.assertEqual([i["port"] for i in items], [7002, 7003])

    def test_unknown_pids_remain_distinct(self):
        items = di.scan_instances("Maya", probe=lambda p, t: p in (7001, 7002))
        self.assertEqual([i["port"] for i in items], [7001, 7002])

    def test_selected_alias_survives_when_its_pid_was_initially_unknown(self):
        di._ACTIVE["Maya"] = (7002, None)
        items = self.scan({7001: 101, 7002: 101}, {101: "maya.exe"})
        self.assertEqual([i["port"] for i in items], [7002])

    def test_failed_process_lookup_keeps_sessions_but_merges_known_pid(self):
        items = self.scan({7001: 101, 7002: 101, 7003: 303}, {})
        self.assertEqual([i["port"] for i in items], [7001, 7003])
