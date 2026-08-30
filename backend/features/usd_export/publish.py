# publish.py — place a light layered asset into the Flux publish layout with
# LAST/vNNN versioning, keeping every version set self-consistent.
#
# Active set:   {asset}_LAST.usd + {asset}_{model,skel,anim}_LAST.usd
# Archived set: {asset}_vNNN.usd + {asset}_{model,skel,anim}_vNNN.usd
# The archived root's subLayerPaths are rewritten from _LAST to _vNNN so old
# versions keep pointing at their own sublayers. The resolver reads {asset}_LAST.*.

from __future__ import annotations

import tempfile
from pathlib import Path

from pxr import Sdf

from core.constants import ACTIVE_VERSION_LABEL
from core.logger import get_logger
from features.publisher.publish_core import ensure_dir, rename_last_to_versioned
from features.publisher.version_resolver import get_next_version

from .contract import LightAsset
from .skel_export import author_light_asset

log = get_logger("usd_export.publish")

# Published layout under the project (matches the assembler's FluxResolver).
_USD_SUBDIR = "{asset}/model/usd"
_SUBLAYER_SUFFIXES = ("model", "skel", "anim")


def _rewrite_archived_root_sublayers(root_path: Path, version_label: str) -> None:
    """Point an archived root at its own versioned sublayers (rename _LAST -> _vNNN)."""
    layer = Sdf.Layer.FindOrOpen(str(root_path).replace("\\", "/"))
    if layer is None:
        log.warning("archived root not reopenable: %s", root_path)
        return
    old = ACTIVE_VERSION_LABEL
    new_subs = [p.replace(f"_{old}.", f"_{version_label}.") for p in layer.subLayerPaths]
    layer.subLayerPaths = new_subs
    layer.Save()


def publish_light_asset(
    asset: LightAsset,
    project_path: str | Path,
    *,
    fmt: str = "usd",
    config: dict | None = None,
) -> dict:
    """Author *asset* and publish it as the active LAST set under *project_path*.

    Returns {"root": Path, "version": "vNNN", "layers": {name: Path}}.
    """
    project = Path(project_path)
    subdir = (config or {}).get("usd_export", {}).get("usd_subdir", _USD_SUBDIR)
    dest = project / subdir.format(asset=asset.asset)
    ensure_dir(dest)

    # Version number the new active set will represent (mirrors publish_core).
    next_ver = get_next_version(dest, asset.asset)
    had_last = rename_last_to_versioned(dest, asset.asset, next_ver) is not None
    if had_last:
        for suffix in _SUBLAYER_SUFFIXES:
            rename_last_to_versioned(dest, f"{asset.asset}_{suffix}", next_ver)
        archived_root = next(dest.glob(f"{asset.asset}_v{next_ver:03d}.*"), None)
        if archived_root is not None:
            _rewrite_archived_root_sublayers(archived_root, f"v{next_ver:03d}")
    new_ver = next_ver + 1 if had_last else next_ver

    # Author the fresh active set in a temp dir, then move it into place.
    with tempfile.TemporaryDirectory() as tmp:
        authored = author_light_asset(asset, tmp, fmt=fmt, version_label=ACTIVE_VERSION_LABEL)
        moved: dict[str, Path] = {}
        for key, src in authored.items():
            target = dest / src.name
            if target.exists():
                target.unlink()
            src.replace(target)
            moved[key] = target

    version_str = f"v{new_ver:03d}"
    log.info("Published light asset %s (%s) -> %s", asset.asset, version_str, moved["root"].name)
    return {"root": moved["root"], "version": version_str, "layers": moved}
