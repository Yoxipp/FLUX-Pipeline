# publish_core.py — core publish pipeline: path resolution, version archiving, file copy.

from __future__ import annotations

from pathlib import Path

from core.logger import get_logger
from core.paths import ensure_dir
from features.activity.activity_writer import log_publish
from features.folder_manager.naming_validator import (
    format_version, get_base_name, parse_filename,
)
from features.folder_manager.tokens import get_path_for_token, load_tokens
from features.publisher.modif_log import append_log
from features.publisher.last_pointer import full_ext
from features.publisher.publish_layout import publish_into_layout

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
        # ADR 0019: the department of a shot is its TYPE (TYPE_SHOT tokens); projects
        # written before that carry it in their CLASS tokens.
        dept = parsed.get("TYPE") or parsed["CLASS"]
        class_rel = (get_path_for_token(tokens, "TYPE_SHOT", dept)
                     or get_path_for_token(tokens, "CLASS", dept))
        if class_rel is None:
            log.warning("Shot department token not found: %s", dept)
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


def explain_unresolved_publish(project_path: Path, filename: str) -> str:
    """Human readable (French, shown in the UI) reason why ``resolve_publish_path``
    returned None for *filename*. Read-only: it never changes the resolution."""
    parsed = parse_filename(filename)
    if parsed is None:
        return f"Nom de fichier non conforme aux tokens FLUX : {filename}"
    tokens = load_tokens(project_path)
    if parsed["is_shot"]:
        dept = parsed.get("TYPE") or parsed["CLASS"]
        if not dept:
            return f"Task du plan manquante dans {filename}"
        if (get_path_for_token(tokens, "TYPE_SHOT", dept) is None
                and get_path_for_token(tokens, "CLASS", dept) is None):
            return f"Task de plan inconnue : {dept}. Ajoute-la aux tokens TYPE_SHOT du projet."
        return f"Dossier de la task {dept} invalide pour {parsed['SEQ']} / {parsed['SHOT']}"
    if (get_path_for_token(tokens, "NAME", parsed["NAME"]) is None
            and get_path_for_token(tokens, "CLASS", parsed["CLASS"]) is None):
        return f"Catégorie inconnue : {parsed['CLASS']} (ni NAME {parsed['NAME']} ni CLASS dans les tokens)"
    return f"Chemin de publication introuvable pour {filename}"


# ── logical filename ─────────────────────────────────────────────────────────

def resolve_publish_filename(source_path: Path, target_name: str | None = None) -> str:
    """Return the logical FLUX filename to publish under.

    *target_name* : when the source file is NOT named with FLUX tokens (e.g. a
    local image ``Capture.png``), the caller passes the composed token name
    (``CHAR_REF_HERO_null``). The source then only provides the bytes and its
    extension; the destination is named from *target_name*. When omitted, the
    source filename itself must be a valid FLUX name (DCC exports already are).
    """
    if target_name:
        return target_name if Path(target_name).suffix else f"{target_name}{source_path.suffix}"
    return source_path.name


# ── copy half ──────────────────────────────────────────────────────────────────

def copy_publish(
    source_path: Path,
    dest_folder: Path,
    filename: str,
    description: str,
    user: str,
    project_name: str,
    soft: str = "",
) -> Path | None:
    """Archive the previous version and copy *source_path* into *dest_folder*.

    This is the copy half of a publish. It does NOT resolve anything: it consumes
    an already-resolved destination folder (the output of ``resolve_publish_path``
    / ``build_output_path``) instead of recomputing the path itself.

    Steps:
      1. Write the immutable <base>_vNNN.ext, then derive LAST (ADR 0017)
      2. Append entry to modif_logs.json
      3. Append event to activite.json

    *filename* is the logical FLUX name; it only supplies the base name for the
    archived/active files. *dest_folder* is where they land.

    Returns the LAST path (or the version file when LAST is a .link) on success,
    None on failure.
    """
    ensure_dir(dest_folder)

    base_name = get_base_name(filename)

    try:
        dest_path, new_ver = publish_into_layout(source_path, dest_folder, base_name, user=user)
    except OSError as e:
        log.error("File copy failed: %s", e)
        return None

    # modif log stays at the shared publish folder (spans all versions/formats)
    append_log(dest_folder, base_name, format_version(new_ver), description, user)
    # Log the VERSIONED name (not the _LAST alias) so the publish history shows each
    # distinct version; dest_path.parent is the publish folder for the "open folder" UX.
    versioned_name = f"{base_name}_{format_version(new_ver)}{full_ext(source_path.name)}"
    log_publish(user, versioned_name, project_name, dest_folder=dest_path.parent, soft=soft)

    log.info("Published %s → %s (v%03d)", filename, dest_path, new_ver)
    # ADR 0019: proxy layer + asset (component) refresh, both on the immutable version.
    from features.publisher.publish_layout import flat_version_path
    from features.publisher.usd_publish_hooks import after_usd_publish

    ext = full_ext(source_path.name)
    after_usd_publish(dest_folder, base_name, ext,
                      flat_version_path(dest_folder, base_name, new_ver, ext), user=user)
    return dest_path


# ── main publish ───────────────────────────────────────────────────────────────

def publish_file(
    source_path: Path,
    project_path: Path,
    description: str,
    user: str,
    project_name: str = "",
    target_name: str | None = None,
    soft: str = "",
) -> Path | None:
    """Publish *source_path* into the correct folder inside *project_path*.

    *soft* : the software that publishes (Flows OnPublish filter), empty = from the extension.

    Thin wrapper over the two halves of a publish:
      1. resolve  -> logical name + destination folder (no side effect)
      2. copy     -> archive previous version, copy, write logs

    *target_name* : see :func:`resolve_publish_filename`.

    Returns the destination LAST path on success, None on failure.
    """
    filename = resolve_publish_filename(source_path, target_name)
    if parse_filename(filename) is None:
        log.error("Unparseable filename: %s", filename)
        return None

    dest_folder = resolve_publish_path(project_path, filename)
    if dest_folder is None:
        log.error("Cannot resolve publish path for: %s", filename)
        return None

    return copy_publish(
        source_path,
        dest_folder,
        filename,
        description,
        user,
        project_name or project_path.name,
        soft=soft,
    )

