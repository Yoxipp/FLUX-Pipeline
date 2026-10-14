"""FLUX version: one source of truth (package.json fluxVersion) kept in sync everywhere.

scripts/build.cjs bumps package.json "fluxVersion" (x.x.xxx) and derives "version"
(semver, what electron-builder and the NSIS ${VERSION} use), backend APP_VERSION and
scripts/flux_version.nsh. A mismatch shows a wrong version in the app or the installer.
Also runs the node tests of the build.cjs helpers when node is available.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from core.constants import APP_VERSION

_ROOT = Path(__file__).resolve().parents[3]
_DISPLAY_RE = re.compile(r"^(\d+)\.(\d+)\.(\d{3})$")


def _pkg() -> dict:
    return json.loads((_ROOT / "package.json").read_text(encoding="utf-8"))


def _parse(text: str) -> tuple[int, int, int]:
    major, minor, build = text.split(".")
    return int(major), int(minor), int(build)


class AppVersionSyncTests(unittest.TestCase):
    def test_flux_version_is_display_format(self):
        self.assertRegex(_pkg()["fluxVersion"], _DISPLAY_RE)

    def test_semver_matches_flux_version(self):
        pkg = _pkg()
        self.assertEqual(_parse(pkg["version"]), _parse(pkg["fluxVersion"]))
        # electron-builder rejects leading zeros: the semver must not keep the padding.
        self.assertEqual(pkg["version"], ".".join(str(n) for n in _parse(pkg["fluxVersion"])))

    def test_backend_app_version_matches(self):
        self.assertEqual(APP_VERSION, _pkg()["fluxVersion"])

    def test_nsis_defines_match(self):
        nsh = (_ROOT / "scripts" / "flux_version.nsh").read_text(encoding="utf-8")
        pkg = _pkg()
        self.assertIn(f'!define FLUX_VERSION "{pkg["fluxVersion"]}"', nsh)
        self.assertIn(f'!define FLUX_SEMVER "{pkg["version"]}"', nsh)

    def test_atomic_build_wins_numerically(self):
        self.assertGreater(_parse("0.8.001"), _parse("0.8.000"))
        self.assertGreater(_parse("0.8.010"), _parse("0.8.009"))
        self.assertEqual(_parse("0.8.0"), _parse("0.8.000"))

    @unittest.skipUnless(shutil.which("node"), "node not on PATH")
    def test_build_cjs_helpers(self):
        script = _ROOT / "scripts" / "build_version.test.cjs"
        proc = subprocess.run(
            ["node", "--test", str(script)],
            cwd=str(_ROOT), capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
