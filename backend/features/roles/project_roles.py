# project_roles.py - roles of the artists on one project (2026-10-24, ADR 0064).
#
# junior < artist < lead < supervisor, in <project>/_flux_setup/roles.json:
#   {"schema_version": 1, "created_by": "ADAM", "members": {"ADAM": "supervisor"},
#    "updated_by": "MILO", "updated_at": "<iso>"}
# The creator of a project is its supervisor; anyone not listed is an artist. A project
# created before roles (no roles.json) takes the studio's legacy_supervisors (studio.json).
#
# Who changes what: a lead sets junior / artist / lead on anyone who is not a supervisor;
# a supervisor sets anything, demoting another supervisor (or himself) included. The last
# supervisor can never be demoted. A project without any supervisor can be claimed once.
#
# No departments (2026-10-31, ADR 0085): who sees a TOOL page or a Team channel is the
# people / roles ticked on it. An old file's "departments" key is ignored, then dropped by
# the next role change.
#
# A guard against mistakes, not security: the user is the one of the local config, an
# account without password can be picked by anyone, and roles.json sits in the shared
# folder. Same trust model as the TD boxes of the Flows (flux_flows/rights.py).

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from core import config, paths, studio_config
from core.constants import JSON_ROLES
from core.json_manager import append_lock, read_json, write_json
from core.logger import get_logger
from core.project_setup import setup_path

log = get_logger(__name__)

SCHEMA_VERSION = 1
JUNIOR, ARTIST, LEAD, SUPERVISOR = "junior", "artist", "lead", "supervisor"
ROLES = (JUNIOR, ARTIST, LEAD, SUPERVISOR)
RANK = {role: i for i, role in enumerate(ROLES)}
DEFAULT_ROLE = ARTIST
LABELS = {JUNIOR: "Junior", ARTIST: "Artist", LEAD: "Lead", SUPERVISOR: "Supervisor"}

# Minimum role of each guarded action (matrix validated by 2026-10-24).
ACTIONS = {
    "edit_entity": ARTIST,       # archive, rename, edit a seq / shot record (range, casting...)
    "hard_delete": LEAD,         # permanent deletion (archives emptied)
    "farm_env": LEAD,            # locked farm environment screen (engine limits.config)
    "render_settings": LEAD,     # team render settings (render.json)
    "project_settings": LEAD,    # project.json, work profiles, studio environment
    "team_channels": LEAD,       # Team page: create / archive channels, call links, pinned messages (ADR 0077)
    "reset_password": LEAD,      # remove another artist's password
    "manage_roles": LEAD,        # junior / artist / lead (supervisors: see can_set_role)
    "rename_accounts": LEAD,     # rename another artist from first / last name (2026-10-30, ADR 0079)
    "manage_accounts": SUPERVISOR,  # delete another artist's account
    "delete_project": SUPERVISOR,
}
_LEAD_ASSIGNABLE = (JUNIOR, ARTIST, LEAD)


class RoleError(PermissionError):
    """The active user's role is too low for the action (HTTP 403, readable French message)."""


def roles_path(project_name: str) -> Path:
    return setup_path(paths.get_project_path(project_name), JSON_ROLES)


def _norm(name: str | None) -> str:
    return (name or "").strip().upper()


def _clean_members(raw) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {_norm(n): r for n, r in raw.items() if _norm(n) and r in RANK}


def _current_names(table: dict) -> dict:
    """*table* keyed by current artist names (renames, ADR 0079). The file is not rewritten
    here; the next role change saves the current names. A live name's own
    entry wins over the entry of an old name renamed into it."""
    from features.accounts import aliases

    try:
        table_aliases = aliases.load_aliases()
    except (OSError, RuntimeError):
        return table
    if not table_aliases:
        return table
    out = {aliases.resolve_user(n, table_aliases): v for n, v in table.items()
           if aliases.resolve_user(n, table_aliases) != n}
    out.update({n: v for n, v in table.items() if aliases.resolve_user(n, table_aliases) == n})
    return out


def read_roles(project_name: str) -> dict:
    """{created_by, members {NAME: role}, legacy}. Never raises.

    Names are the current ones: an artist renamed since keeps the role."""
    try:
        path = roles_path(project_name)
    except RuntimeError:
        return {"created_by": None, "members": {}, "legacy": True}
    raw = read_json(path) if path.is_file() else None
    if not isinstance(raw, dict):
        # Created before roles: the studio names its supervisors (empty by default).
        members = {_norm(name): SUPERVISOR for name in studio_config.legacy_supervisors() if _norm(name)}
        return {"created_by": None, "members": _current_names(members), "legacy": True}
    return {"created_by": _norm(raw.get("created_by")) or None,
            "members": _current_names(_clean_members(raw.get("members"))), "legacy": False}


def _write(project_name: str, doc: dict, actor: str | None) -> None:
    doc = {
        "schema_version": SCHEMA_VERSION,
        "created_by": doc.get("created_by"),
        "members": dict(sorted(doc["members"].items())),
        "updated_by": actor,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if not write_json(roles_path(project_name), doc):
        raise OSError(f"Ecriture de {JSON_ROLES} impossible")


def role_of(project_name: str, user: str | None, roles: dict | None = None) -> str | None:
    """Role of *user* on the project, None without a user."""
    user = _norm(user)
    if not user:
        return None
    members = (roles or read_roles(project_name))["members"]
    return members.get(user, DEFAULT_ROLE)


def _active(user: str | None) -> str:
    return _norm(user if user is not None else config.get_current_user())


def can(project_name: str, action: str, user: str | None = None, roles: dict | None = None) -> bool:
    """True when *user* (default: the active user) may do *action* on the project."""
    if action not in ACTIONS:
        raise ValueError(f"action inconnue '{action}'")
    role = role_of(project_name, _active(user), roles)
    return role is not None and RANK[role] >= RANK[ACTIONS[action]]


def require(project_name: str, action: str, user: str | None = None) -> None:
    """Raise RoleError when *user* (default: the active user) may not do *action*."""
    if can(project_name, action, user):
        return
    needed = LABELS[ACTIONS[action]]
    who = _active(user)
    if not who:
        raise RoleError(f"Connecte-toi a ton compte : role {needed} requis sur {project_name}")
    role = role_of(project_name, who)
    raise RoleError(f"Role {needed} requis sur {project_name} (tu es {LABELS[role]})")


def supervisors(roles: dict) -> list[str]:
    return sorted(n for n, r in roles["members"].items() if r == SUPERVISOR)


def assignable_roles(actor_role: str | None, target_role: str) -> tuple[str, ...]:
    """Roles the actor may give to a member who has *target_role* (empty: none)."""
    if actor_role == SUPERVISOR:
        return ROLES
    if actor_role == LEAD and target_role in _LEAD_ASSIGNABLE:
        return _LEAD_ASSIGNABLE
    return ()


def check_set_role(roles: dict, actor: str, target: str, new_role: str) -> None:
    """Raise RoleError / ValueError when *actor* may not give *new_role* to *target*."""
    if new_role not in RANK:
        raise ValueError(f"Role inconnu : {new_role!r} ({', '.join(ROLES)})")
    if not actor:
        raise RoleError("Connecte-toi a ton compte pour changer un role")
    actor_role = roles["members"].get(actor, DEFAULT_ROLE)
    target_role = roles["members"].get(target, DEFAULT_ROLE)
    if new_role not in assignable_roles(actor_role, target_role):
        if actor_role not in (LEAD, SUPERVISOR):
            raise RoleError(f"Role Lead requis pour changer un role (tu es {LABELS[actor_role]})")
        raise RoleError("Un Lead ne peut pas changer le role d'un Supervisor ni nommer Supervisor")
    if target_role == SUPERVISOR and new_role != SUPERVISOR and supervisors(roles) == [target]:
        raise RoleError(f"{target} est le dernier Supervisor du projet : nomme un autre Supervisor d'abord")


def set_role(project_name: str, target: str, new_role: str, actor: str | None = None) -> dict:
    """Give *new_role* to *target* (as *actor*, default the active user). Returns read_roles()."""
    from utils.user_utils import is_valid_user_name

    actor, target = _active(actor), _norm(target)
    if not is_valid_user_name(target):
        raise ValueError(f"Nom d'artiste invalide : {target!r}")
    path = roles_path(project_name)
    with append_lock(path):
        roles = read_roles(project_name)
        check_set_role(roles, actor, target, new_role)
        members = dict(roles["members"])
        members[target] = new_role
        _write(project_name, {"created_by": roles["created_by"], "members": members}, actor)
    log.info("Role of %s on %s set to %s by %s", target, project_name, new_role, actor)
    return read_roles(project_name)


def claim_supervisor(project_name: str, user: str | None = None) -> dict:
    """Become supervisor of a project that has none (old project, empty studio list)."""
    user = _active(user)
    if not user:
        raise RoleError("Connecte-toi a ton compte pour devenir Supervisor")
    path = roles_path(project_name)
    with append_lock(path):
        roles = read_roles(project_name)
        if supervisors(roles):
            raise RoleError(f"{project_name} a deja un Supervisor ({', '.join(supervisors(roles))})")
        members = dict(roles["members"])
        members[user] = SUPERVISOR
        _write(project_name, {"created_by": roles["created_by"], "members": members}, user)
    log.warning("%s claimed supervisor of %s (project had none)", user, project_name)
    return read_roles(project_name)


def init_project_roles(project_name: str, creator: str | None) -> None:
    """At project creation: the creator is its supervisor. No user = claimable later."""
    creator = _norm(creator)
    members = {creator: SUPERVISOR} if creator else {}
    _write(project_name, {"created_by": creator or None, "members": members}, creator or None)


def summary(project_name: str, users: list[str], user: str | None = None) -> dict:
    """Body of GET /roles/{project}: every artist with his role, and what the active user can do."""
    roles = read_roles(project_name)
    me = _active(user)
    my_role = role_of(project_name, me, roles)
    names = sorted({_norm(u) for u in users if _norm(u)} | set(roles["members"]))
    members = []
    for name in names:
        role = roles["members"].get(name, DEFAULT_ROLE)
        options = [r for r in assignable_roles(my_role, role)
                   if not (role == SUPERVISOR and r != SUPERVISOR and supervisors(roles) == [name])]
        members.append({"name": name, "role": role, "listed": name in roles["members"],
                        "assignable": options if me else []})
    return {
        "project": project_name,
        "roles": list(ROLES),
        "labels": LABELS,
        "default_role": DEFAULT_ROLE,
        "created_by": roles["created_by"],
        "legacy": roles["legacy"],
        "supervisors": supervisors(roles),
        "can_claim": bool(me) and not supervisors(roles),
        "me": {"user": me or None, "role": my_role,
               "can": {a: can(project_name, a, me, roles) for a in ACTIONS}},
        "members": members,
        "note_fr": "Garde-fou contre l'erreur, pas une securite : un compte sans mot de passe peut etre "
                   "choisi par n'importe qui.",
    }
