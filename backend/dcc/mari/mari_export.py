# mari_export.py — publish Mari channels into FLUX (V6 B7).
#
# Level 2: FLUX tells the in-app Mari bridge to export the current geo's channels to
# a temp dir, then ingests each map under FLUX naming and optionally conforms it to
# .tx (same texture pipeline as Substance Painter). The ingest + conform reuse the
# existing, tested pieces; only the bridge export is Mari-specific.

from __future__ import annotations

import tempfile
from pathlib import Path

from core.logger import get_logger
from dcc.substance_painter.substance_export import map_token_from_filename

log = get_logger(__name__)


def publish_mari(
    project: str,
    class_tok: str,
    task_tok: str,
    name_tok: str,
    instance: str = "null",
    file_format: str = "tif",
    conform_tx: bool = False,
    description: str = "",
    user: str = "unknown",
    channels: list[str] | None = None,
) -> dict:
    """Export Mari channels and ingest them into FLUX (one publish per channel)."""
    from core.paths import get_project_path
    from dcc.mari.client import mari_client

    project_path = get_project_path(project)
    if not project_path.exists():
        return {"ok": False, "error": f"Projet introuvable : {project}"}

    log.info("Mari publish: project=%s %s_%s_%s -> asking the bridge to export", project, class_tok, task_tok, name_tok)
    export_dir = Path(tempfile.mkdtemp(prefix="flux_mari_"))
    result = mari_client.export(str(export_dir), file_format, channels or None)
    if not result.get("ok"):
        log.warning("Mari export failed: %s", result.get("error"))
        return {"ok": False, "error": result.get("error", "Mari export failed")}

    from dcc.substance_painter.substance_export import _conform_published, _exported_files
    from dcc.texture_publish import publish_maps

    files = _exported_files(export_dir, result.get("files", []))
    if not files:
        return {"ok": False, "error": "Mari export produced no channels"}

    variante = instance.strip().upper() if instance.strip() and instance.strip().lower() != "null" else ""
    published, warnings = publish_maps(files, project_path, project, [class_tok, task_tok, name_tok],
                                       variante, description, user, whole_name=True)
    warnings = [f"non exporte : {e}" for e in result.get("errors") or []] + warnings
    for w in warnings:
        log.warning("Mari publish: %s", w)
    tx_paths = _conform_published(published, "Mari") if (conform_tx and published) else []

    if not published:
        return {"ok": False, "error": "No Mari channel could be published"}
    return {"ok": True, "published": published, "tx": tx_paths or None, "warnings": warnings}
