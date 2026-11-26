# dm_actions.py - action buttons and menus under a bot DM (ADR 0091).
#
# A DM about ONE task / retake or ONE calendar proposal carries Discord message components:
#   task, retake      Valider (task status APPROVED), Refuser (RTK), menu "Donner a" (assignee)
#                     Valider / Refuser: project lead or supervisor only
#   calendar proposal Valider (accept), Refuser (decline), menu "Decaler" (+1, +2, +7, +14 days)
# No new state: the existing Production statuses (tracking STATUS_TOKENS) and calendar answers.
# A digest of several events, a mention and a publish get no buttons.
#
# A click reaches the bot host only (interactions come through its Gateway, no intent needed):
# the host writes the change with the existing functions (production_store, calendar_store),
# as the FLUX account linked to the clicking Discord account by /link, then the same side
# effects as the app (notify hooks, calendar ping back to the author).
#
# custom_id (100 chars max): "fx|<op>|<project hash>|<a>|<b>"
#   ok / no / give   a = entity id, b = task detail key   (give: the artist is the menu value)
#   acc / dec / post a = calendar item id                 (post: the days are the menu value)
# The project hash keeps a click on a DM of another project (same bot) from writing here.

from __future__ import annotations

import copy
import hashlib
from datetime import date, datetime, timedelta

from core.logger import get_logger
from features.notify import store
from features.notify.events import _clip

log = get_logger(__name__)

PREFIX = "fx"
SEP = "|"
MAX_ID = 100
MAX_OPTIONS = 25                       # Discord string select limit
POSTPONE_DAYS = (1, 2, 7, 14)
TASK_STATUS = {"ok": "APPROVED", "no": "RTK"}
CALENDAR_ACTION = {"acc": "accept", "dec": "decline", "post": "postpone"}
NOT_LINKED = "Ce compte Discord n'est pas lie a FLUX : tape /link."

# Discord component types / styles
_ROW, _BUTTON, _SELECT = 1, 2, 3
_GREEN, _RED = 3, 4


def project_key(project: str) -> str:
    return hashlib.sha1((project or "").upper().encode("utf-8")).hexdigest()[:8]


def make_id(op: str, project: str, a: str, b: str = "") -> str:
    return SEP.join((PREFIX, op, project_key(project), a, b))


def parse_id(custom_id: str) -> dict | None:
    parts = str(custom_id or "").split(SEP)
    if len(parts) != 5 or parts[0] != PREFIX or parts[1] not in (*TASK_STATUS, "give", *CALENDAR_ACTION):
        return None
    return {"op": parts[1], "project_key": parts[2], "a": parts[3], "b": parts[4]}


def _fits(*ids: str) -> bool:
    return all(len(i) <= MAX_ID for i in ids)


def _button(label: str, style: int, custom_id: str) -> dict:
    return {"type": _BUTTON, "style": style, "label": label, "custom_id": custom_id}


def _select(custom_id: str, placeholder: str, options: list[tuple[str, str]]) -> dict:
    return {"type": _SELECT, "custom_id": custom_id, "placeholder": placeholder, "min_values": 1, "max_values": 1,
            "options": [{"label": lbl[:100], "value": val[:100]} for lbl, val in options[:MAX_OPTIONS]]}


# ── components of a DM (sending side, any PC) ─────────────────────────────────

def components_for(events: list[dict], recipient: str) -> list[dict]:
    """Action rows for the DM of *recipient*; [] unless it holds one actionable event."""
    if len(events) != 1:
        return []
    event = events[0]
    try:
        if event.get("type") in ("task", "retake"):
            return _task_components(event)
        if event.get("type") == "calendar" and event.get("detail") == "proposal":
            return _calendar_components(event, recipient)
    except Exception as exc:  # noqa: BLE001 - no buttons is never an error
        log.warning("notify buttons skipped: %s", exc)
    return []


def _task_components(event: dict) -> list[dict]:
    ref = event.get("ref") or {}
    ent, key, project = str(ref.get("id") or ""), str(ref.get("task") or ""), event.get("project", "")
    if not ent or not key or SEP in ent + key:
        return []
    ok, no, give = (make_id(op, project, ent, key) for op in ("ok", "no", "give"))
    if not _fits(ok, no, give):
        return []
    from utils.user_utils import list_users
    artists = sorted(list_users(), key=str.lower)
    rows = [{"type": _ROW, "components": [_button("Valider", _GREEN, ok), _button("Refuser", _RED, no)]}]
    if artists:
        rows.append({"type": _ROW, "components": [_select(give, "Donner a...", [(a, a) for a in artists])]})
    return rows


def calendar_item_for(project: str, event: dict, recipient: str) -> dict | None:
    """The proposal *event* is about: proposed to *recipient* by the event author, same dates
    (and same title when the event carries it). The newest one when several match."""
    from features.accounts.aliases import same_user
    from features.calendar import calendar_store
    span = str(event.get("entity") or "")
    title = str(event.get("text") or "")
    found = []
    for item in calendar_store.load(project).get("items") or []:
        if not isinstance(item, dict) or item.get("status") != "proposed":
            continue
        item_span = item.get("start") if item.get("start") == item.get("end") else f"{item.get('start')} > {item.get('end')}"
        if span and item_span != span:
            continue
        if title and _clip(str(item.get("title") or "")) != title:     # the event text is the clipped title
            continue
        if same_user(str(item.get("owner") or ""), recipient) and same_user(str(item.get("created_by") or ""), event.get("author", "")):
            found.append(item)
    return max(found, key=lambda i: str(i.get("created_at") or "")) if found else None


def _calendar_components(event: dict, recipient: str) -> list[dict]:
    project = event.get("project", "")
    item = calendar_item_for(project, event, recipient)
    if not item or SEP in str(item.get("id")):
        return []
    acc, dec, post = (make_id(op, project, str(item["id"])) for op in ("acc", "dec", "post"))
    if not _fits(acc, dec, post):
        return []
    days = [(f"+{d} jour{'s' if d > 1 else ''}" if d < 7 else f"+{d // 7} semaine{'s' if d > 7 else ''}", str(d))
            for d in POSTPONE_DAYS]
    return [{"type": _ROW, "components": [_button("Valider", _GREEN, acc), _button("Refuser", _RED, dec)]},
            {"type": _ROW, "components": [_select(post, "Decaler...", days)]}]


# ── a click (bot host) ────────────────────────────────────────────────────────

def handle(project: str, discord_id: str, custom_id: str, values: list | None = None) -> tuple[str, bool]:
    """Apply a click. Returns (answer, done): done = the change is written (the DM loses its
    buttons and shows the answer); not done = an ephemeral answer, the buttons stay."""
    parsed = parse_id(custom_id)
    if parsed is None:
        return "Bouton inconnu.", False
    if parsed["project_key"] != project_key(project):
        return "Ce bouton appartient a un autre projet.", False
    user = store.user_for_discord(discord_id)
    if not user:
        return NOT_LINKED, False
    op, value = parsed["op"], str((values or [""])[0] or "")
    try:
        if op in TASK_STATUS or op == "give":
            return _task(project, user, op, parsed["a"], parsed["b"], value), True
        return _calendar(project, user, op, parsed["a"], value), True
    except (ValueError, PermissionError) as exc:      # CalendarError / CalendarForbidden included
        return f"FLUX a refuse : {exc}", False


def _entity(production: dict, ent_id: str) -> tuple[dict, str]:
    seqs = {s.get("id"): str(s.get("name", "")).upper() for s in production.get("sequences") or []}
    for shot in production.get("shots") or []:
        if shot.get("id") == ent_id:
            return shot, f"{seqs.get(shot.get('seq_id'), '')}/{str(shot.get('name', '')).upper()}"
    for asset in production.get("assets") or []:
        if asset.get("id") == ent_id:
            return asset, f"{str(asset.get('class', '')).upper()}/{str(asset.get('name', '')).upper()}"
    raise ValueError("element introuvable dans Production (supprime ou renomme ?)")


def _task(project: str, user: str, op: str, ent_id: str, key: str, value: str) -> str:
    from features.notify import hooks
    from features.production import production_store
    from features.roles import project_roles
    from utils.user_utils import list_users
    role = project_roles.role_of(project, user)
    if role is None:
        raise PermissionError("compte sans role dans ce projet")
    if op in TASK_STATUS and role not in (project_roles.LEAD, project_roles.SUPERVISOR):
        raise PermissionError("reserve au lead ou au superviseur du projet")
    production = production_store.load_production(project)
    previous = copy.deepcopy(production)
    entity, label = _entity(production, ent_id)
    details = entity.get("task_details") or {}
    stored = next((k for k in details if k.upper() == key.upper()), None)
    if stored is None:
        raise ValueError(f"tache {key} introuvable sur {label}")
    if op == "give":
        artist = next((u for u in list_users() if u.upper() == value.upper()), None)
        if not artist:
            raise ValueError(f"artiste inconnu : {value}")
        production_store.update_task_detail(entity, stored, {"assignee": artist})
        answer = f"Donne a {artist} par {user} : {label} {key}"
    else:
        production_store.update_task_detail(entity, stored, {"status": TASK_STATUS[op]})
        answer = f"{'Valide' if op == 'ok' else 'Refuse (retake)'} par {user} : {label} {key}"
    if not production_store.save_production(project, production):
        raise ValueError("ecriture de production.json impossible, reessaie")
    hooks.on_production(project, previous, production, user)     # new assignee notified, as in the app
    log.info("discord button %s on %s by %s", op, project, user)
    return answer


def _calendar(project: str, user: str, op: str, item_id: str, value: str) -> str:
    from features.accounts.aliases import same_user
    from features.calendar import calendar_store
    data = calendar_store.load(project)
    start = end = None
    if op == "post":
        try:
            days = int(value)
        except ValueError:
            raise ValueError("duree inconnue")
        if days not in POSTPONE_DAYS:
            raise ValueError("duree inconnue")
        current = next((i for i in data["items"] if i.get("id") == item_id), None)
        if current is None:
            raise ValueError("engagement introuvable")
        shift = timedelta(days=days)
        start = (date.fromisoformat(current["start"]) + shift).isoformat()
        end = (date.fromisoformat(current["end"]) + shift).isoformat()
    item = calendar_store.respond(data, item_id, user, CALENDAR_ACTION[op], start, end)
    calendar_store.save(project, data)
    span = item["start"] if item["start"] == item["end"] else f"{item['start']} > {item['end']}"
    words = {"acc": "a accepte", "dec": "a refuse", "post": "a decale puis accepte"}
    # Same ping back to the author as routers/team_calendar.respond.
    if item.get("created_by") and not same_user(item["created_by"], user):
        try:
            from features.activity.chat_manager import _now, _record_mentions
            d, t = _now()
            _record_mentions(user, f"cal_{datetime.now().strftime('%H%M%S%f')}",
                             f"@{item['created_by']} {words[op]} : {item['title']} ({span})", d, t, project,
                             notify_kind="calendar", notify_detail=CALENDAR_ACTION[op], notify_entity=span,
                             notify_text=item["title"])
        except Exception as exc:  # noqa: BLE001 - the answer is saved
            log.warning("calendar ping after a Discord button skipped: %s", exc)
    log.info("discord button %s on %s by %s", op, project, user)
    return f"{user} {words[op]} : {item['title']} ({span})"
