# Packaged app: non-Python files read at runtime must be bundled by backend.spec,
# and an uncaught route error must reach the FLUX log + the front with its message.

from __future__ import annotations

import glob
import re
import unittest
from pathlib import Path

from fastapi import APIRouter
from fastapi.testclient import TestClient

import main

_BACKEND = Path(__file__).resolve().parents[2]
_SPEC = _BACKEND.parent / "scripts" / "backend.spec"


def _bundled_sources() -> list[str]:
    """Every file matched by an `app_datas` source of backend.spec."""
    text = _SPEC.read_text(encoding="utf-8")
    block = text.split("app_datas = [", 1)[1].split("\n]", 1)[0]
    files: list[str] = []
    for rel in re.findall(r'ROOT / "([^"]+)"', block):
        for match in map(Path, glob.glob(str(_BACKEND.parent / rel))):
            # A folder source is copied recursively by PyInstaller.
            found = [f for f in match.rglob("*") if f.is_file()] if match.is_dir() else [match]
            files += [str(f.resolve()) for f in found]
    return files


class FrozenBundleData(unittest.TestCase):
    def test_every_action_yaml_is_bundled(self) -> None:
        bundled = _bundled_sources()
        ymls = sorted((_BACKEND / "flux_actions" / "config").glob("*.yml"))
        self.assertTrue(ymls)
        for yml in ymls:
            self.assertIn(str(yml.resolve()), bundled, f"{yml.name} missing from backend.spec")

    def test_every_shipped_flow_is_bundled(self) -> None:
        bundled = _bundled_sources()
        flows = sorted((_BACKEND / "flux_flows" / "shipped").rglob("*.flow.yml"))
        self.assertTrue(flows)
        for flow in flows:
            self.assertIn(str(flow.resolve()), bundled, f"{flow.name} missing from backend.spec")

    def test_runtime_data_files_are_bundled(self) -> None:
        bundled = _bundled_sources()
        for rel in (
            "features/usd_assembler/recipe/schema.json",
            "dcc/houdini/flux_houdini_server.py",
            "dcc/substance_designer/substance_designer_bridge.py",
            "dcc/marvelous/marvelous_bridge.py",
            "flux_flows/bridges/templates/tcp_json_server.py",
            "flux_flows/bridges/templates/file_mailbox_server.py",
        ):
            self.assertIn(str((_BACKEND / rel).resolve()), bundled, rel)


class UnhandledErrorHandler(unittest.TestCase):
    def test_uncaught_error_returns_detail(self) -> None:
        router = APIRouter()

        @router.get("/__test_boom")
        async def boom() -> dict:
            raise FileNotFoundError("publish_houdini.yml")

        main.app.include_router(router)
        client = TestClient(main.app, raise_server_exceptions=False)
        with self.assertLogs("flux", level="ERROR"):
            r = client.get("/__test_boom")
        self.assertEqual(r.status_code, 500)
        self.assertIn("FileNotFoundError", r.json()["detail"])
        self.assertIn("publish_houdini.yml", r.json()["detail"])


if __name__ == "__main__":
    unittest.main()
