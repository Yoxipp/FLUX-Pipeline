# Test fixture: a studio environment file with realistic values (the school farm the render code was
# first validated on). Production code ships none of these values; tests write them to a temp file.
from __future__ import annotations

import json
import tempfile
from pathlib import Path

SAMPLE_FARM = {
    "engine_user": "root",
    "bridge_python": "",
    "blade_tractor_python": "C:/Program Files/Pixar/Tractor-2.4/bin/rmanpy.exe",
    "houdini_path": "C:/Program Files/Side Effects Software/Houdini 20.5.445",
    "denoise_path": "C:/Program Files/Pixar/RenderManProServer-26.3/bin/denoise_batch.exe",
    "renderer": "renderman",
    "denoise_tag": "Denoise",
    "room_pattern": r"^([A-Za-z]+)(\d{2})[A-Za-z0-9]+$",
    "forbid_drive_letters": True,
}


def write_env(folder: Path | str | None = None, **farm) -> Path:
    """Write an environment file (SAMPLE_FARM + overrides) and return its path."""
    base = Path(folder) if folder else Path(tempfile.mkdtemp())
    path = base / "studio_env.json"
    path.write_text(json.dumps({"schema_version": 1, "name": "test", "farm": {**SAMPLE_FARM, **farm}}), encoding="utf-8")
    return path
