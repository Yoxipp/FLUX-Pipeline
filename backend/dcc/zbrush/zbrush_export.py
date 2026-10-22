"""
FLUX — ZBrush export helpers.
Builds versioned pipeline paths from tokens, sends export commands to ZBrush
via ZBrushClient, and archives previous versions.

Supported formats: .ztl  .obj  .fbx
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from core.constants import DEFAULT_PADDING
from core.logger import get_logger
from core.paths import ensure_dir
from dcc.zbrush.client import zbrush_client
from features.activity.activity_writer import log_publish
from features.folder_manager.naming_validator import format_version, get_base_name
from features.publisher.modif_log import append_log
from features.publisher.publish_core import resolve_publish_path
from features.publisher.publish_layout import publish_into_layout

log = get_logger(__name__)

_SUPPORTED_EXTS: frozenset[str] = frozenset({".ztl", ".obj", ".fbx"})


def publish_zbrush(
    project_path: Path,
    filename: str,
    extension: str,
    export_options: dict[str, Any],
    description: str,
    user: str,
    project_name: str = "",
    keep_local: bool = False,
    local_dir: str | None = None,
) -> dict:
    """Full ZBrush publish pipeline.

    Steps:
      1. Validate extension
      2. Resolve destination folder from pipeline tokens
      3. Compute next version + archive existing LAST
      4. Send export command to ZBrush (writes directly to pipeline path)
      5. Optionally copy to a local directory (keep_local)
      6. Log activity

    Returns {"ok": bool, "path": str, "version": int, "version_str": str} on success.
    """
    ext = extension if extension.startswith(".") else f".{extension}"
    ext = ext.lower()

    if ext not in _SUPPORTED_EXTS:
        return {"ok": False, "error": f"Unsupported extension for ZBrush export: {ext}"}

    # ── 1. Resolve destination folder ─────────────────────────────────────────
    dest_folder = resolve_publish_path(project_path, filename)
    if dest_folder is None:
        return {"ok": False, "error": f"Cannot resolve pipeline path for: {filename}"}

    ensure_dir(dest_folder)

    # ── 2. Prepare paths ──────────────────────────────────────────────────────
    base_name = get_base_name(filename)

    # Export to a temp file so that ZBrush's set_next_filename never receives a
    # path that was just renamed away — which causes a spurious "unable to open"
    # dialog even when the export succeeds.
    temp_path = dest_folder / f"{base_name}_FLUX_TMP{ext}"
    temp_str  = str(temp_path)

    # ── 3. Export from ZBrush → temp ─────────────────────────────────────────
    if ext == ".ztl":
        result = zbrush_client.export_ztl(temp_str)
    elif ext == ".obj":
        result = zbrush_client.export_obj(temp_str, export_options)
    elif ext == ".fbx":
        result = zbrush_client.export_fbx(temp_str, export_options)
    else:
        return {"ok": False, "error": f"Unhandled extension: {ext}"}

    if not result.get("ok"):
        temp_path.unlink(missing_ok=True)
        err = result.get("error") or result.get("msg", "Unknown error from ZBrush")
        log.error("ZBrush export failed: %s", err)
        # Release ZBrush too, otherwise it stays frozen until the freeze timeout.
        try:
            zbrush_client.stop()
        except Exception:
            pass
        return {"ok": False, "error": err}

    # Release ZBrush from freeze ASAP, before any file I/O
    try:
        zbrush_client.stop()
    except Exception:
        pass

    # ── 4. Versioning (after export — temp path is safe to consume) ────────────
    # ADR 0017: immutable <base>_vNNN.ext, then LAST derived from it.
    try:
        dest_path, new_ver = publish_into_layout(temp_path, dest_folder, base_name, user=user)
    except OSError as exc:
        temp_path.unlink(missing_ok=True)
        log.error("Failed to place export in publish layout: %s", exc)
        return {"ok": False, "error": f"File move failed: {exc}"}
    temp_path.unlink(missing_ok=True)  # temp is disposable once copied into the layout

    ver_str   = format_version(new_ver, DEFAULT_PADDING)
    dest_name = dest_path.name

    # ── 5. Keep Local ─────────────────────────────────────────────────────────
    if keep_local and local_dir:
        local_path = Path(local_dir)
        if local_path.is_dir():
            try:
                shutil.copy2(dest_path, local_path / dest_name)
                log.info("Keep-local copy: %s", local_path / dest_name)
            except OSError as exc:
                log.warning("Keep-local copy failed: %s", exc)

    # ── 6. Logging ────────────────────────────────────────────────────────────
    try:
        append_log(
            folder_path=dest_folder,
            name=dest_name,
            version=ver_str,
            modification=description or "ZBrush publish",
            user=user,
        )
    except Exception as exc:
        log.warning("modif_log failed: %s", exc)

    try:
        # Log the versioned name (not the _LAST alias) so publish history shows versions.
        log_publish(
            user=user,
            filename=f"{base_name}_{ver_str}{dest_path.suffix}",
            project=project_name or project_path.name,
            dest_folder=dest_path.parent,
        )
    except Exception as exc:
        log.warning("activity log failed: %s", exc)

    log.info("ZBrush publish OK: %s (v%s)", dest_path, ver_str)
    return {
        "ok":          True,
        "path":        str(dest_path),
        "version":     new_ver,
        "version_str": ver_str,
    }
