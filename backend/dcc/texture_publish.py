# texture_publish.py — publish the maps a texturing app exported (Painter, Mari).
#
# The app writes one file per map, or one file per UDIM tile of a map
# ("Body_BaseColor_ACES - ACEScg.1001.exr"). Tiles of one map are ONE publish: a
# version folder <base>_vNNN/ holding every tile, LAST pointing at the <UDIM>
# pattern (like a Nuke / Houdini frame sequence, ADR 0017). Publishing tile by tile
# gave one version per tile and a LAST with only the last tile.

from __future__ import annotations

import re
import shutil
from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)

UDIM_TOKEN = "<UDIM>"
_TILE = re.compile(r"^(?P<core>.+?)[._](?P<tile>1\d{3})$")


def split_map_name(filename: str, whole_name: bool = False) -> tuple[str, int | None]:
    """(MAP token, UDIM tile or None) of an exported map file name.

    ``HeroBody_BaseColor.png`` -> ("BASECOLOR", None);
    ``Utah_Skin_BaseColor_ACES - ACEScg.1001.exr`` -> ("BASECOLOR", 1001).
    Trailing "X - Y" parts are colorspace labels added by the app ("ACES - ACEScg",
    "sRGB - Texture") and are skipped. *whole_name*: the file is named after the map
    only (Mari bridge: one file per channel), keep all of it ("B_COL" -> "BCOL").
    """
    stem = Path(filename).stem
    tile = None
    m = _TILE.match(stem)
    if m:
        stem, tile = m.group("core"), int(m.group("tile"))
    stem = stem.split(".")[0]
    parts = [p for p in stem.split("_") if p]
    while len(parts) > 1 and " - " in parts[-1]:
        parts.pop()
    kept = "".join(parts) if whole_name else (parts[-1] if parts else "")
    token = re.sub(r"[^A-Za-z0-9]", "", kept)
    return (token.upper() or "MAP"), tile


# One canonical MAP token per map, whatever the app calls it (2026-09-25: COL and
# BCOL, BASECOLOR and BCOL side by side). Same table as the Publisher's local-file
# autogroup (app/src/pages/Publisher.tsx MAP_ALIASES): keep both in sync.
MAP_ALIASES: dict[str, tuple[str, ...]] = {
    "BCOL":    ("bcol", "basecolor", "albedo", "diffuse", "diff", "color", "col"),
    "ROUGH":   ("rough", "roughness", "rgh"),
    "METAL":   ("metal", "metallic", "metalness", "mtl"),
    "SPEC":    ("spec", "specular"),
    "NORM":    ("norm", "normal", "nrm", "nml", "nor"),
    "BUMP":    ("bump",),
    "DISP":    ("disp", "displacement", "displace", "height"),
    "ZDISP":   ("zdisp",),
    "AO":      ("ao", "occlusion", "ambientocclusion"),
    "OPACITY": ("opacity", "alpha", "mask"),
    "EMISS":   ("emiss", "emissive", "emission", "emit"),
    "SSS":     ("sss", "subsurface", "scatter"),
    "GLOSS":   ("gloss", "glossiness"),
    "TRANS":   ("trans", "translucency"),
    "CAVITY":  ("cavity",),
    "CURV":    ("curv", "curvature"),
    "ISO":     ("iso",),
}
_ALIAS_TO_TOKEN = {alias: token for token, aliases in MAP_ALIASES.items() for alias in aliases}


def canonical_map_token(filename: str, whole_name: bool = False) -> str | None:
    """Canonical MAP token of an exported map, None when no alias matches.

    The whole map name first ("B_COL" -> "bcol" -> BCOL, "Ambient Occlusion" -> AO),
    then its parts from the last one ("Body_BaseColor" -> BCOL, "Mesh_Normal_OpenGL" ->
    NORM). ZDISP stays ZDISP (exact match, never read as DISP)."""
    stem = Path(filename).stem
    m = _TILE.match(stem)
    if m:
        stem = m.group("core")
    stem = stem.split(".")[0]
    parts = [p for p in stem.split("_") if p]
    while len(parts) > 1 and " - " in parts[-1]:
        parts.pop()
    if not whole_name and parts:
        # An app file name: <set / mesh>_<map>; only the map part (the end) counts, a
        # set called "Metal_Armor" must not make its maps METAL. "Normal_OpenGL": the
        # API suffix is skipped.
        while len(parts) > 1 and parts[-1].lower() in ("opengl", "directx", "ogl", "dx"):
            parts.pop()
        candidates = parts[-1:]
    else:
        candidates = ["".join(parts)] + [p for p in reversed(parts)]
    for cand in candidates:
        key = re.sub(r"[^a-z0-9]", "", cand.lower())
        if key in _ALIAS_TO_TOKEN:
            return _ALIAS_TO_TOKEN[key]
        words = [w for w in re.split(r"[^a-z0-9]+", cand.lower()) if w]
        for w in reversed(words):
            if w in _ALIAS_TO_TOKEN:
                return _ALIAS_TO_TOKEN[w]
    return None


def group_maps(files: list[Path], whole_name: bool = False,
               warnings: list[str] | None = None) -> dict[str, list[tuple[int | None, Path]]]:
    """{MAP token: [(tile, file), ...]} sorted by tile.

    Each map gets its canonical token (BCOL, DISP, NORM...). Two different maps landing
    on the same one (a "DISP" and a "Displacement" channel): the map already named like
    the token keeps it, the other keeps its own name, and a warning says so."""
    raw_groups: dict[str, list[tuple[int | None, Path]]] = {}
    canon: dict[str, str | None] = {}
    for f in files:
        raw, tile = split_map_name(f.name, whole_name)
        raw_groups.setdefault(raw, []).append((tile, Path(f)))
        canon.setdefault(raw, canonical_map_token(f.name, whole_name))
    groups: dict[str, list[tuple[int | None, Path]]] = {}
    owner: dict[str, str] = {}
    # A map already named like its token goes first, then alphabetical: stable choice.
    for raw in sorted(raw_groups, key=lambda r: (r != canon[r], r)):
        token = canon[raw] or raw
        if token in owner and owner[token] != raw:
            if warnings is not None:
                warnings.append(f"{raw} : meme map que {owner[token]} ({token}), publie sous {raw}")
            token = raw
        owner.setdefault(token, raw)
        groups.setdefault(token, []).extend(raw_groups[raw])
    for items in groups.values():
        items.sort(key=lambda it: (it[0] is None, it[0] or 0))
    return groups


def publish_udim_map(tiles: list[tuple[int, Path]], project_path: Path, project: str,
                     target_name: str, description: str, user: str) -> Path | None:
    """Publish every tile of one map as ONE version. Returns the version folder."""
    from features.activity.activity_writer import log_publish
    from features.folder_manager.naming_validator import format_version, get_base_name
    from features.publisher.modif_log import append_log
    from features.publisher.publish_core import resolve_publish_path
    from features.publisher.publish_layout import (
        DEFAULT_PADDING, discard_rendered_version, finalize_rendered_version,
        reserve_version, sequence_folder,
    )

    ext = tiles[0][1].suffix.lower()
    full_name = f"{target_name}{ext}"
    dest_folder = resolve_publish_path(project_path, full_name)
    if dest_folder is None:
        log.warning("UDIM map not published (unresolved name): %s", full_name)
        return None
    base = get_base_name(full_name)
    ver = reserve_version(dest_folder, base, ext)
    ver_str = format_version(ver, DEFAULT_PADDING)
    folder = sequence_folder(dest_folder, base, ver)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for tile, src in tiles:
            shutil.copy2(src, folder / f"{base}_{ver_str}.{tile}{ext}")
    except OSError as exc:
        log.warning("UDIM map copy failed for %s: %s", full_name, exc)
        discard_rendered_version(dest_folder, base, ext, ver, is_sequence=True)
        return None
    finalize_rendered_version(dest_folder, base, ext, ver, is_sequence=True,
                              pattern=f"{base}_{ver_str}.{UDIM_TOKEN}{ext}", user=user)
    try:
        log_publish(user, f"{base}_{ver_str}{ext}", project, dest_folder=dest_folder)
        append_log(dest_folder, base, ver_str,
                   (description + " " if description else "") + f"({len(tiles)} tuile(s) UDIM)", user)
    except Exception as exc:  # noqa: BLE001 - logging never fails a publish
        log.warning("UDIM publish logging failed (non-fatal): %s", exc)
    log.info("Published UDIM map %s %s (%d tiles)", base, ver_str, len(tiles))
    return folder


def convert_to_tx(files: list[Path], label: str = "") -> tuple[list[Path], list[str]]:
    """"Only .tx" publish: conform each exported map to a .tx in a temp folder.

    The .tx files are then published IN PLACE of the source images, so the publish
    folder holds only <base>_vNNN.tx + LAST.tx. Publishing the image then deleting it
    would break versioning (versions are counted per extension: the next .png publish
    would restart at v001 and overwrite the v001.tx). A map whose conform fails keeps
    its source image (warning), never lost. Non-image files pass through unchanged.
    """
    import tempfile

    from features.publisher.texture_conform import is_texture_source
    from flux_actions.runner import run_conform_texture_action
    from flux_actions.switch import conform_tx_colorconvert

    out_dir = Path(tempfile.mkdtemp(prefix="flux_tx_only_"))
    result: list[Path] = []
    warnings: list[str] = []
    for f in files:
        if not is_texture_source(f):
            result.append(f)
            continue
        tx = out_dir / f"{f.stem}.tx"
        try:
            run_conform_texture_action(f, out_dir=out_dir, colorconvert=conform_tx_colorconvert())
        except Exception as exc:  # noqa: BLE001 - a failed conform publishes the source instead
            log.warning("%s .tx conform failed for %s: %s", label, f.name, exc)
        if tx.is_file():
            result.append(tx)
        else:
            warnings.append(f"{f.name} : conversion .tx echouee, image source publiee a la place")
            result.append(f)
    return result, warnings


def publish_maps(files: list[Path], project_path: Path, project: str, prefix: list[str],
                 variante: str, description: str, user: str,
                 whole_name: bool = False) -> tuple[list[str], list[str]]:
    """Publish exported maps under ``<prefix>_<MAP>[_<VARIANTE>]``, one publish per map.

    Returns (published paths, warnings). A plain map goes through publish_file; the
    tiles of a UDIM map become one version folder.
    """
    from features.publisher.publish_core import publish_file

    published: list[str] = []
    warnings: list[str] = []
    for token, items in group_maps(files, whole_name, warnings).items():
        target = "_".join([*prefix, token, *([variante] if variante else [])]).upper()
        tiles = [(t, f) for t, f in items if t is not None]
        plain = [f for t, f in items if t is None]
        if tiles:
            if len({t for t, _ in tiles}) != len(tiles):
                warnings.append(f"{token} : meme tuile exportee deux fois (plusieurs texture sets ?), "
                                "une seule gardee par tuile")
                tiles = list({t: (t, f) for t, f in tiles}.values())
            dest = publish_udim_map(tiles, project_path, project, target, description, user)
            if dest is not None:
                published.append(str(dest))
        if plain:
            if len(plain) > 1:
                warnings.append(f"{token} : {len(plain)} fichiers pour la meme map, seul le dernier reste LAST")
            for f in plain:
                dest = publish_file(f, project_path, description, user, project, target)
                if dest is None:
                    log.warning("Map not published (unresolved name): %s", f.name)
                    continue
                published.append(str(dest))
    return published, warnings
