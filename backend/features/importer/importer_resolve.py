# importer_resolve.py — token-based path resolution for the FLUX Importer HDA.
#
# Called by routers/dcc.py endpoints; no Houdini dependency.
# Uses the same resolution logic as publish_core so import paths always match
# what the publisher wrote.

from __future__ import annotations

import re
import time
from pathlib import Path

from core.constants import ACTIVE_VERSION_LABEL
from core.logger import get_logger
from core.paths import get_projects_dir
from features.folder_manager.naming_validator import build_asset_filename
from features.folder_manager.tokens import load_tokens
from features.publisher.publish_core import resolve_publish_path

log = get_logger(__name__)

_VERSION_RE = re.compile(r"^v(\d+)$", re.IGNORECASE)

# ── backend-side TTL cache ────────────────────────────────────────────────────
_BCACHE: dict = {}
_BCACHE_TTL = 30.0  # seconds


def _bcached(key: str, fn, ttl: float = _BCACHE_TTL):
    now = time.monotonic()
    if key in _BCACHE:
        exp, val = _BCACHE[key]
        if now < exp:
            return val
    val = fn()
    _BCACHE[key] = (now + ttl, val)
    return val


# ── project listing ───────────────────────────────────────────────────────────

def get_project_list() -> list[str]:
    """Return names of all Flux projects found in the workspace."""
    return _bcached("projects", _scan_projects, ttl=20.0)


def _scan_projects() -> list[str]:
    try:
        return sorted(
            d.name for d in get_projects_dir().iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )
    except OSError:
        return []


# ── token query ───────────────────────────────────────────────────────────────

def get_import_tokens(project_path: Path) -> dict:
    """Return token sections needed to populate the HDA dropdowns."""
    key = f"tokens:{project_path}"
    return _bcached(key, lambda: _load_tokens(project_path))


def _load_tokens(project_path: Path) -> dict:
    tokens = load_tokens(project_path)
    return {k: tokens.get(k, {}) for k in ("CLASS", "TYPE", "NAME", "SEQ", "SHOT", "INSTANCE")}


# ── folder resolution ─────────────────────────────────────────────────────────

def _resolve_folder(
    project_path: Path,
    class_tok: str,
    type_tok: str,
    name_tok: str,
    instance: str,
) -> Path | None:
    """Return the pipeline folder for the given token combination.

    Uses build_asset_filename + resolve_publish_path so the result is always
    consistent with what the publisher wrote to disk.
    """
    dummy = build_asset_filename(class_tok, type_tok, name_tok, instance, ACTIVE_VERSION_LABEL, "dummy")
    return resolve_publish_path(project_path, dummy)


# ── iter scan ─────────────────────────────────────────────────────────────────

def _extract_ext(p: Path) -> str:
    if p.name.endswith(".bgeo.sc"):
        return ".bgeo.sc"
    return p.suffix.lower()


def _extract_iter_stem(filename: str) -> tuple[str, str]:
    """Return (base_without_iter, iter_label) for a filename stem."""
    if filename.endswith(".bgeo.sc"):
        stem = filename[: -len(".bgeo.sc")]
    else:
        stem = filename.rsplit(".", 1)[0]
    parts = stem.split("_")
    if not parts:
        return stem, ""
    ver = parts[-1].upper()
    base = "_".join(parts[:-1])
    if ver == ACTIVE_VERSION_LABEL or _VERSION_RE.match(ver):
        return base, ver
    return stem, ""


def get_available_iters(
    project_path: Path,
    class_tok: str,
    type_tok: str,
    name_tok: str,
    instance: str,
) -> list[str]:
    """Return sorted iteration labels for the given token combination.

    LAST is always first when present, then descending versions (v003, v002…).
    Falls back to [LAST] when the folder does not exist.
    """
    key = f"iters:{project_path}:{class_tok}:{type_tok}:{name_tok}:{instance}"
    return _bcached(key, lambda: _scan_iters(project_path, class_tok, type_tok, name_tok, instance), ttl=15.0)


def _scan_iters(
    project_path: Path,
    class_tok: str,
    type_tok: str,
    name_tok: str,
    instance: str,
) -> list[str]:
    folder = _resolve_folder(project_path, class_tok, type_tok, name_tok, instance)
    if folder is None or not folder.exists():
        return [ACTIVE_VERSION_LABEL]

    has_last = False
    versions: list[int] = []

    for p in folder.iterdir():
        if not p.is_file() or _extract_ext(p) == ".json":
            continue
        _, ver = _extract_iter_stem(p.name)
        if not ver:
            continue
        if ver == ACTIVE_VERSION_LABEL:
            has_last = True
        elif _VERSION_RE.match(ver):
            versions.append(int(ver[1:]))

    result: list[str] = []
    if has_last:
        result.append(ACTIVE_VERSION_LABEL)
    for n in sorted(versions, reverse=True):
        result.append(f"v{n:03d}")
    return result or [ACTIVE_VERSION_LABEL]


# ── path resolution ───────────────────────────────────────────────────────────

def resolve_import_path(
    project_path: Path,
    class_tok: str,
    type_tok: str,
    name_tok: str,
    instance: str,
    iter_val: str,
) -> dict:
    """Find the actual file on disk for the given token combination.

    Returns:
        ok      — whether a file was found
        path    — absolute path string, or None
        ext     — extension including leading dot
        exists  — True when the file exists on disk
        error   — description when ok is False
    """
    folder = _resolve_folder(project_path, class_tok, type_tok, name_tok, instance)
    if folder is None:
        return {"ok": False, "path": None, "ext": "", "exists": False,
                "error": "Cannot resolve pipeline path for given tokens"}

    if not folder.exists():
        return {"ok": False, "path": None, "ext": "", "exists": False,
                "error": f"Pipeline folder does not exist: {folder}"}

    target_stem = f"{class_tok}_{type_tok}_{name_tok}_{instance}_{iter_val}".upper()

    for p in folder.iterdir():
        if not p.is_file():
            continue
        ext = _extract_ext(p)
        if ext == ".json":
            continue
        if p.name.endswith(".bgeo.sc"):
            stem = p.name[: -len(".bgeo.sc")]
        else:
            stem = p.stem
        if stem.upper() == target_stem:
            return {"ok": True, "path": str(p), "ext": ext, "exists": True}

    return {"ok": False, "path": None, "ext": "", "exists": False,
            "error": f"File not found: {target_stem}.*"}


# ── file listing ──────────────────────────────────────────────────────────────

def list_import_files(
    project_path: Path,
    class_filter: str | None = None,
    name_filter: str | None = None,
    last_only: bool = True,
) -> list[dict]:
    """List pipeline files with basic metadata for the HDA file browser."""
    from features.importer.file_browser import list_files

    paths = list_files(
        project_path,
        class_filter=class_filter,
        name_filter=name_filter,
        last_only=last_only,
    )
    result = []
    for p in paths:
        ext = _extract_ext(p)
        result.append({
            "name":    p.name,
            "path":    str(p),
            "ext":     ext,
            "version": ACTIVE_VERSION_LABEL if f"_{ACTIVE_VERSION_LABEL}." in p.name else "",
        })
    return result
