# user_utils.py — user management wrappers over config.py and paths.py.

from __future__ import annotations

from core import config, paths
from core.logger import get_logger
from core.repository_factory import get_repository

log = get_logger(__name__)

# Metadata frontier (V5): the per-user settings blob (User.json) goes through the
# repository. It is a plain dict document, addressed by the user name (the resolver
# builds USER/<name>/UserSettings/User.json), routed get/set like tokens.json.
_COLLECTION = "user_settings"

# An artist name is a folder name (USER/<name>) that rename and delete act on, so
# anything that could address something else than a direct child of USER/ is refused.
_FORBIDDEN_NAME_CHARS = frozenset('<>:"/\\|?*')
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def is_valid_user_name(name: str) -> bool:
    """Return True if *name* is safe as the USER/<name> folder of an artist.

    Refuses empty names, ``.`` / ``..``, separators, characters Windows forbids,
    trailing dots or spaces (Windows strips them) and reserved device names.
    Accents and inner spaces stay allowed: existing artists may use them.
    """
    if not name or name != name.strip() or name in (".", ".."):
        return False
    if name.endswith("."):
        return False
    if any(c in _FORBIDDEN_NAME_CHARS or ord(c) < 32 for c in name):
        return False
    return name.split(".")[0].upper() not in _WINDOWS_RESERVED


def get_current_user() -> str | None:
    """Return the in-memory active user name, or None."""
    return config.get_current_user()


def set_current_user(name: str) -> None:
    """Set active user in memory, persist to config.json, ensure user dir exists."""
    name = name.strip().upper()   # artist names are always FULL UPPERCASE
    if not is_valid_user_name(name):
        raise ValueError(f"Nom d'artiste invalide : {name!r}")
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
    """Return True if FLUX_ROOT/USER/<name>/ exists (False for an unsafe name)."""
    if not is_valid_user_name(name):
        return False
    try:
        return paths.get_user_dir(name).exists()
    except (RuntimeError, OSError):
        return False


def create_user_dir(name: str) -> None:
    """Create FLUX_ROOT/USER/<name>/ if it does not exist."""
    if not is_valid_user_name(name):
        raise ValueError(f"Nom d'artiste invalide : {name!r}")
    paths.ensure_dir(paths.get_user_dir(name))
    log.debug("User dir ready for '%s'", name)


def rename_user(old: str, new: str) -> tuple[bool, str]:
    """Rename artist *old* -> *new* (renames FLUX_ROOT/USER/<old>).

    Names are stored FULL UPPERCASE. If *old* is the active user, the active
    user follows the rename. Returns (ok, message).
    """
    old = (old or "").strip().upper()
    new = (new or "").strip().upper()
    if not new:
        return False, "Le nom ne peut pas être vide."
    if new == old:
        return False, "Le nouveau nom est identique."
    if not is_valid_user_name(new):
        return False, f"Nom invalide : {new}"
    if not user_exists(old):
        return False, f"Artiste introuvable : {old}"
    if user_exists(new):
        return False, f"Un artiste nommé {new} existe déjà."
    try:
        paths.get_user_dir(old).rename(paths.get_user_dir(new))
    except OSError as exc:
        log.error("rename_user %s -> %s failed: %s", old, new, exc)
        return False, f"Échec du renommage : {exc}"
    if get_current_user() == old:
        config.set_current_user(new)
        config.set("username", new)
    log.info("Renamed artist '%s' -> '%s'", old, new)
    return True, f"{old} renommé en {new}"


def delete_user(name: str) -> tuple[bool, str]:
    """Delete artist *name* (removes FLUX_ROOT/USER/<name> and its data).

    Refuses to delete the currently active user (switch first). Returns (ok, message).
    """
    name = (name or "").strip().upper()
    if not user_exists(name):
        return False, f"Artiste introuvable : {name}"
    if get_current_user() == name:
        return False, "Impossible de supprimer l'artiste actif — change d'utilisateur d'abord."
    try:
        # force_rmtree clears read-only bits first (UserSettings files are often
        # read-only), otherwise Windows fails the delete with WinError 5.
        paths.force_rmtree(paths.get_user_dir(name))
    except OSError as exc:
        log.error("delete_user %s failed: %s", name, exc)
        return False, f"Échec de la suppression : {exc}"
    log.info("Deleted artist '%s'", name)
    return True, f"{name} supprimé"


# ── Per-user settings blob (favorites / recents / archived, …) ────────────────
# Stored at FLUX_ROOT/USER/<name>/UserSettings/User.json — on the shared drive,
# so a user's data follows them across machines and never leaks between users.
# The path is built by the "user_settings" resolver in repository_factory.

def read_user_data(name: str) -> dict:
    """Return the user's settings blob, or {} if none / unreadable."""
    try:
        data = get_repository().get(_COLLECTION, name)
        return data if isinstance(data, dict) else {}
    except (RuntimeError, OSError):
        return {}


def write_user_data(name: str, data: dict) -> bool:
    """Persist (overwrite) the user's settings blob. Returns True on success.

    The repository's set() writes atomically and creates the parent directory,
    so no explicit ensure_dir is needed (behaviour identical to the old path).
    """
    try:
        return get_repository().set(_COLLECTION, name, data)
    except (RuntimeError, OSError):
        return False


# ── Enabled DCCs (V8 U10) ─────────────────────────────────────────────────────
# Per-user list of launcher keys ("maya", "houdini", ...) stored in User.json under
# "enabled_dccs". Absent key = every DCC enabled (compat with existing users).
_ENABLED_DCCS_KEY = "enabled_dccs"


def get_enabled_dccs(name: str) -> list[str] | None:
    """Return the user's enabled DCC keys, or None when not set (= all enabled)."""
    value = read_user_data(name).get(_ENABLED_DCCS_KEY)
    if not isinstance(value, list):
        return None
    return [k for k in value if isinstance(k, str)]


def set_enabled_dccs(name: str, keys: list[str] | None, known: set[str]) -> list[str] | None:
    """Persist the enabled DCC keys (unknown keys dropped, sorted, deduplicated).

    None removes the preference (back to all enabled). Returns the stored value.
    """
    data = read_user_data(name)
    if keys is None:
        data.pop(_ENABLED_DCCS_KEY, None)
        stored = None
    else:
        wanted = {k for k in keys if isinstance(k, str)}
        stored = [k for k in sorted(known) if k in wanted]
        data[_ENABLED_DCCS_KEY] = stored
    if not write_user_data(name, data):
        raise OSError(f"cannot write user settings for '{name}'")
    return stored

