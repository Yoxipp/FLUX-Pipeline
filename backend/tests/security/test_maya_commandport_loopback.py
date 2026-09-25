# test_maya_commandport_loopback.py — S3: FLUX opens the Maya commandPort on 127.0.0.1 only.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dcc.maya import autostart


def _block(text: str) -> str:
    start = text.find(autostart._BLOCK_BEGIN)
    end = text.find(autostart._BLOCK_END, start)
    return text[start:end + len(autostart._BLOCK_END)]


class MayaCommandPortLoopbackTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.startup = Path(self._tmp.name) / "2025" / "scripts" / "userSetup.py"
        patches = [
            mock.patch.object(autostart, "_get_maya_app_dir", return_value=Path(self._tmp.name)),
            mock.patch.object(autostart, "_discover_startup_files", return_value=[self.startup]),
            mock.patch.object(autostart, "get_startup_file", return_value=self.startup),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def test_new_block_binds_loopback_and_is_valid_python(self):
        autostart.install()
        block = _block(self.startup.read_text(encoding="utf-8"))
        self.assertIn("'127.0.0.1:%d' % _n for _n in range(7001, 7009)", block)
        self.assertNotIn("':%d'", block)
        compile(block, "userSetup.py", "exec")

    def test_stale_block_with_bare_port_is_upgraded(self):
        autostart.install()
        text = self.startup.read_text(encoding="utf-8")
        self.startup.write_text(text.replace("'127.0.0.1:%d'", "':%d'"), encoding="utf-8")
        self.assertTrue(autostart.is_installed())
        result = autostart.install()
        self.assertNotEqual(result["message"], "already_installed")
        self.assertIn("'127.0.0.1:%d'", self.startup.read_text(encoding="utf-8"))

    def test_new_block_takes_the_first_free_port_and_frees_it_on_quit(self):
        # Live 2026-09-18: a Maya with no window held 7001, the artist's Maya gave up.
        autostart.install()
        block = _block(self.startup.read_text(encoding="utf-8"))
        self.assertIn("for _p in _flux_ports:", block)
        self.assertIn("quitApplication", block)
        self.assertIn("close=True", block)

    def test_shelf_and_router_commands_use_loopback(self):
        backend = Path(autostart.__file__).resolve().parents[2]
        for rel in ("dcc/maya/maya_shelf.py", "dcc/maya/maya_connection.py",
                    "routers/dcc.py", "resources/shelves/maya/shelf_Flux.mel"):
            text = (backend / rel).read_text(encoding="utf-8-sig")
            self.assertNotIn("name=':", text, rel)
            self.assertNotIn('f":{port}"', text, rel)


if __name__ == "__main__":
    unittest.main()
