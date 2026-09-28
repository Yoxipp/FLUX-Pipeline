# B5 (2026-09-28): ghost instances dropped, sessions without bridge counted,
# Houdini autostart in 123.py AND 456.py (a .hip opened outside FLUX skips 123.py).

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from core import dcc_identity as di
from dcc.houdini import autostart


def inst(port: int, pid: int | None) -> dict:
    return {"port": port, "pid": pid}


class GhostInstances(unittest.TestCase):
    procs = {100: "maya.exe", 200: "houdinifx.exe", 300: "conhost.exe", 400: "houdini.exe"}

    def test_dead_or_foreign_pid_is_dropped(self) -> None:
        got = di.live_instances("Maya", [inst(7001, 100), inst(7002, 999), inst(7003, 300)], self.procs)
        self.assertEqual([i["port"] for i in got], [7001])

    def test_unknown_pid_or_no_process_list_keeps_everything(self) -> None:
        self.assertEqual(len(di.live_instances("Maya", [inst(7001, None)], self.procs)), 1)
        self.assertEqual(len(di.live_instances("Maya", [inst(7002, 999)], {})), 1)

    def test_houdini_without_bridge_next_to_one_with_it(self) -> None:
        self.assertEqual(di.unbridged_pids("Houdini", [inst(48884, 200)], self.procs), [400])
        self.assertEqual(di.unbridged_pids("Houdini", [], self.procs), [200, 400])


class AutostartBothScripts(unittest.TestCase):
    def setUp(self) -> None:
        self.prefs = Path(tempfile.mkdtemp(prefix="flux_hprefs_"))
        (self.prefs / "scripts").mkdir()
        (self.prefs / "scripts" / "123.py").write_text("print('mine')\n", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.prefs, ignore_errors=True)

    def test_block_compiles_and_runs_once(self) -> None:
        compile(autostart._NEW_BLOCK, "123.py", "exec")
        self.assertIn("'flux_houdini_server' not in _flux_sys.modules", autostart._NEW_BLOCK)

    def test_written_to_123_and_456_idempotent(self) -> None:
        for _ in range(2):
            for name in autostart._STARTUP_FILES:
                autostart._write_block(self.prefs / "scripts" / name)
        for name in ("123.py", "456.py"):
            text = (self.prefs / "scripts" / name).read_text(encoding="utf-8")
            self.assertEqual(text.count(autostart._BLOCK_BEGIN), 1)
        self.assertIn("print('mine')", (self.prefs / "scripts" / "123.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
