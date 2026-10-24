"""Personal notifications (retake 04): which activity events concern ONE artist.

Pure functions, no I/O: the router feeds them the project's events, the artist's
follow list (``production.favorites`` in User.json) and the project's production
document. Scope is always one project (no event of another project ever comes out).

Follow keys share the favorites list (``hooks/useFavorites.ts``):
    "<project>|<CLASS>/<NAME>|<TASK>[|<SUBTASK>]"   followed task (asset or shot)
    "<project>|<SEQ>/<SHOT>|*"                     followed shot (every task)

Reasons, strongest first: ``followed_shot``, ``favorite``, ``assigned``.
"""

from __future__ import annotations

from features.accounts.aliases import load_aliases, resolve_user
from features.production.reconcile import parse_publish_event

SHOT_WILDCARD = "*"
REASONS = ("followed_shot", "favorite", "assigned")


def shot_follow_key(project: str, seq: str, shot: str) -> str:
    return f"{project}|{seq.upper()}/{shot.upper()}|{SHOT_WILDCARD}"


def _split(key: str) -> tuple[str, str, str, str] | None:
    parts = str(key).split("|")
    if len(parts) < 3 or "/" not in parts[1]:
        return None
    return parts[0], parts[1].upper(), parts[2].upper(), (parts[3].upper() if len(parts) > 3 else "")


def followed_shots(favorites: list[str], project: str) -> list[tuple[str, str]]:
    """(SEQ, SHOT) the artist follows in *project*, in list order, no duplicates."""
    out: list[tuple[str, str]] = []
    for key in favorites or []:
        parts = _split(key)
        if parts and parts[0] == project and parts[2] == SHOT_WILDCARD:
            seq, _, shot = parts[1].partition("/")
            if (seq, shot) not in out:
                out.append((seq, shot))
    return out


def assignments(production: dict, user: str, aliases: dict[str, str] | None = None) -> set[tuple[str, str]]:
    """{(ENTITY, TOKEN)} of tasks assigned to *user*: ENTITY = "SEQ/SHOT" or "CLASS/NAME",
    TOKEN = the task name and each of its TYPE tokens (what a publish file carries).
    Stored assignee names go through the rename alias table."""
    table = load_aliases() if aliases is None else aliases
    who = str(resolve_user((user or "").strip(), table)).upper()
    if not who:
        return set()
    seqs = {s.get("id"): str(s.get("name", "")).upper() for s in production.get("sequences", [])}
    out: set[tuple[str, str]] = set()
    entities = [(e, f"{seqs.get(e.get('seq_id'), '')}/{str(e.get('name', '')).upper()}")
                for e in production.get("shots", [])]
    entities += [(e, f"{str(e.get('class', '')).upper()}/{str(e.get('name', '')).upper()}")
                 for e in production.get("assets", [])]
    for entity, ent_key in entities:
        mine = {k.split("|")[0].upper() for k, d in (entity.get("task_details") or {}).items()
                if isinstance(d, dict) and who in {str(resolve_user(a.strip(), table)).upper()
                                      for a in str(d.get("assignee") or "").split(",")}}
        if not mine:
            continue
        for task in entity.get("tasks") or []:
            name = str(task.get("name", "")).upper()
            if name in mine:
                out.add((ent_key, name))
                out.update((ent_key, str(t).upper()) for t in task.get("type_tokens") or [])
        out.update((ent_key, name) for name in mine)   # inherited / virtual tasks
    return out


def _event_target(event: dict) -> tuple[str, str, str, bool] | None:
    """(ENTITY, TASK, INSTANCE, is_shot) of an event's file, or None."""
    parsed = parse_publish_event(event)
    if not parsed:
        return None
    if parsed.get("is_shot"):
        entity = f"{parsed.get('SEQ', '')}/{parsed.get('SHOT', '')}"
    else:
        entity = f"{parsed.get('CLASS', '')}/{parsed.get('NAME', '')}"
    return entity.upper(), str(parsed.get("TASK", "")).upper(), str(parsed.get("INSTANCE", "")).upper(), \
        bool(parsed.get("is_shot"))


def reason_for(event: dict, *, project: str, favorites: list[str],
               assigned: set[tuple[str, str]]) -> str | None:
    """Why *event* concerns the artist, or None. Events of another project never do."""
    if event.get("project") != project:
        return None
    target = _event_target(event)
    if target is None:
        return None
    entity, task, instance, is_shot = target
    best: str | None = None
    for key in favorites or []:
        parts = _split(key)
        if not parts or parts[0] != project or parts[1] != entity:
            continue
        if parts[2] == SHOT_WILDCARD:
            if is_shot:
                return "followed_shot"
            continue
        if parts[2] == task and (not parts[3] or parts[3] == instance):
            best = "favorite"
    if best:
        return best
    if (entity, task) in assigned:
        return "assigned"
    return None


def _dedupe_key(event: dict, aliases: dict[str, str] | None = None) -> tuple:
    # A status change or a multi-file update logs several identical lines in the
    # same minute: one notification is enough.
    return (resolve_user(event.get("user"), aliases), event.get("action"), event.get("file"),
            event.get("date"), str(event.get("time", ""))[:5])


def personal_feed(events: list[dict], *, project: str, scope: str, favorites: list[str],
                  assigned: set[tuple[str, str]]) -> list[dict]:
    """Events of *project* annotated with ``reason``; scope "self" keeps only those
    with a reason, "global" keeps every event of the project. Newest first, deduplicated."""
    out: list[dict] = []
    seen: set[tuple] = set()
    table = load_aliases()
    for event in events:
        if event.get("project") != project:
            continue
        key = _dedupe_key(event, table)
        if key in seen:
            continue
        seen.add(key)
        reason = reason_for(event, project=project, favorites=favorites, assigned=assigned)
        if scope == "self" and reason is None:
            continue
        shown = {**event, "reason": reason}
        if "user" in shown:
            shown["user"] = resolve_user(shown["user"], table)
        out.append(shown)
    return out
