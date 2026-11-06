# nuke_publish.py — publish from Nuke like Houdini: act on the selected node,
# create a Write with the requested options, and render it into the FLUX layout.
#
# the maintainer's spec (V6 B1): "comme Houdini, tu exportes -> ça agit sur le node
# sélectionné et ça crée un Write aux options demandées". So FLUX resolves the
# versioned destination (same token logic as every publish), then asks the in-Nuke
# bridge to build a Write connected to the selected node, set its file + format
# options, execute it, and remove it. The bytes land directly in the publish
# folder, like Houdini's ROP cook (no separate copy step).
#
# The code builder is pure (unit-testable); only publish_from_nuke talks to Nuke.

from __future__ import annotations

import json
from pathlib import Path

from core.constants import DEFAULT_PADDING
from core.logger import get_logger
from dcc.nuke.client import nuke_client

log = get_logger(__name__)

# Nuke script formats save the whole comp (no Write node), everything else renders
# through a Write. file_type is inferred by Nuke from the extension, so we do not
# force it; the caller's options tune the format-specific knobs.
_SCENE_EXTS = {".nk", ".nknc"}

# Project default write colorspace (see .nuke/init.py: Write = "color_picking").
DEFAULT_WRITE_COLORSPACE = "color_picking"


def _norm_ext(extension: str) -> str:
    ext = extension.strip().lower()
    return ext if ext.startswith(".") else f".{ext}"


# ── output path (mirrors Houdini's build_rop_output_path) ─────────────────────

def build_nuke_output_path(
    project_path: Path | str,
    filename: str,
    extension: str,
    is_sequence: bool = False,
    frame_padding: int = 4,
) -> tuple[Path, int] | tuple[None, None]:
    """Resolve the versioned output path a Nuke Write should render to.

    Single file : dest/<base>_vNNN.ext  (immutable, LAST derived after the render)
    Sequence    : dest/<base>_vNNN/<base>_vNNN.%0Nd.ext  (Nuke printf frame token)
    Returns (path, version) or (None, None).
    """
    from features.folder_manager.naming_validator import get_base_name
    from features.publisher.publish_core import resolve_publish_path
    from features.publisher.publish_layout import (
        flat_version_path, reserve_version, sequence_folder,
    )

    project_path = Path(project_path)
    ext = _norm_ext(extension)
    full_name = f"{filename}{ext}"

    dest_folder = resolve_publish_path(project_path, full_name)
    if dest_folder is None:
        log.error("Cannot resolve publish path for: %s", full_name)
        return None, None
    dest_folder.mkdir(parents=True, exist_ok=True)

    base_name = get_base_name(full_name)
    ver = reserve_version(dest_folder, base_name, ext)

    if is_sequence:
        seq_folder = sequence_folder(dest_folder, base_name, ver)
        seq_folder.mkdir(parents=True, exist_ok=True)
        frame_token = f"%0{frame_padding}d"  # Nuke uses printf-style frame padding
        output_path = seq_folder / f"{seq_folder.name}.{frame_token}{ext}"
    else:
        output_path = flat_version_path(dest_folder, base_name, ver, ext)

    return output_path, ver


# ── Nuke code builders (pure) ─────────────────────────────────────────────────

def build_write_export_code(
    file_path: str,
    options: dict | None = None,
    first: int | None = None,
    last: int | None = None,
    node_name: str | None = None,
    colorspace: str = DEFAULT_WRITE_COLORSPACE,
) -> str:
    """Return Nuke Python that, on the selected node (or *node_name*), creates a
    Write with *options*, renders it to *file_path*, removes it, and sets
    ``result`` to the written path. Pure string builder (unit-testable)."""
    opts = dict(options or {})
    fp = json.dumps(str(file_path).replace("\\", "/"))
    cs = json.dumps(colorspace)
    src = (
        f"nuke.toNode({json.dumps(node_name)})"
        if node_name
        else "(nuke.selectedNodes() or [None])[0]"
    )
    lines = [
        f"_src = {src}",
        "if _src is None:",
        "    raise RuntimeError('Aucun node sélectionné dans Nuke')",
        f"_w = nuke.nodes.Write(inputs=[_src], file={fp})",
        f"_w['colorspace'].setValue({cs})",
    ]
    # Apply requested format options straight onto the Write knobs. Unknown or
    # unsettable knobs are skipped so a bad option never aborts the export.
    for key, value in opts.items():
        if key in ("colorspace", "file", "scope"):
            continue
        lines.append(f"try: _w[{json.dumps(key)}].setValue({json.dumps(value)})")
        lines.append("except Exception: pass")
    if first is not None and last is not None:
        lines.append(f"nuke.execute(_w, {int(first)}, {int(last)})")
    else:
        lines.append("_f = int(nuke.frame())")
        lines.append("nuke.execute(_w, _f, _f)")
    lines.append("nuke.delete(_w)")
    lines.append(f"result = {fp}")
    return "\n".join(lines)


def build_script_save_code(file_path: str) -> str:
    """Return Nuke Python that saves the whole comp script to *file_path*."""
    fp = json.dumps(str(file_path).replace("\\", "/"))
    return f"nuke.scriptSaveAs({fp}, overwrite=1)\nresult = {fp}"


# ── orchestration ─────────────────────────────────────────────────────────────

def publish_from_nuke(
    project: str,
    filename: str,
    extension: str,
    options: dict | None = None,
    is_sequence: bool = False,
    frame_range: tuple[int, int] | None = None,
    node_name: str | None = None,
    description: str = "",
    user: str = "unknown",
    colorspace: str | None = None,
) -> dict:
    """Publish from Nuke by rendering a Write into the FLUX layout.

    Returns {ok, path, version, version_str} or {ok: False, error}.
    """
    from features.activity.activity_writer import log_publish
    from features.folder_manager.naming_validator import format_version, get_base_name
    from features.publisher.modif_log import append_log
    from features.publisher.publish_core import resolve_publish_path
    from features.publisher.publish_layout import (
        discard_rendered_version, finalize_rendered_version,
    )
    from core.paths import get_project_path

    ext = _norm_ext(extension)
    project_path = get_project_path(project)
    if not project_path.exists():
        return {"ok": False, "error": f"Projet introuvable : {project}"}

    output_path, next_ver = build_nuke_output_path(project_path, filename, ext, is_sequence)
    if output_path is None:
        return {"ok": False, "error": f"Chemin de publication introuvable pour : {filename}{ext}"}

    full_name = f"{filename}{ext}"
    dest_folder = resolve_publish_path(project_path, full_name)
    base_name = get_base_name(full_name)

    # The Write renders straight into the reserved immutable version (ADR 0017).
    effective_ver = next_ver
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cs = colorspace or DEFAULT_WRITE_COLORSPACE
    if ext in _SCENE_EXTS:
        code = build_script_save_code(str(output_path))
    else:
        first = last = None
        if frame_range is not None:
            first, last = int(frame_range[0]), int(frame_range[1])
        elif is_sequence:
            return {"ok": False, "error": "Une séquence a besoin d'un frame range"}
        code = build_write_export_code(str(output_path), options, first, last, node_name, cs)

    res = nuke_client.run(code)
    if not res.get("ok"):
        discard_rendered_version(dest_folder, base_name, ext, effective_ver, is_sequence=is_sequence)
        return {"ok": False, "error": res.get("error", "Nuke run failed")}

    active = finalize_rendered_version(
        dest_folder, base_name, ext, effective_ver, is_sequence=is_sequence,
        pattern=output_path.name if is_sequence else None, user=user,
    ) or output_path

    ver_str = format_version(effective_ver, DEFAULT_PADDING)
    try:
        log_publish(user, f"{base_name}_{ver_str}{ext}", project, dest_folder=output_path.parent, soft="nuke")
        append_log(dest_folder, base_name, ver_str, description, user)
    except Exception as exc:  # logging must never fail a publish
        log.warning("Nuke publish logging failed (non-fatal): %s", exc)

    return {
        "ok": True,
        "path": str(output_path if is_sequence else active),
        "version": effective_ver,
        "version_str": ver_str,
        "is_sequence": is_sequence,
    }
