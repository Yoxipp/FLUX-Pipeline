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
) -> dict:
    """Return a substance_painter.export config (pure, testable structure)."""
    cfg: dict = {
        "exportPath": str(export_path).replace("\\", "/"),
        "exportShaderParams": False,
        "defaultExportPreset": preset,
        "exportParameters": [
            {"parameters": {"fileFormat": file_format, "bitDepth": bit_depth}}
        ],
    }
    if texture_sets:
        cfg["exportList"] = [{"rootPath": ts} for ts in texture_sets]
    return cfg


def map_token_from_filename(filename: str) -> str:
    """Derive a FLUX instance token from a map file name.

    Painter names maps like ``TextureSet_BaseColor.png`` / ``..._Roughness.1001.png``.
    We take the last alpha segment before any UDIM/frame number as the map token.
    """
    stem = Path(filename).stem
    # drop a trailing UDIM/frame block (e.g. ".1001")
    parts = stem.split(".")
    core = parts[0]
    token = core.split("_")[-1] if "_" in core else core
    return token.upper() or "MAP"


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
) -> dict:
    """Export Painter maps and ingest them into FLUX (one publish per map).

    Returns {ok, published:[paths], tx:[paths]} or {ok: False, error}.
    """
    from core.paths import get_project_path
    from dcc.substance_painter.client import substance_client
    from features.publisher.publish_core import publish_file

    project_path = get_project_path(project)
    if not project_path.exists():
        return {"ok": False, "error": f"Projet introuvable : {project}"}

    log.info("Painter publish: project=%s %s_%s_%s -> asking the bridge to export", project, class_tok, task_tok, name_tok)
    export_dir = Path(tempfile.mkdtemp(prefix="flux_painter_"))
    config = build_export_config(export_dir, preset, file_format, bit_depth)
    result = substance_client.export(config)
    if not result.get("ok"):
        log.warning("Painter export failed: %s", result.get("error"))
        return {"ok": False, "error": result.get("error", "Painter export failed")}

    files = [Path(f) for f in result.get("files", [])]
    if not files:
        return {"ok": False, "error": "Painter export produced no maps"}

    published: list[str] = []
    tx_paths: list[str] = []
    variante = instance.strip().upper() if instance.strip() and instance.strip().lower() != "null" else ""
    for f in files:
        map_tok = map_token_from_filename(f.name)
        parts = [class_tok, task_tok, name_tok, map_tok]
        if variante:
            parts.append(variante)
        target_name = "_".join(parts).upper()
        dest = publish_file(f, project_path, description, user, project, target_name)
        if dest is None:
            log.warning("Painter map not published (unresolved name): %s", f.name)
            continue
        published.append(str(dest))
        if conform_tx:
            tx = _maybe_conform(Path(dest))
            if tx:
                tx_paths.extend(tx)

    if not published:
        return {"ok": False, "error": "No Painter map could be published"}
    return {"ok": True, "published": published, "tx": tx_paths or None}


def _maybe_conform(published_map: Path) -> list[str] | None:
    """Conform a published map to .tx via the existing texture_conform brick."""
    try:
        from flux_actions.runner import run_conform_texture_action
        res = run_conform_texture_action(published_map, out_dir=published_map.parent)
    except Exception as exc:  # noqa: BLE001 - conform must never fail a publish
        log.warning("Painter .tx conform failed for %s: %s", published_map.name, exc)
        return None
    return (res or {}).get("tx_paths") or None
