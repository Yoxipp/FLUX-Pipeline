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
_LAYERED_DIR_RE = re.compile(r"^(.+)_v(\d+)$", re.IGNORECASE)
# The asset's generated USD folder (component_auto.COMPONENT_SUBDIR); never a task.
COMPONENT_SUBDIR = "usd"

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


# ── instance scan ─────────────────────────────────────────────────────────────

def get_available_instances(
    project_path: Path,
    class_tok: str,
    type_tok: str,
    name_tok: str,
) -> list[str]:
    """Return the instance folders that actually exist on disk for these tokens.

    The INSTANCE token map often only lists 'null', but assets are published under
    real instance folders (e.g. .../rig/allbody/). Those folders are the direct
    children of the TYPE folder, so we list them from disk. DEFAULT_INSTANCE is kept
    first so a fresh node still resolves the default layout when it exists.
    """
    key = f"instances:{project_path}:{class_tok}:{type_tok}:{name_tok}"
    return _bcached(key, lambda: _scan_instances(project_path, class_tok, type_tok, name_tok), ttl=15.0)


def _scan_instances(project_path: Path, class_tok: str, type_tok: str, name_tok: str) -> list[str]:
    # Folder for a dummy instance → its parent is the TYPE folder holding instances.
    folder = _resolve_folder(project_path, class_tok, type_tok, name_tok, DEFAULT_INSTANCE)
    if folder is None:
        return [DEFAULT_INSTANCE]
    type_dir = folder.parent
    try:
        found = sorted(
            d.name for d in type_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )
    except OSError:
        return [DEFAULT_INSTANCE]
    # DEFAULT_INSTANCE first, then the real instance folders (deduped).
    result = [DEFAULT_INSTANCE]
    for name in found:
        if name != DEFAULT_INSTANCE:
            result.append(name)
    return result


# ── iter scan ─────────────────────────────────────────────────────────────────

def _extract_ext(p: Path) -> str:
    """Data extension, compound ones included; a LAST .link reports its target's."""
    from features.publisher.last_pointer import parse_published_name
    return parse_published_name(p.name)[1].lower()


# Preference order when several formats exist for the same asset — pick the one a
# DCC importer can actually load. USD (pipeline interchange) first, DCC-native
# scenes (.ma/.mb/.hip) last. Lower rank = preferred.
_IMPORT_EXT_ORDER = (
    ".usd", ".usda", ".usdc", ".usdz",
    ".abc", ".bgeo.sc", ".bgeo", ".geo", ".obj", ".fbx",
)


def _import_ext_rank(ext: str) -> int:
    ext = ext.lower()
    try:
        return _IMPORT_EXT_ORDER.index(ext)
    except ValueError:
        # Unknown / DCC-native (.ma, .mb, .hip…) sort after all importable ones.
        return len(_IMPORT_EXT_ORDER) + (1 if ext in (".ma", ".mb", ".hip", ".hiplc") else 0)


def _extract_iter_stem(filename: str) -> tuple[str, str]:
    """Return (base_without_iter, iter_label) for a filename stem."""
    from features.publisher.last_pointer import parse_published_name
    stem = parse_published_name(filename)[0]
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
    # Layered USD version folders (ADR 0017 U3c): <base>_vNNN/<base>.<usd ext>.
    for d in folder.iterdir():
        m = _LAYERED_DIR_RE.match(d.name)
        if m and d.is_dir() and any((d / f"{m.group(1)}{e}").is_file() for e in (".usd", ".usda", ".usdc")):
            versions.add(int(m.group(2)))

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
    iter_u = iter_val.upper()
    # Exact stem (no variante) and the prefix/suffix used to also match a file that
    # carries a VARIANTE token: build_asset_filename writes
    # CLASS_TYPE_NAME_INSTANCE[_VARIANTE]_ITER, and the HDA has no variante field,
    # so "CHAR_RIG_DOMINICK_ALLBODY_NORMAL_LAST" must resolve for these tokens.
    exact_stem = f"{class_tok}_{type_tok}_{name_tok}_{effective_instance}_{iter_u}".upper()
    prefix = f"{class_tok}_{type_tok}_{name_tok}_{effective_instance}_".upper()
    suffix = f"_{iter_u}"

    # published_files descends into the nested <base>_<FMT>_{LAST,Vnnn}/ folders
    # as well as the legacy flat files, so import resolves under either layout.
    from features.publisher.last_pointer import link_target, parse_published_name
    from features.publisher.publish_layout import published_files
    candidates: list[Path] = []
    for p in published_files(folder):
        stem, ext, role = parse_published_name(p.name)
        if ext.lower() == ".json":
            continue
        su = stem.upper()
        # Exact stem, or the same stem with a VARIANTE token in the middle
        # (e.g. CHAR_RIG_DOMINICK_ALLBODY_NORMAL_LAST).
        if su == exact_stem or (su.startswith(prefix) and su.endswith(suffix)):
            if role == "link":
                # LAST .link (ADR 0017): load the real vNNN file; a sequence target
                # folder is handled by the sequence fallback below.
                target = link_target(p)
                if target is not None and target.is_file():
                    candidates.append(target)
                continue
            candidates.append(p)

    if candidates:
        best = min(candidates, key=lambda p: _import_ext_rank(_extract_ext(p)))
        return {"ok": True, "path": str(best), "ext": _extract_ext(best), "exists": True}

    # Layered USD version folder (ADR 0017 U3c): <base>_vNNN/<base>.<usd ext>.
    layered = _resolve_layered_usd(folder, prefix, suffix, exact_stem)
    if layered is not None:
        return {"ok": True, "path": str(layered), "ext": layered.suffix.lower(), "exists": True}

    # No flat file matched — try the sequence layout. Nuke/Houdini publish a frame
    # sequence as a versioned SUBFOLDER <base>_<ITER>/ holding <base>_<ITER>.<frame>.<ext>
    # files (there is no _LAST sequence, so iter=LAST maps to the newest version).
    seq = _resolve_sequence(folder, prefix, suffix, exact_stem, iter_u)
    if seq is not None:
        return seq

    return {"ok": False, "path": None, "ext": "", "exists": False,
            "error": f"File not found: {exact_stem}.* (nor a variante, nor a sequence)"}


_FRAME_RE = re.compile(r"^\d+$")


def _resolve_layered_usd(folder: Path, prefix: str, suffix: str, exact_stem: str) -> Path | None:
    """Root layer of a layered USD version folder ``<base>_vNNN/<base>.<usd ext>``."""
    try:
        subdirs = sorted(d for d in folder.iterdir() if d.is_dir())
    except OSError:
        return None
    for d in subdirs:
        du = d.name.upper()
        if not (du == exact_stem or (du.startswith(prefix) and du.endswith(suffix))):
            continue
        base = d.name[: -len(suffix)]
        for ext in (".usd", ".usda", ".usdc"):
            root = d / f"{base}{ext}"
            if root.is_file():
                return root
    return None


def _resolve_sequence(
    folder: Path,
    prefix: str,
    suffix: str,
    exact_stem: str,
    iter_u: str,
) -> dict | None:
    """Resolve a frame-sequence version folder for the given tokens.

    Sequences live in a versioned subfolder ``<base>_<ITER>/`` next to the flat
    files, holding ``<base>_<ITER>.<frame>.<ext>`` frames. There is never a _LAST
    sequence folder, so ``iter=LAST`` maps to the highest ``vNNN`` version.

    Returns a resolve dict with ``is_sequence=True`` plus ``first``/``last`` and a
    ``frame_pattern`` (path with a printf ``%0Nd`` frame token). ``path`` stays a
    real first-frame file so callers that only read ``path`` still get a valid file.
    Returns None when no matching sequence folder exists.
    """
    try:
        subdirs = [d for d in folder.iterdir() if d.is_dir()]
    except OSError:
        return None

    # Keep the version folders whose name matches the token stem (exact or variante),
    # mapping each to its trailing ITER label (LAST / vNNN).
    versioned: list[tuple[str, Path]] = []
    for d in subdirs:
        du = d.name.upper()
        if du == exact_stem or (du.startswith(prefix) and du.endswith(suffix)):
            versioned.append((iter_u, d))
        elif du.startswith(prefix):
            iter_label = du[len(prefix):].split("_")[-1]
            if iter_label == ACTIVE_VERSION_LABEL or _VERSION_RE.match(iter_label):
                versioned.append((iter_label, d))
    if not versioned:
        return None

    if iter_u == ACTIVE_VERSION_LABEL:
        # LAST → the newest version (a real _LAST folder wins if one exists).
        last_dirs = [d for lbl, d in versioned if lbl == ACTIVE_VERSION_LABEL]
        if last_dirs:
            chosen = last_dirs[0]
        else:
            numbered = [(int(lbl[1:]), d) for lbl, d in versioned if _VERSION_RE.match(lbl)]
            if not numbered:
                return None
            chosen = max(numbered, key=lambda t: t[0])[1]
    else:
        matches = [d for lbl, d in versioned if lbl == iter_u]
        if not matches:
            return None
        chosen = matches[0]

    return _sequence_from_folder(chosen)


def _sequence_from_folder(seq_dir: Path) -> dict | None:
    """Build the sequence resolve dict from a version folder of frame files."""
    seq_stem = seq_dir.name
    prefix = seq_stem + "."
    frames: list[int] = []
    ext = ""
    for p in seq_dir.iterdir():
        if not p.is_file() or not p.name.startswith(prefix):
            continue
        remainder = p.name[len(prefix):]           # "<frame>.<ext...>"
        frame_str, dot, ext_rest = remainder.partition(".")
        if not dot or not _FRAME_RE.match(frame_str):
            continue
        frames.append(int(frame_str))
        ext = "." + ext_rest
    if not frames:
        return None

    frames.sort()
    # Padding comes from the on-disk frame token width (e.g. 0001 → 4) so the pattern
    # matches exactly what was written.
    pad_width = 4
    for p in seq_dir.iterdir():
        if p.is_file() and p.name.startswith(prefix):
            digits = p.name[len(prefix):].partition(".")[0]
            if digits.isdigit():
                pad_width = len(digits)
                break

    frame_token = f"%0{pad_width}d"
    frame_pattern = seq_dir / f"{seq_stem}.{frame_token}{ext}"
    first_file = seq_dir / f"{seq_stem}.{frames[0]:0{pad_width}d}{ext}"
    return {
        "ok": True,
        "path": str(first_file),
        "ext": ext,
        "exists": True,
        "is_sequence": True,
        "first": frames[0],
        "last": frames[-1],
        "frame_pattern": str(frame_pattern),
    }


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
    The asset's USD folder (<NAME>/usd, ADR 0018) is NOT a task: it holds the generated
    asset entry, so it resolves to no TYPE rather than to a made-up "USD" task.
    """
    if not segs:
        return "", ""
    if segs[0].lower() == COMPONENT_SUBDIR:
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

