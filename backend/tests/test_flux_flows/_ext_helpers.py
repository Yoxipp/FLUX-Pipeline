# Helpers of the P6c tests: a temporary CONFIG/extensions/bridges/ folder.

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from unittest import mock

from flux_flows.bridges import extension

MAX_YML = """\
soft: max
label: 3ds Max
icon: Box
prefix: max
exe_hints: []
port_range: [7100, 4]
transport: tcp_json
install:
  target: "{target}"
  files: [flux_max_bridge.py]
"""


class ExtFolder:
    """A bridges/ folder with patched lookups. ``add(soft, text, files)``."""

    def __init__(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_ext_"))
        self.root = self.tmp / "extensions" / "bridges"
        self.root.mkdir(parents=True)
        self._p = mock.patch.object(extension, "bridges_dir", side_effect=lambda: self.root)

    def __enter__(self) -> "ExtFolder":
        extension.reset_cache()
        self._p.start()
        return self

    def __exit__(self, *exc) -> None:
        self._p.stop()
        extension.reset_cache()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add(self, soft: str, text: str, files: dict | None = None) -> Path:
        folder = self.root / soft
        (folder / "dcc_side").mkdir(parents=True, exist_ok=True)
        (folder / extension.MANIFEST).write_text(text, encoding="utf-8")
        for name, body in (files or {}).items():
            (folder / "dcc_side" / name).write_text(body, encoding="utf-8")
        extension.reset_cache()
        return folder
