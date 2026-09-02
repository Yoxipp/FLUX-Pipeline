# publish_core.py — core publish pipeline: path resolution, version archiving, file copy.

from __future__ import annotations

import shutil
from pathlib import Path

from core.constants import ACTIVE_VERSION_LABEL, DEFAULT_PADDING
from core.logger import get_logger
from core.paths import ensure_dir
from features.activity.activity_writer import log_publish
from features.folder_manager.naming_validator import (
    format_version, get_base_name, parse_filename,
)
from features.folder_manager.tokens import get_path_for_token, load_tokens
from features.publisher.modif_log import append_log
from features.publisher.version_resolver import get_last_file, get_next_version

log = get_logger(__name__)


# ── path resolution ────────────────────────────────────────────────────────────

def resolve_publish_path(project_path: Path, filename: str) -> Path | None:
    """Return the destination folder for *filename* inside *project_path*.

    Asset:  project/<NAME_path>/<type_sub>/<instance>/
            type_sub comes from tokens["TYPE"] (defaults + project custom entries),
            falls back to TYPE.lower() for unknown types.
    Shot:   project/<CLASS_template{seq=SEQ, shot=SHOT}>/<instance>/
    Returns None if *filename* is unparseable or required tokens are missing.
    """
    parsed = parse_filename(filename)
    if parsed is None:
        log.warning("Cannot parse filename: %s", filename)
        return None

    tokens = load_tokens(project_path)

    instance = parsed["INSTANCE"].lower() if parsed["INSTANCE"] else "null"

    if parsed["is_shot"]:
        class_rel = get_path_for_token(tokens, "CLASS", parsed["CLASS"])
        if class_rel is None:
            log.warning("CLASS token not found: %s", parsed["CLASS"])
            return None
        try:
            rel = class_rel.format(seq=parsed["SEQ"], shot=parsed["SHOT"])
        except KeyError as e:
            log.warning("Template substitution failed for %r: %s", class_rel, e)
            return None
        return project_path / rel / instance

    # asset: NAME token gives asset root, TYPE maps to subfolder, then instance
    name_rel = get_path_for_token(tokens, "NAME", parsed["NAME"])
    if name_rel is None:
        # fallback: CLASS_path/NAME
        class_rel = get_path_for_token(tokens, "CLASS", parsed["CLASS"])
        if class_rel is None:
            log.warning("Neither NAME nor CLASS token found for: %s", filename)
            return None
        name_rel = f"{class_rel}/{parsed['NAME']}"

    type_sub = tokens.get("TYPE", {}).get(parsed["TYPE"]) or parsed["TYPE"].lower()
    return project_path / name_rel / type_sub / instance


# ── versioning ─────────────────────────────────────────────────────────────────

def rename_last_to_versioned(
    dest_folder: Path,
    base_name: str,
    next_version: int,
    padding: int = DEFAULT_PADDING,
) -> Path | None:
    """Rename the existing LAST file to a versioned name.

    Returns the new versioned path, or None if no LAST existed.
    """
    last_file = get_last_file(dest_folder, base_name)
    if last_file is None:
        return None

    version_str = format_version(next_version, padding)
    ext = last_file.suffix
    versioned_path = dest_folder / f"{base_name}_{version_str}{ext}"

    try:
        last_file.rename(versioned_path)
        log.debug("Renamed %s → %s", last_file.name, versioned_path.name)
        return versioned_path
    except OSError as e:
        log.error("Failed to rename LAST → versioned: %s", e)
        return None


# ── main publish ───────────────────────────────────────────────────────────────

def publish_file(
    source_path: Path,
    project_path: Path,
    description: str,
    user: str,
    project_name: str = "",
    target_name: str | None = None,
) -> Path | None:
    """Publish *source_path* into the correct folder inside *project_path*.

    Steps:
      1. Parse the logical filename → tokens
      2. Resolve destination folder from tokens.json
      3. Compute next version number
      4. Rename existing LAST → vXXX
      5. Copy source → dest as *_LAST.ext
      6. Append entry to modif_logs.json
      7. Append event to activite.json

    *target_name* : when the source file is NOT named with FLUX tokens (e.g. a
    local image ``Capture.png``), the caller passes the composed token name
    (``CHAR_REF_HERO_null``). The source then only provides the bytes and its
    extension; the destination is named from *target_name*. When omitted, the
    source filename itself must be a valid FLUX name (DCC exports already are).

    Returns the destination LAST path on success, None on failure.
    """
    if target_name:
        filename = target_name if Path(target_name).suffix else f"{target_name}{source_path.suffix}"
    else:
        filename = source_path.name
    parsed = parse_filename(filename)
    if parsed is None:
        log.error("Unparseable filename: %s", filename)
        return None

    dest_folder = resolve_publish_path(project_path, filename)
    if dest_folder is None:
        log.error("Cannot resolve publish path for: %s", filename)
        return None

    ensure_dir(dest_folder)

    base_name = get_base_name(filename)
    next_ver  = get_next_version(dest_folder, base_name)

    # If a LAST file exists, it gets archived as v{next_ver}; the new LAST is v{next_ver+1}.
    # If no LAST exists (first publish ever), the new LAST is v{next_ver} = v001.
    had_last = rename_last_to_versioned(dest_folder, base_name, next_ver) is not None
    new_ver  = next_ver + 1 if had_last else next_ver

    dest_name = f"{base_name}_{ACTIVE_VERSION_LABEL}{source_path.suffix}"
    dest_path = dest_folder / dest_name

    try:
        shutil.copy2(source_path, dest_path)
    except OSError as e:
        log.error("File copy failed: %s", e)
        return None

    append_log(dest_folder, base_name, format_version(new_ver), description, user)
    log_publish(user, dest_name, project_name or project_path.name, dest_folder=dest_folder)

    log.info("Published %s → %s (v%03d)", filename, dest_path, next_ver)
    return dest_path

