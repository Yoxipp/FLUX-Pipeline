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
from .skel_export import author_light_asset, author_motion_only

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


def _match_rig(project_path, name: str | None, joints: list[str]) -> tuple[list[str], list[str]]:
    """(joints, warnings): the animated joints checked against the rig of asset *name*
    (motion only: the skeleton comes from the asset). A rig imported in Maya from the
    asset USD gets an extra root joint named after the Skeleton prim ("Skeleton/joint1"):
    that prefix is dropped when it makes every joint match. Never raises."""
    rig, warnings = _rig_joints(project_path, name)
    if rig is None:
        return joints, warnings
    if any(j not in rig for j in joints):
        stripped = [j.split("/", 1)[1] if "/" in j else j for j in joints]
        heads = {j.split("/", 1)[0] for j in joints}
        if len(heads) == 1 and all(j in rig for j in stripped):
            return stripped, [f"racine {heads.pop()} retiree : les joints suivent le rig de {name}"]
    missing = [j for j in joints if j not in rig]
    if not missing:
        return joints, []
    shown = ", ".join(missing[:5]) + (" ..." if len(missing) > 5 else "")
    return joints, [f"{len(missing)} joint(s) anime(s) absent(s) du rig de {name} : {shown}"]


def _rig_joints(project_path, name: str | None) -> tuple[set[str] | None, list[str]]:
    """Joints of the skeleton published for asset *name*, or (None, [warning])."""
    if not name:
        return None, ["anim sans perso reconnu : impossible de verifier le squelette"]
    try:
        from pxr import Usd, UsdSkel

        from features.usd_assembler.component_auto import component_dir

        folder = component_dir(project_path, name)
        entry = folder / f"{name}_LAST.usda" if folder is not None else None
        if entry is None or not entry.is_file():
            return None, [f"asset {name} sans USD publie : squelette non verifie"]
        stage = Usd.Stage.Open(str(entry))
        skel = next((UsdSkel.Skeleton(p) for p in stage.Traverse() if p.IsA(UsdSkel.Skeleton)), None)
        if skel is None:
            return None, [f"l'asset {name} n'a pas de squelette publie (GEO avec skin ou RIG)"]
        return set(skel.GetJointsAttr().Get() or []), []
    except Exception as exc:        # noqa: BLE001 - a check never blocks a publish
        return None, [f"squelette de {name} non verifie : {exc}"]


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

    A token-named asset publish (ADR 0019) keeps only its department's data
    (departments.restrict_light_asset, MULT refused) and its prim root is the NAME token.

    Returns {"root": Path (LAST pointer, or the version root if LAST is locked),
    "version": "vNNN", "folder": version folder, "version_root": Path, "layers": {...},
    "warnings": [...]}.
    """
    from .departments import character_name, contribution, is_motion_only, restrict_light_asset

    base = base_name or asset.asset
    contrib = contribution(base) if base_name else None
    warnings: list[str] = []
    root_name = None
    motion_only = is_motion_only(contrib)
    if contrib is not None:
        asset, warnings = restrict_light_asset(asset, contrib)
        root_name = contrib["name"] or None
        if motion_only and contrib["kind"] == "shot":
            root_name = character_name(contrib, project_path) or None
            if root_name is None:
                raise ValueError("anim de plan sans perso : nomme-la SEQ_SHOT_ANIM_<NAME> "
                                 "(4e case du Publisher = le perso anime)")
    if motion_only:
        if asset.anim is None or not asset.anim.joints:
            raise ValueError("aucune anim a publier : rien ne bouge sur la plage demandee "
                             "(active la plage d'animation et selectionne le rig)")
        joints, rig_warnings = _match_rig(project_path, root_name, asset.anim.joints)
        warnings += rig_warnings
        if joints != asset.anim.joints:
            asset = replace(asset, anim=replace(asset.anim, joints=joints))
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

    # RIG (ADR 0034): the skin lands on the meshes (and proxies) of the published model.
    skin_kw: dict = {}
    skin_meshes = [m for m in asset.meshes if m.skin_only]
    if skin_meshes and not motion_only:
        from .rig_skin import skin_targets

        targets, proxy_skins, skin_warnings = skin_targets(project_path, root_name, skin_meshes)
        warnings += skin_warnings
        skin_kw = {"skin_targets": targets, "proxy_skins": proxy_skins}

    # Author straight into the reserved version folder (no rename, ADR 0017 U3b rule).
    light = replace(asset, asset=base)
    try:
        if motion_only:
            authored = author_motion_only(light, folder, fmt=fmt.lstrip("."), root_name=root_name)
        else:
            authored = author_light_asset(light, folder, fmt=fmt.lstrip("."), version_label=None,
                                          root_name=root_name, **skin_kw)
    except Exception:
        discard_rendered_version(parent, base, ext, ver, is_sequence=True)
        raise

    root = authored["root"]
    last = lp.write_last(parent, base, ext, folder, ver, lp.MODE_LAYER, user=user,
                         layer_target=f"{folder.name}/{root.name}")

    log.info("Published light asset %s (%s) -> %s", base, version_str, folder)

    # USD_ASSEMBLER_V2 A1 / ADR 0019: proxy layer beside the version root, then the
    # asset (component). Only for token-resolved publishes (dest_dir); never fails.
    component = None
    if dest_dir is not None:
        from features.publisher.usd_publish_hooks import after_usd_publish

        hooked = after_usd_publish(parent, base, ext, root, user=user)
        component = hooked["component"]

    for w in warnings:
        log.warning("Light asset %s: %s", base, w)
    return {"root": last or root, "version": version_str, "folder": folder,
            "version_root": root, "layers": authored,
            "component": component["version"] if component else None, "warnings": warnings}
