"""Successful/offline Houdini startup stays quiet; real failures remain visible."""
import builtins
import sys
import types
import unittest
from unittest import mock

from dcc.houdini import autostart
from backend.tests.security.test_houdini_bridge_browser_guard import _load_server_module


class QuietStartup(unittest.TestCase):
    def run_block(self, offline=False):
        hou = mock.MagicMock()
        hou.isUIAvailable.return_value = True
        hou.homeHoudiniDirectory.return_value = "C:/fake/scripts"
        original_import = builtins.__import__

        def import_bridge(name, *args, **kwargs):
            if name == "flux_houdini_server":
                return types.ModuleType(name)
            return original_import(name, *args, **kwargs)

        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"root": "D:/Flux"}'
        with mock.patch.dict(sys.modules, {"hou": hou}), \
             mock.patch("builtins.__import__", side_effect=import_bridge), \
             mock.patch("builtins.print") as output, \
             mock.patch("pathlib.Path.exists", return_value=False), \
             mock.patch("urllib.request.urlopen", return_value=response,
                        side_effect=OSError("offline") if offline else None):
            sys.modules.pop("flux_houdini_server", None)
            # The startup adds scripts to sys.path; restore it after executing.
            with mock.patch.object(sys, "path", list(sys.path)):
                exec(compile(autostart._NEW_BLOCK, "123.py", "exec"), {})
            output.assert_not_called()
        return hou

    def test_online_startup_sets_flux_without_console_message(self):
        self.run_block().putenv.assert_called_once_with("FLUX", "D:/Flux")

    def test_offline_startup_keeps_package_value_without_console_message(self):
        self.run_block(offline=True).putenv.assert_not_called()

    def test_bridge_starts_and_repeated_start_is_quiet(self):
        server = _load_server_module()
        httpd = mock.MagicMock()
        with mock.patch.object(server, "_ThreadedHTTPServer", return_value=httpd), \
             mock.patch.object(server.threading, "Thread") as thread, \
             mock.patch.object(server, "_register_queue_processor") as register, \
             mock.patch.object(server, "_safe_status") as status, \
             mock.patch("builtins.print") as output:
            server.start(48884)
            server.start(48884)
            thread.return_value.start.assert_called_once()
            register.assert_called_once()
            status.assert_not_called()
            output.assert_not_called()
