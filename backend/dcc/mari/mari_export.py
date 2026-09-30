# mari_export.py — publish Mari channels into FLUX (V6 B7).
#
# Level 2: FLUX tells the in-app Mari bridge to export the current geo's channels to
# a temp dir, then ingests each map under FLUX naming and optionally conforms it to
# .tx (same texture pipeline as Substance Painter). The ingest + conform reuse the
# existing, tested pieces; only the bridge export is Mari-specific.

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from core.logger import get_logger

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
    channel_params: dict[str, dict] | None = None,
) -> dict:
    """Export Mari channels and ingest them into FLUX (one publish per channel).

    Mari writes each channel losslessly (tif 8 bits, exr float: faster than png too);
    FLUX then writes each map in its own format / bit depth / size (*channel_params*
    {channel: {"format", "bit_depth", "size"}}, missing = *file_format* at the channel's
    own depth and size)."""
    from core.paths import get_project_path
    from dcc.mari.client import mari_client

    project_path = get_project_path(project)
    if not project_path.exists():
        return {"ok": False, "error": f"Projet introuvable : {project}"}

    log.info("Mari publish: project=%s %s_%s_%s -> asking the bridge to export", project, class_tok, task_tok, name_tok)
    export_dir = Path(tempfile.mkdtemp(prefix="flux_mari_"))
    # Each channel's own format: Mari writes it directly when it holds the channel's
    # depth, FLUX then keeps the file as is (no re-encode of every tile).
    params = channel_params or {}
    formats = {"*": file_format}
    formats.update({c: str(p.get("format")) for c, p in params.items() if p.get("format")})
    sizes = {c: int(p["size"]) for c, p in params.items() if str(p.get("size") or "").isdigit()}
    t0 = time.monotonic()
    result = mari_client.export(str(export_dir), "auto", channels or None, formats, sizes)
    timings = [f"export Mari {time.monotonic() - t0:.0f} s"
               + (" (nodes FLUX Export)" if result.get("mode") == "nodes" else "")]
    if not result.get("ok"):
        log.warning("Mari export failed: %s", result.get("error"))
        return {"ok": False, "error": result.get("error", "Mari export failed")}

    from dcc.substance_painter.substance_export import _conform_published, _exported_files
    from dcc.texture_publish import publish_maps

    files = [f for f in _exported_files(export_dir, result.get("files", [])) if "$UDIM" not in f.name]
    if not files:
        return {"ok": False, "error": "Mari export produced no channels"}

    from dcc.texture_convert import convert_maps

    conv_dir = Path(tempfile.mkdtemp(prefix="flux_mari_maps_"))
    t0 = time.monotonic()
    files, conv_warnings = convert_maps(files, conv_dir, params, file_format,
                                        key_of=lambda f: f.name.split(".")[0])
    timings.append(f"conversion {time.monotonic() - t0:.0f} s")
    if not files:
        return {"ok": False, "error": "Aucune map convertie : " + " ; ".join(conv_warnings[:3])}

    variante = instance.strip().upper() if instance.strip() and instance.strip().lower() != "null" else ""
    t0 = time.monotonic()
    published, warnings = publish_maps(files, project_path, project, [class_tok, task_tok, name_tok],
                                       variante, description, user, whole_name=True)
    warnings = [f"Mari : {e}" for e in result.get("errors") or []] + conv_warnings + warnings
    for w in warnings:
        log.warning("Mari publish: %s", w)
    timings.append(f"copie {time.monotonic() - t0:.0f} s")
    t0 = time.monotonic()
    tx_paths = _conform_published(published, "Mari") if (conform_tx and published) else []
    if conform_tx:
        timings.append(f".tx {time.monotonic() - t0:.0f} s")
    log.info("Mari publish timings (%d file(s)): %s", len(files), ", ".join(timings))

    if not published:
        return {"ok": False, "error": "No Mari channel could be published"}
    return {"ok": True, "published": published, "tx": tx_paths or None, "warnings": warnings,
            "timings": ", ".join(timings)}
