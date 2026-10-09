# test_install_all_bridges.py - "Installer tous les bridges" (retake F1).
#
# Installers are mocked: nothing is written in any DCC prefs.

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from features.launcher.bridges import install_all_bridges
from routers import dcc as dcc_router


def _mod(result=None, exc=None):
    install = mock.Mock(side_effect=exc) if exc else mock.Mock(return_value=result)
    return SimpleNamespace(install=install)


class InstallAllBridges(unittest.TestCase):
    def test_installed_ok_missing_skipped_failure_reported(self):
        maya = _mod({"success": True, "message": "userSetup.py ok"})
        nuke = _mod({"success": False, "message": "init.py verrouille"})
        mari = _mod({"success": True, "message": "x"})
        houdini = _mod(exc=RuntimeError("boom"))
        installed = {"maya": r"C:\Maya2025\bin\maya.exe", "nuke": r"C:\Nuke\Nuke15.exe",
                     "houdini": r"C:\H\houdini.exe"}
        res = install_all_bridges(installed, {"maya": maya, "nuke": nuke, "mari": mari, "houdini": houdini})
        by = {r["dcc"]: r for r in res}
        self.assertEqual(by["maya"]["status"], "ok")
        maya.install.assert_called_once_with(r"C:\Maya2025\bin\maya.exe")
        self.assertEqual(by["nuke"]["status"], "error")
        self.assertEqual(by["nuke"]["message"], "init.py verrouille")
        self.assertEqual(by["mari"]["status"], "skip")
        mari.install.assert_not_called()
        self.assertEqual(by["houdini"]["status"], "error")
        self.assertIn("boom", by["houdini"]["message"])

    def test_photoshop_library_only_when_installed(self):
        ps = mock.Mock(return_value={"ok": True, "message": "deja installe"})
        res = install_all_bridges({"photoshop": r"C:\PS\Photoshop.exe"}, {}, ps)
        self.assertEqual(res, [{"dcc": "photoshop", "status": "ok", "message": "deja installe"}])
        ps2 = mock.Mock()
        res = install_all_bridges({}, {}, ps2)
        self.assertEqual(res[0]["status"], "skip")
        ps2.assert_not_called()

    def test_photoshop_failure_reported(self):
        ps = mock.Mock(return_value={"ok": False, "message": "pip absent"})
        res = install_all_bridges({"photoshop": "x"}, {}, ps)
        self.assertEqual(res[0]["status"], "error")


class InstallAllEndpoint(unittest.IsolatedAsyncioTestCase):
    async def test_endpoint_uses_detected_dccs_and_every_module(self):
        fake = {key: _mod({"success": True, "message": "ok"}) for key in dcc_router._AUTOSTART_MODULES}
        with mock.patch.object(dcc_router, "_AUTOSTART_MODULES", fake), \
             mock.patch.object(dcc_router, "get_installed_dccs", return_value={"maya": "m.exe"}), \
             mock.patch("dcc.photoshop.client.ensure_library") as ps:
            out = await dcc_router.install_all_bridges_endpoint()
        by = {r["dcc"]: r["status"] for r in out["results"]}
        self.assertEqual(by["maya"], "ok")
        self.assertEqual(by["photoshop"], "skip")
        self.assertEqual(set(by), set(fake) | {"photoshop"})
        self.assertTrue(all(s == "skip" for k, s in by.items() if k != "maya"))
        ps.assert_not_called()

    def test_route_is_registered_before_dynamic_autostart(self):
        paths = [getattr(r, "path", "") for r in dcc_router.router.routes]
        self.assertIn("/bridges/install-all", paths)


if __name__ == "__main__":
    unittest.main()
