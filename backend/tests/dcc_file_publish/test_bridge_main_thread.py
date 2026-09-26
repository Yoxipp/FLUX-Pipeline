# test_bridge_main_thread.py - Painter / Designer / Mari bridges: one API call at a time,
# a port of their own, no API call in the ping (2026-09-26).

from __future__ import annotations

import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from dcc.mari import mari_bridge
from dcc.substance_designer import substance_designer_bridge as designer_bridge
from dcc.substance_painter import substance_painter_bridge as painter_bridge

BRIDGES = (painter_bridge, designer_bridge, mari_bridge)


class OneCallAtATime(unittest.TestCase):
    def test_no_call_starts_inside_another_and_abandoned_jobs_are_skipped(self):
        for b in BRIDGES:
            with self.subTest(bridge=b.__name__), mock.patch.object(b, "_diag", lambda msg: None):
                order = []

                def export(b=b, order=order):
                    order.append("export start")
                    b._drain()          # the Qt timer firing while the app exports
                    order.append("export end")
                    return {}

                def info(order=order):
                    order.append("info")
                    return {}

                for fn, box in ((export, {}), (info, {}), (info, {"abandoned": True})):
                    b._jobs.put((fn, box, threading.Event()))
                b._drain()
                self.assertEqual(order, ["export start", "export end", "info"])


class OwnPort(unittest.TestCase):
    def test_a_second_bridge_cannot_share_the_port(self):
        for b in BRIDGES:
            with self.subTest(bridge=b.__name__):
                first = b._listen("127.0.0.1", 0)
                try:
                    port = first.getsockname()[1]
                    with self.assertRaises(OSError):
                        b._listen("127.0.0.1", port).close()
                finally:
                    first.close()


class DesignerPing(unittest.TestCase):
    def test_ping_never_calls_the_sd_api(self):
        with mock.patch.object(designer_bridge, "_app", side_effect=AssertionError("sd API in the ping")), \
                mock.patch.object(designer_bridge, "_VERSION", "Substance Designer 14.0"):
            res = designer_bridge._dispatch({"action": "ping"})
        self.assertEqual(res, {"status": "ok", "version": "Substance Designer 14.0"})


class PainterDiagnose(unittest.TestCase):
    def test_says_where_the_bridge_is_and_quotes_its_log(self):
        from dcc.substance_painter import autostart
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "flux_painter_bridge.log"
            with mock.patch.dict(os.environ, {"FLUX_SP_PLUGINS_DIR": tmp}), \
                    mock.patch.object(autostart, "_BRIDGE_LOG", log):
                self.assertIn("non installe", autostart.diagnose())
                (Path(tmp) / "flux_substance_bridge.py").write_text("#", encoding="utf-8")
                self.assertIn("jamais lance", autostart.diagnose())
                log.write_text("2026-09-26 10:00:00 bind failed\n", encoding="utf-8")
                self.assertIn("bind failed", autostart.diagnose())


if __name__ == "__main__":
    unittest.main()
