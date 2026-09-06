# test_port_guard.py — zombie Maya detection: liveness persistence + identity guards.
#
# The detection must NEVER flag a healthy or still-initialising Maya, so these tests
# pin the decision logic (find_stuck_maya) against mocked netstat/connect/tasklist.

from __future__ import annotations

import unittest
from unittest import mock

from dcc.maya import port_guard


class Reachable(unittest.TestCase):
    """_reachable: one accepted connection proves the instance is alive."""

    def test_first_attempt_succeeds(self):
        with mock.patch.object(port_guard, "_connect_ok", return_value=True) as m:
            self.assertTrue(port_guard._reachable(7001))
        self.assertEqual(m.call_count, 1)  # short-circuits on first success

    def test_late_attempt_succeeds(self):
        # Fails twice (Maya's commandPort thread not ready), then accepts.
        seq = [False, False, True]
        with mock.patch.object(port_guard, "_connect_ok", side_effect=seq), \
             mock.patch.object(port_guard.time, "sleep"):
            self.assertTrue(port_guard._reachable(7001, attempts=3, gap=0))

    def test_all_attempts_fail(self):
        with mock.patch.object(port_guard, "_connect_ok", return_value=False), \
             mock.patch.object(port_guard.time, "sleep"):
            self.assertFalse(port_guard._reachable(7001, attempts=3, gap=0))


class FindStuckMaya(unittest.TestCase):
    def test_free_port_is_not_stuck(self):
        with mock.patch.object(port_guard, "_listener_pids", return_value=[]):
            self.assertIsNone(port_guard.find_stuck_maya(7001))

    def test_responsive_listener_is_not_stuck(self):
        # A live Maya accepts the connection → never flagged, netstat identity unused.
        with mock.patch.object(port_guard, "_listener_pids", return_value=[123]), \
             mock.patch.object(port_guard, "_reachable", return_value=True):
            self.assertIsNone(port_guard.find_stuck_maya(7001))

    def test_bound_but_unreachable_maya_is_stuck(self):
        with mock.patch.object(port_guard, "_listener_pids", return_value=[123]), \
             mock.patch.object(port_guard, "_reachable", return_value=False), \
             mock.patch.object(port_guard, "_proc_name", return_value="maya.exe"):
            stuck = port_guard.find_stuck_maya(7001)
        self.assertIsNotNone(stuck)
        self.assertEqual(stuck["pid"], 123)
        self.assertEqual(stuck["port"], 7001)

    def test_non_maya_holder_is_never_flagged(self):
        # An unreachable listener that isn't Maya must not be proposed for a kill.
        with mock.patch.object(port_guard, "_listener_pids", return_value=[999]), \
             mock.patch.object(port_guard, "_reachable", return_value=False), \
             mock.patch.object(port_guard, "_proc_name", return_value="python.exe"):
            self.assertIsNone(port_guard.find_stuck_maya(7001))


class ReapIdentityGuard(unittest.TestCase):
    def test_reap_aborts_when_pid_no_longer_maya(self):
        # Detected as stuck, but the PID has been recycled onto another process by
        # the time we reap → must refuse to kill.
        with mock.patch.object(
            port_guard, "find_stuck_maya",
            return_value={"pid": 123, "name": "maya.exe", "port": 7001},
        ), mock.patch.object(port_guard, "_proc_name", return_value="notepad.exe"):
            result = port_guard.reap_stuck_maya(7001)
        self.assertFalse(result["killed"])
        self.assertEqual(result["message"], "pid_no_longer_maya")

    def test_reap_noop_when_nothing_stuck(self):
        with mock.patch.object(port_guard, "find_stuck_maya", return_value=None):
            result = port_guard.reap_stuck_maya(7001)
        self.assertFalse(result["killed"])
        self.assertEqual(result["message"], "no_stuck_maya")


if __name__ == "__main__":
    unittest.main()
