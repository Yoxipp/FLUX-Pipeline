# rights.py — TD / Team TD boxes of the Flows (01_ARCHITECTURE §7, 00_LOGIQUE §14 n°7, 23).
#
# Two keys at the root of USER/<NAME>/UserSettings/User.json (not in work_profile:
# applying the built-in "TD / Avance" interface profile must not tick rights):
#   flows_td        edit perso flows, dry runs, editor draft runs, cancel a run
#   flows_team_td   edit team / project flows, unlock, team nodes, pages, bridges, migrate
# team_td implies td. The user is the one of the local config, never the request.
#
# This is a guard against mistakes, NOT security: any artist can tick the boxes, FLUX
# has no roles and the X-Flux-Token only stops web pages. The only real barrier is the
# NTFS rights of CONFIG/extensions/ on the share (outside FLUX).

from __future__ import annotations

from typing import Any, Dict, Optional

from flux_flows.store import SCOPE_ORDER, FlowStoreError

TD_KEY = "flows_td"
TEAM_TD_KEY = "flows_team_td"

# Kinds of action of the 01 §7 table.
READ = "read"      # read, list, validate, see runs, run an active flow (page button, Publisher)
WRITE = "write"    # save, increment, revert, delete, activate, deactivate
DRAFT = "draft"    # dry run, editor draft run, cancel a run (td or the launcher)
ADMIN = "admin"    # team Python nodes, pages, bridges, unlock, migrate
ACTIONS = (READ, WRITE, DRAFT, ADMIN)

NOTE_FR = "Garde-fou contre l'erreur, pas une securite : n'importe qui peut cocher ces cases."
NOTE_EN = "A guard against mistakes, not security: anyone can tick these boxes."


class FlowRightsError(FlowStoreError):
    """The current user lacks the TD / Team TD box (HTTP 403)."""

    def __init__(self, level: str) -> None:
        label = "Team TD" if level == "team_td" else "TD"
        super().__init__(f"Case {label} requise", 403, {"required": level})


def rights_from_data(user: Optional[str], data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """{user, td, team_td} from a User.json blob; team_td implies td."""
    data = data if isinstance(data, dict) else {}
    team_td = data.get(TEAM_TD_KEY) is True
    return {"user": user, "td": team_td or data.get(TD_KEY) is True, "team_td": team_td}


def current_rights() -> Dict[str, Any]:
    """Rights of the user of the local config (no user = no box)."""
    from core import config
    from utils import user_utils

    user = config.get_current_user()
    return rights_from_data(user, user_utils.read_user_data(user) if user else None)


def required(action: str, scope: str) -> Optional[str]:
    """Box needed for *action* on *scope*: None, "td" or "team_td"."""
    if action not in ACTIONS:
        raise ValueError(f"action inconnue '{action}'")
    if scope not in SCOPE_ORDER:
        raise ValueError(f"portee inconnue '{scope}'")
    if action == READ:
        return None
    if action == DRAFT:
        return "td"
    if action == ADMIN:
        return "team_td"
    # WRITE: perso is the TD's own; shipped is written through its team copy (unlock).
    return "td" if scope == "perso" else "team_td"


def allowed(rights: Dict[str, Any], action: str, scope: str) -> bool:
    level = required(action, scope)
    return level is None or bool(rights.get(level))


def check(rights: Dict[str, Any], action: str, scope: str) -> None:
    """Raise FlowRightsError (403) when *rights* miss the box of *action* on *scope*."""
    level = required(action, scope)
    if level is not None and not rights.get(level):
        raise FlowRightsError(level)


def summary(rights: Dict[str, Any]) -> Dict[str, Any]:
    """Body of GET /flows/rights: the boxes, what they allow per scope, and the warning."""
    return {
        **rights,
        "can": {scope: {a: allowed(rights, a, scope) for a in (WRITE, DRAFT, ADMIN)} for scope in SCOPE_ORDER},
        "note_fr": NOTE_FR,
        "note_en": NOTE_EN,
    }
