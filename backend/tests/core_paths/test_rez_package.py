"""package.py evaluated with stand-ins for the Rez globals (Rez is not installed here)."""

from __future__ import annotations

import contextlib
import json
import os
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[3]


def _load() -> dict:
    scope: dict = {"early": lambda: (lambda func: func)}
    exec(compile((_ROOT / "package.py").read_text(encoding="utf-8"), "package.py", "exec"), scope)
    return scope


class RezPackageTests(unittest.TestCase):
    def test_version_is_the_app_version(self):
        with contextlib.chdir(_ROOT):
            version = _load()["version"]()
        expected = json.loads((_ROOT / "package.json").read_text(encoding="utf-8"))["version"]
        self.assertEqual(version, expected)

    def test_commands_only_adds_the_app(self):
        scope = _load()
        scope["env"], scope["alias"] = mock.MagicMock(), mock.MagicMock()
        scope["commands"]()
        scope["env"].PATH.append.assert_called_once_with("{root}/app")
        scope["alias"].assert_called_once_with("flux", "{root}/app/FLUX.exe")

    def test_build_command_copies_the_unpacked_app(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            (src / "INSTALLEURS" / "win-unpacked").mkdir(parents=True)
            (src / "INSTALLEURS" / "win-unpacked" / "FLUX.exe").write_bytes(b"x")
            dest = Path(tmp) / "dest"
            command = _load()["build_command"].format(root=src.as_posix())
            code = command[len('python -c "'):-1]
            env = {"REZ_BUILD_INSTALL": "1", "REZ_BUILD_INSTALL_PATH": str(dest)}
            with mock.patch.dict(os.environ, env):
                exec(code, {})
            self.assertTrue((dest / "app" / "FLUX.exe").is_file())


if __name__ == "__main__":
    unittest.main()
