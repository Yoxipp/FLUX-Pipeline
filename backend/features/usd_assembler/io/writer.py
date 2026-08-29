# writer.py — atomic stage writing: export to a temp sibling, then os.replace so
# readers never observe a half-written layer.

from __future__ import annotations

import os
from pathlib import Path

from pxr import Usd


class StageWriter:
    """Write a stage's root layer to *dest* atomically (tmp + rename)."""

    def write(self, stage: "Usd.Stage", dest: str | Path) -> Path:
        dest_path = Path(dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        # Temp sibling keeps the same extension so USD picks the right format.
        tmp_path = dest_path.with_name(f".{dest_path.stem}.tmp{dest_path.suffix}")
        try:
            exported = stage.GetRootLayer().Export(str(tmp_path))
            if not exported:
                raise RuntimeError(f"USD export failed for {dest_path}")
            os.replace(tmp_path, dest_path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
        return dest_path
