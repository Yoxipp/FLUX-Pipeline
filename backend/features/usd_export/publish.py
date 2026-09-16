# publish.py — place a light layered asset into the Flux publish layout (ADR 0017).
#
# The whole light asset (root + model/skel/anim) lives in ONE immutable version folder,
# and LAST is a pointer layer beside it:
#   <dest>/<base>_vNNN/          root <base>.usd + <base>_{model,skel,anim}.usd (never rewritten)
#   <dest>/<base>_LAST.<fmt>     ~1 KB layer, subLayers = [@./<base>_vNNN/<base>.<fmt>@]
# The root keeps pointing at its sibling sublayers by relative name, so a version folder
# composes on its own. <dest> is the token-resolved publish folder, so the light asset
# sits next to the DCC's normal publishes. A legacy <base>_LAST/ folder (pre 0017) is
# copied to the next vNNN, then removed.

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

from core.constants import ACTIVE_VERSION_LABEL
from core.logger import get_logger
from features.folder_manager.naming_validator import format_version
from features.publisher import last_pointer as lp
from features.publisher.publish_core import ensure_dir
from features.publisher.publish_layout import (
    discard_rendered_version, reserve_version, sequence_folder,
)

from .contract import LightAsset
from .skel_export import author_light_asset

log = get_logger("usd_export.publish")

# Fallback layout under the project when no dest_dir is given (matches FluxResolver).
_USD_SUBDIR = "{asset}/model/usd"


def _archive_legacy_last_folder(parent: Path, base: str, ext: str) -> str | None:
    """Copy a pre-0017 <base>_LAST/ folder to the next free vNNN/, then remove it.

    Copy then delete (never rename: Windows locks). Returns the version label it took.
    """
    legacy = parent / f"{base}_{ACTIVE_VERSION_LABEL}"
    if not legacy.is_dir():
        return None
    ver = reserve_version(parent, base, ext)
    target = sequence_folder(parent, base, ver)
    shutil.copytree(legacy, target)
    shutil.rmtree(legacy, ignore_errors=True)
    if legacy.exists():
        log.warning("Old light asset folder kept (locked): %s", legacy)
    return format_version(ver)


def publish_light_asset(
    asset: LightAsset,
    project_path: str | Path,
    *,
    fmt: str = "usd",
    config: dict | None = None,
    dest_dir: str | Path | None = None,
    base_name: str | None = None,
    user: str = "",
) -> dict:
    """Author *asset* into a new immutable version folder and point LAST at it.

    *dest_dir* is the output folder (pass the token-resolved publish path); *base_name*
    is the file/folder stem (e.g. "CHAR_BLOCK_DAVID_null"). Falls back to
    ``{project}/{asset}/model/usd`` and the asset name when omitted.

    Returns {"root": Path (LAST pointer, or the version root if LAST is locked),
    "version": "vNNN", "folder": version folder, "version_root": Path, "layers": {...}}.
    """
    base = base_name or asset.asset
    if dest_dir is not None:
        parent = Path(dest_dir)
    else:
        subdir = (config or {}).get("usd_export", {}).get("usd_subdir", _USD_SUBDIR)
        parent = Path(project_path) / subdir.format(asset=asset.asset)
    ensure_dir(parent)
    ext = f".{fmt.lstrip('.')}"

    _archive_legacy_last_folder(parent, base, ext)
    ver = reserve_version(parent, base, ext)          # also archives a legacy flat LAST
    folder = sequence_folder(parent, base, ver)
    version_str = format_version(ver)

    # Author straight into the reserved version folder (no rename, ADR 0017 U3b rule).
    light = replace(asset, asset=base)
    try:
        authored = author_light_asset(light, folder, fmt=fmt.lstrip("."), version_label=None)
    except Exception:
        discard_rendered_version(parent, base, ext, ver, is_sequence=True)
        raise

    root = authored["root"]
    last = lp.write_last(parent, base, ext, folder, ver, lp.MODE_LAYER, user=user,
                         layer_target=f"{folder.name}/{root.name}")

    log.info("Published light asset %s (%s) -> %s", base, version_str, folder)

    # USD_ASSEMBLER_V2 A1: a GEO / RIG / SHADING publish regenerates the asset component.
    # Only for token-resolved publishes (dest_dir); never fails the publish.
    component = None
    if dest_dir is not None:
        from features.usd_assembler.component_auto import refresh_from_publish
        component = refresh_from_publish(project_path, base, user=user)

    return {"root": last or root, "version": version_str, "folder": folder,
            "version_root": root, "layers": authored,
            "component": component["version"] if component else None}
