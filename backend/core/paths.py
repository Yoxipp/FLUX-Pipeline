# paths.py — single source of truth for all absolute path construction.
# Every other module MUST call these helpers instead of building paths manually.

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

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


def _frozen_appdata_dir() -> Path:
    """Return %APPDATA%/FluxPipeline/, the user-writable data dir of the installed app."""
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "FluxPipeline"


def get_config_json_path() -> Path:
    """Return the config.json path.

    Prod (frozen exe): %APPDATA%/FluxPipeline/config.json — user-writable even when
    the app is installed in Program Files (which is read-only without admin rights).
    Dev (non-frozen):  project root / config.json (existing behaviour).
    """
    if getattr(sys, "frozen", False):
        return _frozen_appdata_dir() / "config.json"
    return _get_exe_dir() / "config.json"


def get_prefs_path() -> Path:
    """Return the user prefs file.

    Prod (frozen exe): %APPDATA%/FluxPipeline/prefs.json
    Dev (non-frozen):  config.json next-to-project-root (existing behavior)
    """
    if getattr(sys, "frozen", False):
        return _frozen_appdata_dir() / "prefs.json"
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
    # Atomic: a reader (the running backend, a test) must never see a half-written
    # file, which reads as {} and looks like "FLUX_ROOT is not set".
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


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


# Folder names of sync clients that replicate a folder between machines. A SQLite
# base in (or serving) such a folder is unsafe: the client copies a half-written
# base, and other machines never see the local writes.
_SYNCED_DIR_MARKERS = ("onedrive", "dropbox", "google drive", "googledrive")


def _is_remote_drive(path: Path) -> bool:
    """True when *path* sits on a mapped network drive (Windows only)."""
    if sys.platform != "win32":
        return False
    drive = path.drive
    if not drive or drive.startswith("\\\\"):
        return False
    try:
        import ctypes
        drive_remote = 4
        return ctypes.windll.kernel32.GetDriveTypeW(f"{drive}\\") == drive_remote
    except (AttributeError, OSError):
        return False


def shared_location_reason(path: Path | str | None) -> str | None:
    """Return why *path* is a synced or network location, or None when local.

    Used by the repository factory to refuse SQLite where several machines share
    the files (V8 U0). Name based, no read of the target: works for a base that
    does not exist yet.
    """
    if not path:
        return None
    raw = str(path)
    if raw.startswith("\\\\") or raw.startswith("//"):
        return "network share (UNC path)"
    p = Path(raw)
    for env in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        root = os.environ.get(env)
        if not root:
            continue
        try:
            p.resolve().relative_to(Path(root).resolve())
            return f"synced folder ({env})"
        except (ValueError, OSError):
            pass
    for part in p.parts:
        low = part.casefold()
        if any(marker in low for marker in _SYNCED_DIR_MARKERS):
            return f"synced folder ({part})"
    if _is_remote_drive(p):
        return "network drive"
    return None


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
    """Legacy workspace-wide team chat (before per-project chats). Read by nothing
    at runtime anymore; kept for the SQLite migration of old workspaces."""
    return get_config_dir() / JSON_CHAT


def get_project_chat_path(project_name: str) -> Path:
    """Team chat of one project: DOSSIER_PROJETS/<project>/teamChat.json."""
    return get_project_path(project_name) / JSON_CHAT


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


def _clear_readonly_and_retry(func, path) -> None:
    """rmtree error handler: drop the read-only bit, then retry the failed op.

    On Windows shutil.rmtree raises PermissionError (WinError 5, "Accès refusé") the
    moment it hits a read-only file or directory — common in archived publishes. We
    chmod +write and re-run the exact op that failed (unlink / rmdir).
    """
    import os as _os
    import stat as _stat
    try:
        _os.chmod(path, _stat.S_IWRITE)
        func(path)
    except OSError:
        # Genuinely locked/held elsewhere: let the final rmtree raise so the caller
        # surfaces a real error instead of silently leaving a half-deleted tree.
        pass


def force_rmtree(path: Path | str) -> None:
    """Recursively delete *path*, clearing read-only bits that block Windows.

    Plain shutil.rmtree fails with WinError 5 on read-only entries; this retries each
    failing entry after making it writable. No-op when the path does not exist.
    """
    import shutil as _shutil
    import sys as _sys
    p = Path(path)
    if not p.exists():
        return
    if _sys.version_info >= (3, 12):
        # onexc replaced the deprecated onerror in 3.12; signature is (func, path, exc).
        _shutil.rmtree(p, onexc=lambda func, pth, _exc: _clear_readonly_and_retry(func, pth))
    else:
        _shutil.rmtree(p, onerror=lambda func, pth, _exc: _clear_readonly_and_retry(func, pth))


def force_remove(path: Path | str) -> None:
    """Delete a file or a whole directory tree, clearing read-only bits (Windows-safe)."""
    import os as _os
    import stat as _stat
    p = Path(path)
    if p.is_dir():
        force_rmtree(p)
        return
    try:
        p.unlink()
    except PermissionError:
        _os.chmod(p, _stat.S_IWRITE)
        p.unlink()


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

