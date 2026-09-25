# photoshop_export.py — publish the active Photoshop document into FLUX (V6 B6).
#
# Level 2, backend-driven COM: Photoshop is scriptable from OUTSIDE via COM
# (photoshop-python-api, MIT, Windows-only), so no in-app plugin is needed. FLUX
# resolves the versioned destination (same token logic as every publish) and tells
# Photoshop to save the active document there, in the requested format.
#
# The format -> save-options mapping is pure (unit-testable). The COM save is
# isolated in _save_active_document and lazy-imports the library, so the backend
# (and its tests) run fine on a machine without Photoshop or the lib.

from __future__ import annotations

from pathlib import Path

from core.constants import DEFAULT_PADDING
from core.logger import get_logger

log = get_logger(__name__)

# ext -> (photoshop.api save-options class name, kwargs). "asCopy" keeps the
# artist's open document untouched (we export a copy to the pipeline). Formats
# Photoshop can write natively; EXR needs a third-party plugin so it is omitted.
_SAVE_OPTIONS: dict[str, tuple[str, dict]] = {
    ".psd":  ("PhotoshopSaveOptions", {}),
    ".psb":  ("PhotoshopSaveOptions", {"maximizeCompatibility": True}),
    ".png":  ("PNGSaveOptions", {}),
    ".jpg":  ("JPEGSaveOptions", {"quality": 12}),
    ".jpeg": ("JPEGSaveOptions", {"quality": 12}),
    ".tif":  ("TiffSaveOptions", {}),
    ".tiff": ("TiffSaveOptions", {}),
    ".gif":  ("GIFSaveOptions", {}),
    ".bmp":  ("BMPSaveOptions", {}),
    ".tga":  ("TargaSaveOptions", {}),
}


def _norm_ext(extension: str) -> str:
    ext = extension.strip().lower()
    return ext if ext.startswith(".") else f".{ext}"


def supported_extensions() -> list[str]:
    """Return the file types the Photoshop publish can write."""
    return sorted(_SAVE_OPTIONS)


def save_options_for_ext(extension: str, options: dict | None = None) -> tuple[str, dict]:
    """Return (save-options class name, kwargs) for *extension*, merging *options*.

    Pure and testable: no Photoshop needed. Raises ValueError for an unsupported
    extension so the caller fails clearly instead of writing a broken file.
    """
    ext = _norm_ext(extension)
    if ext not in _SAVE_OPTIONS:
        raise ValueError(f"Photoshop cannot save {ext} (supported: {', '.join(supported_extensions())})")
    cls, defaults = _SAVE_OPTIONS[ext]
    kwargs = dict(defaults)
    # Only carry through options that are real fields for this format (the caller's
    # schema is per-format, so a stray key is ignored rather than passed to COM).
    for key, value in (options or {}).items():
        if key in defaults or key in ("quality", "maximizeCompatibility"):
            kwargs[key] = value
    return cls, kwargs


def _save_active_document(dest_path: str, extension: str, options: dict | None) -> dict:
    """Drive Photoshop over COM to save the active document to *dest_path*.

    Lazy-imports photoshop-python-api so the module loads without it. Returns
    {ok, version} or {ok: False, error}. Not unit-tested (needs Photoshop live)."""
    cls_name, kwargs = save_options_for_ext(extension, options)
    try:
        import photoshop.api as ps  # lazy: Windows + Photoshop only
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"photoshop-python-api indisponible: {exc}"}
    from dcc.photoshop.client import com_apartment
    try:
        with com_apartment():   # executor thread: COM must be initialised here
            app = ps.Application()
            doc = app.activeDocument
            opts_cls = getattr(ps, cls_name)
            opts = opts_cls()
            for key, value in kwargs.items():
                try:
                    setattr(opts, key, value)
                except Exception:  # noqa: BLE001 - unknown field never aborts the save
                    pass
            doc.saveAs(str(dest_path), opts, asCopy=True)
            version = str(getattr(app, "version", ""))
            del doc, opts, app
        return {"ok": True, "version": version}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Photoshop save failed: {exc}"}


def publish_photoshop(
    project: str,
    filename: str,
    extension: str,
    options: dict | None = None,
    description: str = "",
    user: str = "unknown",
) -> dict:
    """Save the active Photoshop document into the FLUX layout.

    Returns {ok, path, version, version_str} or {ok: False, error}.
    """
    from core.paths import get_project_path
    from features.activity.activity_writer import log_publish
    from features.folder_manager.naming_validator import format_version, get_base_name
    from features.publisher.modif_log import append_log
    from features.publisher.publish_core import resolve_publish_path
    from features.publisher.publish_layout import (
        discard_rendered_version, finalize_rendered_version, flat_version_path, reserve_version,
    )

    ext = _norm_ext(extension)
    try:
        save_options_for_ext(ext, options)  # validate the format up front
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    project_path = get_project_path(project)
    if not project_path.exists():
        return {"ok": False, "error": f"Projet introuvable : {project}"}

    full_name = f"{filename}{ext}"
    dest_folder = resolve_publish_path(project_path, full_name)
    if dest_folder is None:
        return {"ok": False, "error": f"Chemin de publication introuvable pour : {full_name}"}
    dest_folder.mkdir(parents=True, exist_ok=True)

    base_name = get_base_name(full_name)
    # Photoshop saves the immutable version, LAST is derived from it (ADR 0017).
    effective_ver = reserve_version(dest_folder, base_name, ext)
    version_path = flat_version_path(dest_folder, base_name, effective_ver, ext)

    saved = _save_active_document(str(version_path), ext, options)
    if not saved.get("ok"):
        discard_rendered_version(dest_folder, base_name, ext, effective_ver)
        return saved
    dest_path = finalize_rendered_version(dest_folder, base_name, ext, effective_ver,
                                          user=user) or version_path

    ver_str = format_version(effective_ver, DEFAULT_PADDING)
    try:
        log_publish(user, f"{base_name}_{ver_str}{ext}", project, dest_folder=dest_folder)
        append_log(dest_folder, base_name, ver_str, description, user)
    except Exception as exc:  # logging must never fail a publish
        log.warning("Photoshop publish logging failed (non-fatal): %s", exc)

    return {"ok": True, "path": str(dest_path), "version": effective_ver, "version_str": ver_str}
