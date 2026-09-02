# importer_resolve.py — token-based path resolution for the FLUX Importer HDA.
#
# Called by routers/dcc.py endpoints; no Houdini dependency.
# Uses the same resolution logic as publish_core so import paths always match
# what the publisher wrote.

from __future__ import annotations

import re
import time
from pathlib import Path

from core.constants import ACTIVE_VERSION_LABEL, DEFAULT_INSTANCE
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
    versions: set[int] = set()

    # published_files walks both the legacy flat files and the nested
    # <base>_<FMT>_{LAST,Vnnn}/ folders, so iters resolve under either layout.
    from features.publisher.publish_layout import published_files
    for p in published_files(folder):
        if _extract_ext(p) == ".json":
            continue
        _, ver = _extract_iter_stem(p.name)
        if not ver:
            continue
        if ver == ACTIVE_VERSION_LABEL:
            has_last = True
        elif _VERSION_RE.match(ver):
            versions.add(int(ver[1:]))

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

    effective_instance = instance.strip() if instance.strip() else DEFAULT_INSTANCE
    target_stem = f"{class_tok}_{type_tok}_{name_tok}_{effective_instance}_{iter_val}".upper()

    # published_files descends into the nested <base>_<FMT>_{LAST,Vnnn}/ folders
    # as well as the legacy flat files, so import resolves under either layout.
    from features.publisher.publish_layout import published_files
    for p in published_files(folder):
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


# ── path → token reverse lookup ───────────────────────────────────────────────

def path_to_tokens(project_path: Path, rel_parts: list[str]) -> dict:
    """Reverse-map filesystem path segments (relative to project root) to FLUX tokens.

    Args:
        rel_parts: path segments, e.g. ['assets', 'chara', 'MECHANT', 'rig']
                   The last segment is the clicked item (folder or file).

    Returns a dict with keys CLASS, TYPE, NAME, INSTANCE (empty string when not found).
    Longest-match wins so that a deep NAME path beats a shallow CLASS path.
    """
    tokens = load_tokens(project_path)

    # Build reverse maps path_str → token_key (skip templates containing '{')
    name_map: dict[str, str] = {
        v: k for k, v in tokens.get("NAME", {}).items() if "{" not in v
    }
    class_map: dict[str, str] = {
        v: k for k, v in tokens.get("CLASS", {}).items() if "{" not in v
    }

    # Reverse-map TYPE subpaths: "model/sculpt" → "SCULPT", "rig/rig" → "RIG", …
    # tokens["TYPE"] already contains DEFAULT_TYPE_TOKENS merged with any custom entries.
    type_by_subpath: dict[str, str] = {v: k for k, v in tokens.get("TYPE", {}).items()}

    result = {"CLASS": "", "TYPE": "", "NAME": "", "INSTANCE": ""}
    if not rel_parts:
        return result

    # Try NAME match first (more specific — includes the class subfolder)
    for name_path, name_tok in sorted(name_map.items(), key=lambda kv: -len(kv[0])):
        parts = [p for p in name_path.replace("\\", "/").split("/") if p]
        if rel_parts[: len(parts)] == parts:
            result["NAME"] = name_tok
            # Derive CLASS from the name_path prefix
            for cls_path, cls_tok in class_map.items():
                cp = [p for p in cls_path.replace("\\", "/").split("/") if p]
                if parts[: len(cp)] == cp:
                    result["CLASS"] = cls_tok
                    break
            result["TYPE"], result["INSTANCE"] = _extract_type_instance(
                rel_parts[len(parts):], type_by_subpath
            )
            return result

    # Fallback: CLASS match only
    for cls_path, cls_tok in sorted(class_map.items(), key=lambda kv: -len(kv[0])):
        parts = [p for p in cls_path.replace("\\", "/").split("/") if p]
        if rel_parts[: len(parts)] == parts:
            result["CLASS"] = cls_tok
            remaining = rel_parts[len(parts):]
            if remaining:
                result["NAME"] = remaining[0].upper()
            result["TYPE"], result["INSTANCE"] = _extract_type_instance(
                remaining[1:], type_by_subpath
            )
            return result

    return result


def _extract_type_instance(segs: list[str], type_by_subpath: dict[str, str]) -> tuple[str, str]:
    """Resolve (TYPE, INSTANCE) from path segments after the NAME root.

    Tries 2-segment match first (e.g. 'model'+'sculpt' → SCULPT),
    then 1-segment match (e.g. 'cloth' → CLOTH), then plain uppercase fallback.
    File-like segments (containing a dot) are never treated as instance or type.
    """
    if not segs:
        return "", ""

    if len(segs) >= 2:
        two = f"{segs[0]}/{segs[1]}"
        if two in type_by_subpath:
            # segs[2] is instance only if it looks like a folder (no extension)
            inst = segs[2].upper() if len(segs) > 2 and "." not in segs[2] else ""
            return type_by_subpath[two], inst

    one = segs[0]
    if "." in one:
        return "", ""
    type_tok = type_by_subpath.get(one, one.upper())
    inst = segs[1].upper() if len(segs) > 1 and "." not in segs[1] else ""
    return type_tok, inst


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
