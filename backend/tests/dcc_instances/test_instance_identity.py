# A1 (2026-09-27): an instance is (port, pid). A port taken back by another process
# (the chosen Houdini closed, another one opened) is never targeted silently.

from __future__ import annotations

import unittest
from unittest import mock

from core import dcc_identity, dcc_instances as di

NETSTAT = """
  Proto  Local Address          Foreign Address        State           PID
  TCP    127.0.0.1:7001         0.0.0.0:0              LISTENING       1200
  TCP    127.0.0.1:7002         0.0.0.0:0              LISTENING       1300
  TCP    127.0.0.1:7001         127.0.0.1:55000        ESTABLISHED     1200
  TCP    0.0.0.0:48884          0.0.0.0:0              LISTENING       4400
"""

TASKLIST = '''"maya.exe","1200","Console","1","900 000 Ko"
"mayapy.exe","1250","Console","1","90 000 Ko"
"houdinifx.exe","4400","Console","1","2 000 000 Ko"
"hython.exe","4500","Console","1","300 000 Ko"
"Nuke16.0.exe","5100","Console","1","800 000 Ko"
'''


class Parsing(unittest.TestCase):
    def test_netstat_listeners(self) -> None:
        self.assertEqual(dcc_identity.parse_netstat(NETSTAT), {7001: 1200, 7002: 1300, 48884: 4400})

    def test_sessions_skip_flux_helpers(self) -> None:
        procs = dcc_identity.parse_tasklist(TASKLIST)
        self.assertEqual(dcc_identity.running_pids("Maya", procs), [1200])          # not mayapy
        self.assertEqual(dcc_identity.running_pids("Houdini", procs), [4400])       # not hython
        self.assertEqual(dcc_identity.running_pids("Nuke", procs), [5100])
        self.assertEqual(dcc_identity.running_pids("Photoshop", procs), [])         # COM, no bridge port

    def test_scene_label(self) -> None:
        self.assertEqual(dcc_identity.scene_label("C:\\p\\shot\\SEQ001_render.hip"), "SEQ001_render.hip")
        self.assertEqual(dcc_identity.scene_label(""), "sans titre")


class ActiveInstance(unittest.TestCase):
    def setUp(self) -> None:
        di._ACTIVE.clear()
        di._LOST.clear()

    def test_the_same_process_stays_active(self) -> None:
        di.set_active_port("Houdini", 48885, pid=10)
        self.assertEqual(di.check_active("Houdini", pid_of=lambda p: 10), 48885)
        self.assertIsNone(di.lost_active("Houdini"))

    def test_a_port_taken_back_by_another_process_is_lost(self) -> None:
        di.set_active_port("Houdini", 48885, pid=10)
        self.assertIsNone(di.check_active("Houdini", pid_of=lambda p: 99))
        self.assertEqual(di.lost_active("Houdini")["pid"], 10)
        self.assertEqual(di.lost_active("Houdini")["now_pid"], 99)

    def test_lost_with_several_running_refuses_to_guess(self) -> None:
        di.set_active_port("Houdini", 48885, pid=10)
        live = [di.make_instance("Houdini", 48884, pid=20), di.make_instance("Houdini", 48885, pid=99)]
        with self.assertRaises(di.InstanceLostError):
            di.resolve_port("Houdini", instances=live, pid_of=lambda p: 99)

    def test_lost_with_one_running_takes_it(self) -> None:
        di.set_active_port("Houdini", 48885, pid=10)
        live = [di.make_instance("Houdini", 48884, pid=20)]
        self.assertEqual(di.resolve_port("Houdini", instances=live, pid_of=lambda p: None), 48884)

    def test_no_choice_uses_the_lowest_then_the_base_port(self) -> None:
        live = [di.make_instance("Houdini", 48886, pid=3)]
        self.assertEqual(di.resolve_port("Houdini", instances=live), 48886)
        self.assertEqual(di.resolve_port("Houdini", instances=[]), 48884)

    def test_choosing_again_clears_the_loss(self) -> None:
        di.set_active_port("Houdini", 48885, pid=10)
        di.check_active("Houdini", pid_of=lambda p: 99)
        di.set_active_port("Houdini", 48885, pid=99)
        self.assertIsNone(di.lost_active("Houdini"))

    def test_houdini_client_reports_the_loss_instead_of_sending(self) -> None:
        from dcc.houdini.client import HoudiniClient

        with mock.patch("core.dcc_instances.resolve_port", side_effect=di.InstanceLostError("fermee")):
            res = HoudiniClient().run("result = 1")
        self.assertFalse(res["ok"])
        self.assertIn("fermee", res["error"])


class BusyDetails(unittest.TestCase):
    def setUp(self) -> None:
        dcc_identity.clear_cache()

    def test_a_maya_that_does_not_answer_is_busy(self) -> None:
        with mock.patch("dcc.maya.maya_connection.send_command_direct", return_value=None):
            self.assertEqual(dcc_identity.details("Maya", 7001, 1200)["state"], "busy")

    def test_a_maya_answer_gives_scene_and_version(self) -> None:
        with mock.patch("dcc.maya.maya_connection.send_command_direct",
                        return_value="C:/p/shot.mb\n2025\n\x00"):
            info = dcc_identity.details("Maya", 7002, 1300)
        self.assertEqual((info["scene"], info["version"], info["state"]), ("C:/p/shot.mb", "2025", "connected"))


if __name__ == "__main__":
    unittest.main()
