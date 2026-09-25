# shot_light.py — publish the light rig of one shot from the sequence scene (A5).
#
# The FLUX Shot node of the Houdini sequence scene ends with a Layer Break: the lights
# the lighter adds after it are new layers. Its "Publier le light rig du shot" button
# writes them (USD ROP, layers above the break stripped) to a temp file, then this
# module publishes that file as the LIGHT department of the shot: SEQ_SHOT_LIGHT, an
# immutable vNNN folder + a LAST pointer (ADR 0017), and the shot stage is regenerated
# (the stage sublayers the LIGHT publish, ADR 0020).

from __future__ import annotations

import shutil
from pathlib import Path

from core.logger import get_logger

log = get_logger("usd_assembler.shot_light")

LIGHT_TYPE = "LIGHT"


def light_base(seq: str, shot: str) -> str:
    return f"{seq.upper()}_{shot.upper()}_{LIGHT_TYPE}"


def _defines_prims(layer) -> bool:
    """True when the layer defines at least one prim (a light rig). A layer of "over"
    only edits lights published before: published alone, the new version would replace
    the old one and those lights would vanish from the shot."""
    from pxr import Sdf

    found = []

    def _visit(path):
        if not found and path.IsPrimPath():
            spec = layer.GetPrimAtPath(path)
            if spec is not None and spec.specifier == Sdf.SpecifierDef:
                found.append(path)

    layer.Traverse(Sdf.Path.absoluteRootPath, _visit)
    return bool(found)


def publish_shot_light(source: str | Path, project_path: str | Path, seq: str, shot: str, *,
                       user: str = "") -> dict:
    """Publish *source* (an exported light layer) as the shot's LIGHT department.

    Returns {"base", "version", "folder", "root", "last", "stage", "warnings"}. ValueError
    when the file is missing, holds only edits ("over") of existing lights, or the tokens
    cannot place the publish. Sublayers of the export (the shot stage above the Layer
    Break) are dropped from the published copy: they would loop the stage into itself.
    """
    from pxr import Sdf

    from features.folder_manager.naming_validator import format_version
    from features.publisher import last_pointer as lp
    from features.publisher.publish_core import ensure_dir, resolve_publish_path
    from features.publisher.publish_layout import (
        discard_rendered_version, reserve_version, sequence_folder,
    )

    src = Path(source)
    if not src.is_file():
        raise ValueError(f"fichier de lumieres introuvable : {src}")
    layer = Sdf.Layer.FindOrOpen(str(src))
    if layer is None:
        raise ValueError(f"USD illisible : {src.name}")
    if not layer.rootPrims:
        raise ValueError("aucune lumiere a publier : ajoute les lumieres apres le node FLUX Shot")
    if not _defines_prims(layer):
        raise ValueError("le light rig ne contient que des modifications (over) de lumieres deja "
                         "publiees : publie-le, il remplacerait l'ancien et ces lumieres disparaitraient. "
                         "Cree ou duplique les lumieres apres le node FLUX Shot")
    warnings: list[str] = []

    project = Path(project_path)
    base = light_base(seq, shot)
    ext = ".usda"
    parent = resolve_publish_path(project, f"{base}{ext}")
    if parent is None:
        raise ValueError(f"chemin de publish introuvable pour {base} (token TYPE_SHOT LIGHT)")
    ensure_dir(parent)
    ver = reserve_version(parent, base, ext)
    folder = sequence_folder(parent, base, ver)
    folder.mkdir(parents=True, exist_ok=True)
    root = folder / f"{base}{ext}"
    try:
        # Export (not copy) so a crate or an anonymous-layer file lands as clean usda.
        if not layer.Export(str(root)):
            shutil.copy2(src, root)
        published = Sdf.Layer.FindOrOpen(str(root))
        if published is not None and published.subLayerPaths:
            warnings.append(f"{len(published.subLayerPaths)} sublayer(s) retire(s) du light rig "
                            "(le stage du shot au-dessus du Layer Break)")
            published.subLayerPaths = []
            published.Save()
    except Exception:
        discard_rendered_version(parent, base, ext, ver, is_sequence=True)
        raise
    last = lp.write_last(parent, base, ext, folder, ver, lp.MODE_LAYER, user=user,
                         layer_target=f"{folder.name}/{root.name}")

    from features.publisher.modif_log import append_log

    version = format_version(ver)
    append_log(parent, base, version, "light rig du shot publie depuis la scene de sequence", user or "flux")

    from features.publisher.usd_publish_hooks import after_usd_publish

    hooked = after_usd_publish(parent, base, ext, root, user=user)
    stage = (hooked.get("shot") or {}).get("version")
    log.info("Shot light %s %s -> %s (stage %s)", base, version, folder, stage or "unchanged")
    return {"base": base, "version": version, "folder": folder, "root": root, "last": last,
            "stage": stage, "warnings": warnings}


def list_stage_shots(project_path: str | Path) -> list[dict]:
    """Shots that have a stage, for the FLUX Shot node menus.

    [{"seq", "shot", "last", "versions", "files": {vNNN: entry}, "range", "fps"}]."""
    from features.importer.library_import import _stage_shots
    from features.publisher.last_pointer import read_usd_root_info

    from . import shot_stage as ss

    project = Path(project_path)
    out = []
    for seq, shot in _stage_shots(project):
        versions = ss.stage_versions(project, seq, shot)
        last = ss.last_file(project, seq, shot)
        if not versions or not last.is_file():
            continue
        name = ss.entity(seq, shot)
        parent = ss.stage_dir(project, seq, shot)
        info = read_usd_root_info(last)
        rng = ([int(info["startTimeCode"]), int(info["endTimeCode"])]
               if "startTimeCode" in info and "endTimeCode" in info else None)
        out.append({
            "seq": seq, "shot": shot, "last": str(last), "versions": versions,
            "files": {v: str(parent / f"{name}_{v}" / f"{name}{ss.STAGE_EXT}") for v in versions},
            "range": rng,
            "fps": float(info.get("framesPerSecond") or info.get("timeCodesPerSecond") or 24),
        })
    return out
