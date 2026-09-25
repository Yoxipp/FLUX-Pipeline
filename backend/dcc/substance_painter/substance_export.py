# substance_export.py — publish Substance Painter maps into FLUX (V6 B2).
#
# Level 2: FLUX tells the in-app bridge to export the project textures (an export
# preset) into a temp dir, then ingests each produced map under FLUX naming, and
# optionally conforms it to .tx (reusing the existing texture_conform brick) so
# Karma stops re-mipmapping at render time.
#
# The export-config builder + the map-token derivation are pure and unit-testable;
# the bridge call, the ingest (publish_file) and the conform (run_conform_texture_
# action) are the existing, already-tested pieces, wired here.

from __future__ import annotations

import tempfile
from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)


def build_export_config(
    export_path: str | Path,
    preset: str,
    file_format: str = "png",
    bit_depth: str = "8",
    texture_sets: list[str] | None = None,
    size: int | None = None,
    padding: str = "infinite",
    dilation: int = 16,
    maps: list[str] | None = None,
    map_params: dict[str, dict] | None = None,
    channels: list[dict] | None = None,
) -> dict:
    """Return a substance_painter.export config (pure, testable structure).

    *size*: output width in pixels (power of two), None = each texture set's own size.
    *padding*: Painter dilation algorithm (infinite, passthrough, transparent, color,
    diffusion); *dilation* in pixels for the non-infinite ones.
    *maps*: output maps of the preset to export (their fileName), None = all of them.
    *map_params*: {fileName: {"format", "bit_depth", "size"}} overriding the defaults per
    map (2026-09-25: format, bit depth and size chosen map by map)."""
    from dcc.texture_convert import pick_depth

    # A depth the format holds (no 32 bits in png, 2026-09-25).
    params: dict = {"fileFormat": file_format, "bitDepth": pick_depth(file_format, str(bit_depth)),
                    "paddingAlgorithm": padding or "infinite", "dithering": False}
    if params["paddingAlgorithm"] not in ("infinite", "passthrough"):
        params["dilationDistance"] = int(dilation)
    if size:
        params["sizeLog2"] = _size_log2(size)
    export_params: list[dict] = [{"parameters": params}]
    for fid, over in sorted((map_params or {}).items()):
        if maps and fid not in maps:
            continue
        p: dict = {}
        fmt = str(over.get("format") or "").lower().lstrip(".")
        if fmt and fmt != file_format:
            p["fileFormat"] = fmt
        if over.get("bit_depth") or (fmt and fmt != file_format):
            p["bitDepth"] = pick_depth(fmt or file_format, str(over.get("bit_depth") or bit_depth))
        if over.get("size"):
            p["sizeLog2"] = _size_log2(over["size"])
        if p:
            # Later entries win over the global one for the maps they filter.
            export_params.append({"filter": {"outputMaps": [fid]}, "parameters": p})
    if channels:
        # "Canaux du shader": one map per picked channel of the stack, whatever the preset
        # knows (coat, anisotropy, user channels...). Map id = its fileName.
        preset = CHANNEL_PRESET
    cfg: dict = {
        "exportPath": str(export_path).replace("\\", "/"),
        "exportShaderParams": False,
        "defaultExportPreset": preset,
        # Painter refuses the export ("impossible de resoudre l'algorithme de
        # dilatation") when parameters are given without a padding algorithm.
        "exportParameters": export_params,
    }
    if channels:
        cfg["exportPresets"] = [channel_preset(channels)]
    if texture_sets:
        cfg["exportList"] = [{"rootPath": ts} for ts in texture_sets]
        if maps:
            for entry in cfg["exportList"]:
                entry["filter"] = {"outputMaps": list(maps)}
    elif maps:
        # No set listed: the bridge lists every set, then applies this filter.
        cfg["fluxOutputMaps"] = list(maps)
    return cfg


CHANNEL_PRESET = "FLUX_channels"


def channel_map_id(channel: dict) -> str:
    """fileName of the map exported for one stack channel: $textureSet_<Label>."""
    import re

    label = re.sub(r"[^A-Za-z0-9]", "", str(channel.get("label") or channel["id"])) or channel["id"]
    return f"$textureSet_{label}"


def channel_preset(channels: list[dict]) -> dict:
    """An export preset with one map per channel: grey channels as L, colour ones as RGB."""
    maps = []
    for ch in channels:
        comps = ("L",) if ch.get("gray") else ("R", "G", "B")
        maps.append({
            "fileName": channel_map_id(ch),
            "channels": [{"destChannel": c, "srcChannel": c, "srcMapType": "documentMap",
                          "srcMapName": ch["id"]} for c in comps],
        })
    return {"name": CHANNEL_PRESET, "maps": maps}


def _size_log2(size) -> int:
    return max(7, min(13, int(size).bit_length() - 1))


def map_token_from_filename(filename: str) -> str:
    """Derive a FLUX instance token from a map file name.

    Painter names maps like ``TextureSet_BaseColor.png`` / ``..._Roughness.1001.png``.
    We take the last alpha segment before any UDIM/frame number as the map token.
    """
    from dcc.texture_publish import canonical_map_token, split_map_name

    return canonical_map_token(filename) or split_map_name(filename)[0]


def publish_painter(
    project: str,
    class_tok: str,
    task_tok: str,
    name_tok: str,
    instance: str = "null",
    preset: str = "PBR Metallic Roughness",
    file_format: str = "png",
    bit_depth: str = "8",
    conform_tx: bool = False,
    description: str = "",
    user: str = "unknown",
    texture_sets: list[str] | None = None,
    size: int | None = None,
    padding: str = "infinite",
    dilation: int = 16,
    maps: list[str] | None = None,
    map_params: dict[str, dict] | None = None,
    channels: list[dict] | None = None,
) -> dict:
    """Export Painter maps and ingest them into FLUX (one publish per map, so only the
    ticked maps get a texture folder).

    Returns {ok, published:[paths], tx:[paths]} or {ok: False, error}.
    """
    from core.paths import get_project_path
    from dcc.substance_painter.client import substance_client
    project_path = get_project_path(project)
    if not project_path.exists():
        return {"ok": False, "error": f"Projet introuvable : {project}"}

    log.info("Painter publish: project=%s %s_%s_%s -> asking the bridge to export", project, class_tok, task_tok, name_tok)
    export_dir = Path(tempfile.mkdtemp(prefix="flux_painter_"))
    config = build_export_config(export_dir, preset, file_format, bit_depth,
                                 texture_sets or None, size, padding, dilation,
                                 maps or None, map_params, channels or None)
    result = substance_client.export(config)
    if not result.get("ok"):
        log.warning("Painter export failed: %s", result.get("error"))
        return {"ok": False, "error": result.get("error", "Painter export failed")}

    files = _exported_files(export_dir, result.get("files", []))
    if not files:
        return {"ok": False, "error": "Painter export produced no maps"}

    from dcc.texture_publish import publish_maps

    variante = instance.strip().upper() if instance.strip() and instance.strip().lower() != "null" else ""
    published, warnings = publish_maps(files, project_path, project, [class_tok, task_tok, name_tok],
                                       variante, description, user)
    for w in warnings:
        log.warning("Painter publish: %s", w)
    if not published:
        return {"ok": False, "error": "No Painter map could be published"}
    tx_paths = _conform_published(published, "Painter") if conform_tx else []
    return {"ok": True, "published": published, "tx": tx_paths or None, "warnings": warnings}


def _exported_files(export_dir: Path, reported: list[str]) -> list[Path]:
    """Files really written in *export_dir* (the bridge may report a template such
    as ``..._BaseColor.$UDIM.tif``, not the tiles); the reported list as fallback."""
    on_disk = sorted(p for p in Path(export_dir).rglob("*") if p.is_file())
    return on_disk or [Path(f) for f in reported if Path(f).is_file()]


def _conform_published(published: list[str], label: str) -> list[str]:
    """.tx conform of each published map (a UDIM version folder as a <UDIM> pattern)."""
    from dcc.texture_publish import UDIM_TOKEN
    from flux_actions.runner import run_conform_texture_action

    tx_paths: list[str] = []
    for dest in published:
        p = Path(dest)
        source = p
        if p.is_dir():
            tiles = sorted(p.iterdir())
            if not tiles:
                continue
            first = tiles[0]
            stem = first.name.split(".")[0]
            source = p / f"{stem}.{UDIM_TOKEN}{first.suffix}"
        try:
            res = run_conform_texture_action(source, out_dir=p if p.is_dir() else p.parent)
            tx_paths.extend((res or {}).get("tx_paths") or [])
        except Exception as exc:  # noqa: BLE001 - conform must never fail a publish
            log.warning("%s .tx conform failed for %s: %s", label, p.name, exc)
    return tx_paths
