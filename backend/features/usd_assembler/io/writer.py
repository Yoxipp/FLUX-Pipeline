# writer.py — atomic stage writing: export to a temp sibling, then os.replace so
# readers never observe a half-written layer. Handles a single root layer or a
# shot's full set (root + department sublayers) in one call.

from __future__ import annotations

import os
from pathlib import Path

from pxr import Sdf, Usd


def _export_atomic(layer: "Sdf.Layer", dest: "Path") -> Path:
    """Export *layer* to *dest* atomically (temp sibling + os.replace)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Temp sibling keeps the same extension so USD picks the right format.
    tmp_path = dest.with_name(f".{dest.stem}.tmp{dest.suffix}")
    try:
        if not layer.Export(str(tmp_path)):
            raise RuntimeError(f"USD export failed for {dest}")
        os.replace(tmp_path, dest)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
    return dest


class StageWriter:
    """Write a stage's root layer (and optional department sublayers) atomically."""

    def write(self, stage: "Usd.Stage", dest: str | Path) -> Path:
        """Write the stage's root layer to *dest* atomically."""
        return _export_atomic(stage.GetRootLayer(), Path(dest))

    def write_all(
        self,
        stage: "Usd.Stage",
        department_layers: dict,
        dest_dir: str | Path,
        root_name: str,
    ) -> list[Path]:
        """Write the root layer plus every department layer into *dest_dir*.

        *department_layers* is ``{dept: (filename, Sdf.Layer)}`` as returned by
        ``StageComposer.department_layers()``. The root's ``subLayerPaths`` already
        reference those file names relatively, so writing them side by side yields
        a self-consistent, reopenable shot. Returns every written path, root first.
        """
        dest_dir = Path(dest_dir)
        root_layer = stage.GetRootLayer()
        ext = root_layer.GetFileFormat().primaryFileExtension
        root_path = dest_dir / f"{root_name}.{ext}"

        written = [_export_atomic(root_layer, root_path)]
        for _dept, (filename, layer) in department_layers.items():
            written.append(_export_atomic(layer, dest_dir / filename))
        return written
