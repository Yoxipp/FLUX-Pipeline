# P6c (2026-10-23): installation of an extension bridge (01 §12): copy + <script>.json,
# never a silent overwrite (conflict, then backup), uninstall removes only FLUX's files and
# restores backups, paths contained, "Installer tous les bridges" includes the extensions.

from __future__ import annotations

import json
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from flux_flows.bridges import extension, installer
from routers import flows as flows_router
from tests.test_flux_flows._ext_helpers import MAX_YML, ExtFolder

SCRIPT = "print('flux max bridge')\n"


class Installer(unittest.TestCase):
    def setUp(self) -> None:
        self.ext = ExtFolder().__enter__()
        self.target = self.ext.tmp / "max_prefs" / "startup"
        self.ext.add("max", MAX_YML.format(target=self.target.as_posix()), {"flux_max_bridge.py": SCRIPT})
        self.bridge = extension.get("max")

    def tearDown(self) -> None:
        self.ext.__exit__(None, None, None)

    def test_install_writes_script_config_and_receipt(self) -> None:
        self.assertEqual(installer.status(self.bridge)["state"], "absent")
        got = installer.install(self.bridge)
        self.assertTrue(got["success"], got)
        self.assertEqual((self.target / "flux_max_bridge.py").read_text(encoding="utf-8"), SCRIPT)
        cfg = json.loads((self.target / "flux_max_bridge.json").read_text(encoding="utf-8"))
        self.assertEqual((cfg["soft"], cfg["port_base"], cfg["port_count"]), ("max", 7100, 4))
        self.assertTrue((self.target / installer.receipt_name("max")).is_file())
        self.assertEqual(installer.status(self.bridge)["state"], "installed")
        # A new version of the script in dcc_side/ replaces FLUX's copy without asking.
        (self.bridge.folder / "dcc_side" / "flux_max_bridge.py").write_text(SCRIPT + "# v2\n", encoding="utf-8")
        self.assertEqual(installer.status(self.bridge)["state"], "outdated")
        self.assertTrue(installer.install(self.bridge)["success"])
        self.assertIn("# v2", (self.target / "flux_max_bridge.py").read_text(encoding="utf-8"))

    def test_conflict_is_never_overwritten_silently(self) -> None:
        self.target.mkdir(parents=True)
        (self.target / "flux_max_bridge.py").write_text("# the artist's own script\n", encoding="utf-8")
        got = installer.install(self.bridge)
        self.assertFalse(got["success"])
        self.assertEqual(got["conflicts"], ["flux_max_bridge.py"])
        self.assertEqual((self.target / "flux_max_bridge.py").read_text(encoding="utf-8"), "# the artist's own script\n")
        self.assertFalse((self.target / "flux_max_bridge.json").exists())
        self.assertEqual(installer.status(self.bridge)["state"], "conflict")
        got = installer.install(self.bridge, overwrite=True)
        self.assertTrue(got["success"], got)
        self.assertEqual(len(got["backups"]), 1)
        # Uninstall removes FLUX's files and gives the artist's file back.
        out = installer.uninstall(self.bridge)
        self.assertEqual(sorted(out["removed"]), ["flux_max_bridge.json", "flux_max_bridge.py"])
        self.assertEqual(out["restored"], ["flux_max_bridge.py"])
        self.assertEqual((self.target / "flux_max_bridge.py").read_text(encoding="utf-8"), "# the artist's own script\n")
        self.assertEqual(sorted(p.name for p in self.target.iterdir()), ["flux_max_bridge.py"])

    def test_uninstall_keeps_a_file_changed_after_install(self) -> None:
        installer.install(self.bridge)
        (self.target / "flux_max_bridge.py").write_text("# edited in place\n", encoding="utf-8")
        out = installer.uninstall(self.bridge)
        self.assertEqual(out["kept"], ["flux_max_bridge.py"])
        self.assertTrue((self.target / "flux_max_bridge.py").exists())
        self.assertFalse((self.target / "flux_max_bridge.json").exists())
        self.assertIn("rien a desinstaller", installer.uninstall(self.bridge)["message"])

    def test_target_resolution(self) -> None:
        self.ext.add("max", MAX_YML.format(target="{exe_dir}/scripts/startup"), {"flux_max_bridge.py": SCRIPT})
        bridge = extension.get("max")
        with self.assertRaisesRegex(installer.InstallError, "exe_dir"):
            installer.target_dir(bridge)
        exe = self.ext.tmp / "3ds Max" / "3dsmax.exe"
        self.assertEqual(installer.target_dir(bridge, str(exe)), exe.parent / "scripts" / "startup")
        with mock.patch.dict("os.environ", {"FLUX_TEST_MAX": str(self.ext.tmp)}):
            self.ext.add("max", MAX_YML.format(target="%FLUX_TEST_MAX%/a"), {"flux_max_bridge.py": SCRIPT})
            self.assertEqual(installer.target_dir(extension.get("max")), self.ext.tmp / "a")
        self.ext.add("max", MAX_YML.format(target="%FLUX_NOPE_VAR%/a"), {"flux_max_bridge.py": SCRIPT})
        self.assertIn("variable", installer.install(extension.get("max"))["message"])
        self.ext.add("max", MAX_YML.format(target="relative/dir"), {"flux_max_bridge.py": SCRIPT})
        self.assertIn("absolu", installer.install(extension.get("max"))["message"])

    def test_paths_stay_contained(self) -> None:
        outside = self.ext.tmp / "secret.py"
        outside.write_text("x", encoding="utf-8")
        try:
            (self.bridge.folder / "dcc_side" / "link.py").symlink_to(outside)
        except OSError:
            self.skipTest("symlink indisponible (Windows sans mode developpeur)")
        self.ext.add("max", MAX_YML.format(target=self.target.as_posix()).replace(
            "[flux_max_bridge.py]", "[link.py]"))
        got = installer.install(extension.get("max"))
        self.assertFalse(got["success"])
        self.assertIn("sort de dcc_side", got["message"])
        # A receipt edited by hand never makes uninstall delete outside the target.
        installer.install(self.bridge)
        receipt = self.target / installer.receipt_name("max")
        data = json.loads(receipt.read_text(encoding="utf-8"))
        data["files"]["../../secret.py"] = {"sha256": "x"}
        receipt.write_text(json.dumps(data), encoding="utf-8")
        self.ext.add("max", MAX_YML.format(target=self.target.as_posix()), {"flux_max_bridge.py": SCRIPT})
        out = installer.uninstall(extension.get("max"))
        self.assertIn("../../secret.py", out["kept"])
        self.assertTrue(outside.exists())

    def test_install_all_includes_extensions(self) -> None:
        from features.launcher.bridges import install_all_bridges

        installed, modules = installer.install_all_entries()
        self.assertEqual(list(modules), ["3ds Max (extension)"])
        self.assertIn("3ds Max (extension)", installed)        # no exe_hints, no {exe_dir}
        (res,) = install_all_bridges(installed, modules)
        self.assertEqual(res["status"], "ok", res)
        self.assertTrue((self.target / "flux_max_bridge.py").exists())
        self.ext.add("max", MAX_YML.format(target=self.target.as_posix()).replace(
            "exe_hints: []", "exe_hints: ['/nope/3dsmax.exe']"), {"flux_max_bridge.py": SCRIPT})
        installed, modules = installer.install_all_entries()
        self.assertEqual(install_all_bridges(installed, modules)[0]["status"], "skip")


class Routes(unittest.TestCase):
    def test_list_install_uninstall(self) -> None:
        app = FastAPI()
        app.include_router(flows_router.router, prefix="/flows")
        client = TestClient(app)
        with ExtFolder() as ext:
            target = ext.tmp / "t"
            ext.add("max", MAX_YML.format(target=target.as_posix()), {"flux_max_bridge.py": SCRIPT})
            ext.add("bad", "soft: bad\n")
            got = client.get("/flows/bridges").json()
            rows = {b["soft"]: b for b in got["bridges"]}
            self.assertEqual(rows["max"]["install"]["state"], "absent")
            self.assertFalse(rows["bad"]["ok"])
            self.assertIsNone(rows["bad"]["install"])
            r = client.post("/flows/bridges/max/install", json={})
            self.assertTrue(r.json()["success"], r.text)
            self.assertEqual(client.get("/flows/bridges").json()["bridges"][1]["install"]["state"], "installed")
            self.assertTrue(client.post("/flows/bridges/max/uninstall", json={}).json()["success"])
            self.assertEqual(client.post("/flows/bridges/nope/install", json={}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
