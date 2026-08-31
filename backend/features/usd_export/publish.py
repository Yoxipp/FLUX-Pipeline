# publish.py — place a light layered asset into the Flux publish layout.
#
# The whole light asset (root + model/skel/anim) lives in ONE per-version folder:
#   <dest>/<base>_LAST/         active version  (root <base>.usd + <base>_{model,skel,anim}.usd)
#   <dest>/<base>_vNNN/         archived versions
# Archiving is a folder rename, so the root keeps pointing at its sibling sublayers
# (relative names) with no rewriting. <dest> is the token-resolved publish folder, so
# the light asset sits next to the DCC's normal publishes.

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from core.constants import ACTIVE_VERSION_LABEL
from core.logger import get_logger
from features.publisher.publish_core import ensure_dir

from .contract import LightAsset
from .skel_export import author_light_asset

log = get_logger("usd_export.publish")

# Fallback layout under the project when no dest_dir is given (matches FluxResolver).
_USD_SUBDIR = "{asset}/model/usd"


def _next_version(parent: Path, base: str) -> int:
    """Highest existing {base}_vNNN archive number + 1 (1 when none).

    Counts BOTH archived folders ({base}_vNNN/) and archived flat files
    ({base}_vNNN.ext) so layered and non-layered publishes share one version line.
    """
    n = 0
    if parent.exists():
        rx = re.compile(re.escape(base) + r"_v(\d+)(?:\.[^.]+)?$")
        for d in parent.iterdir():
            m = rx.match(d.name)
            if m:
                n = max(n, int(m.group(1)))
    return n + 1


def publish_light_asset(
    asset: LightAsset,
    project_path: str | Path,
    *,
    fmt: str = "usd",
    config: dict | None = None,
    dest_dir: str | Path | None = None,
    base_name: str | None = None,
) -> dict:
    """Author *asset* and publish it as the active LAST folder.

    *dest_dir* is the output folder (pass the token-resolved publish path); *base_name*
    is the file/folder stem (e.g. "CHAR_BLOCK_DAVID_null"). Falls back to
    ``{project}/{asset}/model/usd`` and the asset name when omitted.

    Returns {"root": Path, "version": "vNNN", "folder": Path, "layers": {name: Path}}.
    """
    base = base_name or asset.asset
    if dest_dir is not None:
        parent = Path(dest_dir)
    else:
        subdir = (config or {}).get("usd_export", {}).get("usd_subdir", _USD_SUBDIR)
        parent = Path(project_path) / subdir.format(asset=asset.asset)
    ensure_dir(parent)

    active = parent / f"{base}_{ACTIVE_VERSION_LABEL}"   # e.g. CHAR_..._LAST/
    # Archive any previous active version before taking the LAST slot: a folder (a prior
    # layered export) AND any flat {base}_LAST.ext file left by the non-layered USD
    # publisher — otherwise a _LAST/ folder and a _LAST.usda file would coexist.
    stale_files = [
        p for p in parent.glob(f"{base}_{ACTIVE_VERSION_LABEL}.*")
        if p.is_file()
    ] if parent.exists() else []
    if active.exists() or stale_files:
        ver = _next_version(parent, base)
        if active.exists():
            active.rename(parent / f"{base}_v{ver:03d}")     # archive the whole folder
        for f in stale_files:
            f.rename(parent / f"{base}_v{ver:03d}{f.suffix}")  # archive the flat LAST file
        version_str = f"v{ver + 1:03d}"
    else:
        version_str = "v001"
    active.mkdir(parents=True, exist_ok=True)

    # Name the files off the base (plain names; the folder carries the version).
    light = replace(asset, asset=base)
    authored = author_light_asset(light, active, fmt=fmt, version_label=None)

    log.info("Published light asset %s (%s) -> %s", base, version_str, active)
    return {"root": authored["root"], "version": version_str, "folder": active, "layers": authored}
