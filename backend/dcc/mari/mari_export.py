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
) -> dict:
    """Export Mari channels and ingest them into FLUX (one publish per channel)."""
    from core.paths import get_project_path
    from dcc.mari.client import mari_client
    from features.publisher.publish_core import publish_file

    project_path = get_project_path(project)
    if not project_path.exists():
        return {"ok": False, "error": f"Projet introuvable : {project}"}

    export_dir = Path(tempfile.mkdtemp(prefix="flux_mari_"))
    result = mari_client.export(str(export_dir), file_format)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "Mari export failed")}

    files = [Path(f) for f in result.get("files", [])]
    if not files:
        return {"ok": False, "error": "Mari export produced no channels"}

    published: list[str] = []
    tx_paths: list[str] = []
    variante = instance.strip().upper() if instance.strip() and instance.strip().lower() != "null" else ""
    for f in files:
        parts = [class_tok, task_tok, name_tok, map_token_from_filename(f.name)]
        if variante:
            parts.append(variante)
        target_name = "_".join(parts).upper()
        dest = publish_file(f, project_path, description, user, project, target_name)
        if dest is None:
            log.warning("Mari channel not published (unresolved name): %s", f.name)
            continue
        published.append(str(dest))
        if conform_tx:
            try:
                from flux_actions.runner import run_conform_texture_action
                res = run_conform_texture_action(Path(dest), out_dir=Path(dest).parent)
                tx = (res or {}).get("tx_paths") or []
                tx_paths.extend(tx)
            except Exception as exc:  # noqa: BLE001
                log.warning("Mari .tx conform failed for %s: %s", f.name, exc)

    if not published:
        return {"ok": False, "error": "No Mari channel could be published"}
    return {"ok": True, "published": published, "tx": tx_paths or None}
