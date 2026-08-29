# stage_factory.py — isolated creation of Usd.Stage objects (the only entry
# point for stages, so tests can spin one up without touching disk).

from __future__ import annotations

from pathlib import Path

from pxr import Usd


def in_memory() -> "Usd.Stage":
    """Return a fresh anonymous in-memory stage (no disk I/O). For tests."""
    return Usd.Stage.CreateInMemory()


def new_stage(root_path: str | Path) -> "Usd.Stage":
    """Create a new stage whose root layer is *root_path*.

    The file extension (.usda/.usdc/.usd) selects the on-disk format. Parent
    directories are created if missing.
    """
    path = Path(root_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return Usd.Stage.CreateNew(str(path))
