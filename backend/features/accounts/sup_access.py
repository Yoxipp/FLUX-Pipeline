# sup_access.py - a supervisor enters any account without its password, on his project only.
#
# Two names on a machine: the active user (whose rights apply) and the local identity (who
# really authenticated here, in the per-machine prefs). A supervisor of the active project
# enters another account: the active user changes, the identity does not, so he keeps his
# status and comes back without a password. His role is read from roles.json each time.
#
# The entry is bound to that project: role actions on another project are refused and the
# active project, the workspace or a new project cannot be changed until he leaves. Each
# entry is logged in <project>/_flux_setup/sup_access.jsonl. A safeguard like the password
# itself (ADR 0065, 0087): the prefs and the shared files can be edited by hand.

from __future__ import annotations

import json
from datetime import datetime, timezone

from core import config
from core.logger import get_logger
from features.roles import project_roles
from utils import project_utils, user_utils

log = get_logger(__name__)

IDENTITY_KEY = "local_identity"
ENTRY_KEY = "sup_entry"
JOURNAL_NAME = "sup_access.jsonl"


def _norm(name: object) -> str:
    return str(name or "").strip().upper()


def local_identity() -> str:
    """Who authenticated on this machine; before this feature, the active user."""
    stored = user_utils.follow_rename(_norm(config.get(IDENTITY_KEY)))
    if stored and user_utils.user_exists(stored):
        return stored
    return _norm(config.get_current_user())


def set_local_identity(user: str) -> None:
    """*user* authenticated here (password, or an account without one): no entry is left."""
    config.set(IDENTITY_KEY, _norm(user))
    config.set(ENTRY_KEY, None)


def forget() -> None:
    """First launch: nothing from a previous install may grant an access."""
    config.set(IDENTITY_KEY, None)
    config.set(ENTRY_KEY, None)


def current_entry() -> dict | None:
    """The running entry {project, user, by}, None when the active user is his own."""
    try:
        entry = config.get(ENTRY_KEY)
        active = _norm(config.get_current_user())
    except (RuntimeError, OSError):
        return None
    if not isinstance(entry, dict) or not entry.get("project") or _norm(entry.get("user")) != active:
        return None
    return {"project": str(entry["project"]), "user": active, "by": _norm(entry.get("by"))}


def refusal(project_name: str | None = None, user: str | None = None) -> str | None:
    """Why the running entry forbids acting outside its project, None when it does not."""
    entry = current_entry()
    if entry is None or (user is not None and _norm(user) != entry["user"]):
        return None
    if project_name is not None and project_name == entry["project"]:
        return None
    return (f"Compte de {entry['user']} ouvert par {entry['by']} pour le projet {entry['project']} "
            "seulement : reviens sur ton compte d'abord.")


def _active_project() -> str | None:
    try:
        return project_utils.get_current_project() or None
    except (RuntimeError, OSError):
        return None


def identity_is_supervisor() -> bool:
    """True when the local identity supervises the active project (role read now)."""
    project = _active_project()
    identity = local_identity()
    if not project or not identity:
        return False
    try:
        return project_roles.role_of(project, identity) == project_roles.SUPERVISOR
    except (RuntimeError, OSError, ValueError) as exc:
        log.warning("cannot read the roles of %s: %s", project, exc)
        return False


def is_free_entry(target: str, is_supervisor: bool | None = None) -> bool:
    """True when *target* opens without a password: his own account, or a supervisor's entry."""
    if _norm(target) == local_identity():
        return True
    return identity_is_supervisor() if is_supervisor is None else is_supervisor


def _journal(project: str, action: str, by: str, user: str) -> None:
    path = project_roles.roles_path(project).parent / JOURNAL_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "action": action, "by": by, "user": user, "project": project}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def enter_without_password(target: str) -> bool:
    """Apply a free entry to *target*. False when its password must be checked instead.

    An entry that cannot be logged does not happen: the password is asked.
    """
    target = _norm(target)
    identity = local_identity()
    if target == identity:
        entry = current_entry()
        if entry is not None:
            try:
                _journal(entry["project"], "leave", identity, entry["user"])
            except OSError as exc:
                log.warning("sup access journal not written: %s", exc)
        set_local_identity(identity)
        return True
    if not identity_is_supervisor():
        return False
    project = _active_project()
    try:
        _journal(project, "enter", identity, target)
    except OSError as exc:
        log.error("sup access refused, journal not written: %s", exc)
        return False
    config.set(IDENTITY_KEY, identity)
    config.set(ENTRY_KEY, {"project": project, "user": target, "by": identity})
    log.info("Supervisor %s entered the account of %s on %s", identity, target, project)
    return True


def follow_user_rename(old: str, new: str) -> None:
    """An artist was renamed on this machine: the identity and the entry follow."""
    if _norm(config.get(IDENTITY_KEY)) == old:
        config.set(IDENTITY_KEY, new)
    entry = config.get(ENTRY_KEY)
    if isinstance(entry, dict):
        patched = {**entry,
                   "user": new if _norm(entry.get("user")) == old else entry.get("user"),
                   "by": new if _norm(entry.get("by")) == old else entry.get("by")}
        if patched != entry:
            config.set(ENTRY_KEY, patched)
