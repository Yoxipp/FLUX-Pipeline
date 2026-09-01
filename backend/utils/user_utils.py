# user_utils.py — user management wrappers over config.py and paths.py.

from __future__ import annotations

from pathlib import Path

from core import config, paths
from core.constants import JSON_USER_SETTINGS
from core.json_manager import read_json, write_json
from core.logger import get_logger

log = get_logger(__name__)


def get_current_user() -> str | None:
    """Return the in-memory active user name, or None."""
    return config.get_current_user()


def set_current_user(name: str) -> None:
    """Set active user in memory, persist to config.json, ensure user dir exists."""
    name = name.strip().upper()   # artist names are always FULL UPPERCASE
    config.set_current_user(name)
    config.set("username", name)
    try:
        create_user_dir(name)
    except RuntimeError:
        log.warning("FLUX_ROOT not set, skipping user dir creation for '%s'", name)


def list_users() -> list[str]:
    """Return sorted list of user names found in FLUX_ROOT/USER/."""
    try:
        users_dir = paths.get_users_dir()
        return sorted(d.name for d in users_dir.iterdir() if d.is_dir())
    except (RuntimeError, OSError):
        return []


def user_exists(name: str) -> bool:
    """Return True if FLUX_ROOT/USER/<name>/ exists."""
    try:
        return paths.get_user_dir(name).exists()
    except (RuntimeError, OSError):
        return False


def create_user_dir(name: str) -> None:
    """Create FLUX_ROOT/USER/<name>/ if it does not exist."""
    paths.ensure_dir(paths.get_user_dir(name))
    log.debug("User dir ready for '%s'", name)


# ── Per-user settings blob (favorites / recents / archived, …) ────────────────
# Stored at FLUX_ROOT/USER/<name>/UserSettings/User.json — on the shared drive,
# so a user's data follows them across machines and never leaks between users.

def _user_settings_path(name: str) -> Path:
    return paths.get_user_dir(name) / "UserSettings" / JSON_USER_SETTINGS


def read_user_data(name: str) -> dict:
    """Return the user's settings blob, or {} if none / unreadable."""
    try:
        data = read_json(_user_settings_path(name))
        return data if isinstance(data, dict) else {}
    except (RuntimeError, OSError):
        return {}


def write_user_data(name: str, data: dict) -> bool:
    """Persist (overwrite) the user's settings blob. Returns True on success."""
    try:
        path = _user_settings_path(name)
        paths.ensure_dir(path.parent)
        return write_json(path, data)
    except (RuntimeError, OSError):
        return False

