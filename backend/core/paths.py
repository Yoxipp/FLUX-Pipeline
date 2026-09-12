# paths.py — single source of truth for all absolute path construction.
# Every other module MUST call these helpers instead of building paths manually.

from __future__ import annotations

import json
import sys
from pathlib import Path

# Lazily imported to avoid circular deps at module level
_installer_paths = None


def _get_installer_paths():
    global _installer_paths
    if _installer_paths is None:
        from installer import installer_paths as _ip
        _installer_paths = _ip
    return _installer_paths

from core.constants import (
    FLUX_ROOT_DIRS,
    FLUX_MARKER_FILENAME,
    JSON_ACTIVITY,
    JSON_CHAT,
    JSON_MENTIONS,
)

# ── Exe-relative bootstrap (config.json next to the exe) ─────────────────────

def _get_exe_dir() -> Path:
    """Return the directory containing the running exe (prod) or project root (dev)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    # dev: flux/core/paths.py → up 3 levels → project root
    return Path(__file__).resolve().parent.parent.parent


def get_config_json_path() -> Path:
    """Return the config.json path.

    Prod (frozen exe): %APPDATA%/FluxPipeline/config.json — user-writable even when
    the app is installed in Program Files (which is read-only without admin rights).
    Dev (non-frozen):  project root / config.json (existing behaviour).
    """
    if getattr(sys, "frozen", False):
        return _get_installer_paths().get_appdata_dir() / "config.json"
    return _get_exe_dir() / "config.json"


def get_prefs_path() -> Path:
    """Return the user prefs file.

    Prod (frozen exe): %APPDATA%/FluxPipeline/prefs.json
    Dev (non-frozen):  config.json next-to-project-root (existing behavior)
    """
    if getattr(sys, "frozen", False):
        return _get_installer_paths().get_prefs_path()
    return get_config_json_path()


def _read_config_json() -> dict:
    p = get_config_json_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_config_json(data: dict) -> None:
    p = get_config_json_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _update_config_json(key: str, value: str) -> None:
    data = _read_config_json()
    data[key] = value
    _write_config_json(data)


# ── FLUX_ROOT resolution ──────────────────────────────────────────────────────

def get_flux_root() -> Path | None:
    """Return the workspace path from config.json next to the exe, or None."""
    workspace = _read_config_json().get("workspace")
    return Path(workspace) if workspace else None


def set_flux_root(path: Path | str) -> None:
    """Persist workspace path to config.json next to the exe."""
    _update_config_json("workspace", str(Path(path)))


# ── Metadata backend selection (config.json, bootstrap) ──────────────────────
# Which persistence backend the repository factory builds. Read from config.json
# directly (NOT through the repository - the factory would recurse). Default
# "json" so nothing changes until the maintainer flips it after validating the migration.

def get_metadata_backend() -> str:
    """Return the configured metadata backend name ("json" by default)."""
    value = _read_config_json().get("metadata_backend")
    return str(value).strip().lower() if value else "json"


def get_sqlite_path() -> Path | None:
    """Return the configured SQLite base path, or None when unset."""
    value = _read_config_json().get("sqlite_path")
    return Path(value) if value else None


# ── Storage backend selection (config.json, big-files frontier) ──────────────
# Which StorageLocator the storage factory builds, and where the big files live.
# Read from config.json directly, like the metadata backend. Defaults keep today's
# behaviour: the local backend, rooted at the projects dir, until the maintainer sets a root.

def get_storage_backend() -> str:
    """Return the configured storage backend name ("local" by default)."""
    value = _read_config_json().get("storage_backend")
    return str(value).strip().lower() if value else "local"


def get_storage_root() -> Path | None:
    """Return the configured big-files root, or None to use the projects dir.

    None means "default to DOSSIER_PROJETS", so the resolved paths match today's
    layout. An explicit value (local dir, UNC NAS, synced cloud folder) redirects
    every resolved path under it, without touching any feature.
    """
    value = _read_config_json().get("storage_root")
    return Path(value) if value else None


# ── Install username (config.json, chosen at first launch) ───────────────────

def get_config_username() -> str | None:
    """Return the username stored in config.json, or None if not set."""
    return _read_config_json().get("username") or None


def set_config_username(name: str) -> None:
    """Persist the chosen username to config.json next to the exe."""
    _update_config_json("username", name)


# ── FLUX_ROOT subdirectories ──────────────────────────────────────────────────

def get_users_dir() -> Path:
    return _root_subdir("USER")


def get_projects_dir() -> Path:
    return _root_subdir("DOSSIER_PROJETS")


def get_config_dir() -> Path:
    return _root_subdir("CONFIG")


def get_update_dir() -> Path:
    return _root_subdir("FLUX_UPDATE")


def _root_subdir(name: str) -> Path:
    root = get_flux_root()
    if root is None:
        raise RuntimeError("FLUX_ROOT is not set. Run first-launch setup first.")
    return root / name


# ── User paths ────────────────────────────────────────────────────────────────

def get_user_dir(username: str) -> Path:
    return get_users_dir() / username


# ── Project paths ─────────────────────────────────────────────────────────────

def get_project_path(project_name: str) -> Path:
    return get_projects_dir() / project_name


def get_project_tokens_path(project_name: str) -> Path:
    from core.constants import JSON_TOKENS
    return get_project_path(project_name) / JSON_TOKENS


def get_project_production_path(project_name: str) -> Path:
    from core.constants import JSON_PRODUCTION
    return get_project_path(project_name) / JSON_PRODUCTION


# ── CONFIG / shared JSON paths ────────────────────────────────────────────────

def get_activity_path() -> Path:
    return get_config_dir() / JSON_ACTIVITY


def get_chat_path() -> Path:
    return get_config_dir() / JSON_CHAT


def get_mentions_path() -> Path:
    return get_config_dir() / JSON_MENTIONS


# ── Read-status side files (Phase 5) ─────────────────────────────────────────

def get_activity_read_path() -> Path:
    from core.constants import JSON_ACTIVITY_READ
    return get_config_dir() / JSON_ACTIVITY_READ


def get_mentions_read_path() -> Path:
    from core.constants import JSON_MENTIONS_READ
    return get_config_dir() / JSON_MENTIONS_READ


# ── Cold history archives (CONFIG/archive/, Phase 3) ─────────────────────────

def get_archive_dir() -> Path:
    from core.constants import ARCHIVE_DIRNAME
    return get_config_dir() / ARCHIVE_DIRNAME


def get_archive_path(stem: str, yyyymm: str) -> Path:
    """Return CONFIG/archive/<stem>_<YYYYMM>.json for a rotated month."""
    return get_archive_dir() / f"{stem}_{yyyymm}.json"


# ── FLUX_ROOT marker ──────────────────────────────────────────────────────────

def get_flux_marker_path(root: Path | None = None) -> Path:
    r = root or get_flux_root()
    if r is None:
        raise RuntimeError("FLUX_ROOT is not set.")
    return r / FLUX_MARKER_FILENAME


def is_flux_root(directory: Path) -> bool:
    """Return True if *directory* contains the .flux marker."""
    return (directory / FLUX_MARKER_FILENAME).exists()


# ── Path safety helpers ───────────────────────────────────────────────────────

def ensure_dir(path: Path) -> Path:
    """Create *path* (and parents) if it does not exist. Return *path*."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def path_exists_safe(path: Path) -> bool:
    """Return True if *path* exists, swallowing OS errors (slow network, etc.)."""
    try:
        return path.exists()
    except OSError:
        return False


def normalize_path(path: Path | str) -> Path:
    """Resolve to absolute, normalise separators (handles UNC and OneDrive paths)."""
    return Path(path).resolve()


def is_subpath(child: Path, parent: Path) -> bool:
    """Return True if *child* is strictly inside *parent*."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


# ── $FLUX portable token (priority n3) ────────────────────────────────────────
# A path stored as "$FLUX/DOSSIER_PROJETS/..." is machine-independent: each user
# resolves $FLUX to their own local pipeline root (get_flux_root). These helpers
# convert at the backend <-> DCC boundary; they NEVER change how absolutes are
# built on disk. Additive on purpose (paths.py is the single source of truth).

FLUX_TOKEN = "$FLUX"


def to_flux_token(path: Path | str, root: Path | None = None) -> str:
    """Return *path* as a portable "$FLUX/..." string when it sits under the
    local pipeline root, else the path unchanged (as a string).

    A path outside the root (external asset, temp, other drive) is left absolute
    on purpose: only pipeline paths get the token.
    """
    root = Path(root) if root else get_flux_root()
    p = Path(path)
    if root is None:
        return str(p)
    try:
        rel = normalize_path(p).relative_to(normalize_path(root))
    except (ValueError, OSError):
        return str(p)
    rel_posix = rel.as_posix()
    return FLUX_TOKEN if rel_posix == "." else f"{FLUX_TOKEN}/{rel_posix}"


def from_flux_token(token: Path | str, root: Path | None = None) -> Path:
    """Resolve a "$FLUX/..." token back to an absolute Path on this machine.

    Accepts "$FLUX" and "${FLUX}" forms. A value without the token is returned as
    a Path unchanged. Raises if the token is used but FLUX_ROOT is not set.
    """
    s = str(token)
    prefix = None
    for form in (FLUX_TOKEN, "${FLUX}"):
        if s == form or s.startswith(form + "/") or s.startswith(form + "\\"):
            prefix = form
            break
    if prefix is None:
        return Path(s)
    root = Path(root) if root else get_flux_root()
    if root is None:
        raise RuntimeError("FLUX_ROOT is not set; cannot resolve $FLUX token.")
    rest = s[len(prefix):].lstrip("/\\")
    return root / rest if rest else root

