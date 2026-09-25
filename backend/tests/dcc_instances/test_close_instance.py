# Closing a DCC instance from the sidebar (2026-09-19): normal close first (the DCC
# may ask to save), force only on request, never a process that is not the DCC.

from __future__ import annotations

import unittest
from unittest import mock

from core import dcc_process
from dcc.maya import port_guard


class CloseInstance(unittest.TestCase):
    def setUp(self) -> None:
        self.listening = {7002: [4242]}
        self.names = {4242: "maya.exe"}
        self.calls: list[list[str]] = []
        self.dies = True

        def _run_rc(args):
            self.calls.append(args)
            if self.dies:
                self.listening = {}
            return 0, ""

        for name, fn in (("_listener_pids", lambda port: list(self.listening.get(port, []))),
                         ("_proc_name", lambda pid: self.names.get(pid, "")),
                         ("_run_rc", _run_rc)):
            p = mock.patch.object(port_guard, name, side_effect=fn)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(dcc_process.time, "sleep")
        p.start()
        self.addCleanup(p.stop)

    def test_a_normal_close_is_like_the_window_button(self) -> None:
        res = dcc_process.close_instance("Maya", 7002)
        self.assertTrue(res["closed"])
        self.assertNotIn("/F", self.calls[0])
        self.assertIn("4242", self.calls[0])

    def test_a_session_that_stays_offers_to_force(self) -> None:
        self.dies = False
        with mock.patch.object(dcc_process.time, "monotonic", side_effect=[0.0, 10.0]):
            res = dcc_process.close_instance("Maya", 7002)
        self.assertEqual((res["closed"], res["needs_force"]), (False, True))
        self.dies = True
        res = dcc_process.close_instance("Maya", 7002, force=True)
        self.assertTrue(res["closed"])
        self.assertIn("/F", self.calls[-1])

    def test_never_kills_another_program(self) -> None:
        self.names[4242] = "chrome.exe"
        res = dcc_process.close_instance("Maya", 7002, force=True)
        self.assertFalse(res["closed"])
        self.assertEqual(self.calls, [])

    def test_free_port_and_bad_requests(self) -> None:
        self.assertTrue(dcc_process.close_instance("Maya", 7005)["closed"])
        self.assertEqual(self.calls, [])
        with self.assertRaises(ValueError):
            dcc_process.close_instance("Maya", 48884)
        with self.assertRaises(ValueError):
            dcc_process.close_instance("Blender", 7001)


if __name__ == "__main__":
    unittest.main()
