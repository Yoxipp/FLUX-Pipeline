# reconcile.py — auto-liaison publish ↔ (asset, task, subtask).
#
# Idempotent, pure functions. No IO. Callers pass the loaded production dict
# plus the list of publish events; reconcile enriches production in place (auto
# assets/tasks + mined subtasks) and returns publishes_by_task for the frontend.
#
# Filename nomenclature used here (target order):
#     CLASS_NAME_TASK_INSTANCE[_VARIANTE]_ITER.ext
# TASK is the token that maps to a Task's `type_tokens`.  INSTANCE feeds
# `known_subtasks`.  If the file cannot be parsed under this order, we fall
# back to the legacy `parse_filename` (CLASS_TYPE_NAME_INSTANCE order) so
# older publishes in activite.json still surface until the pipeline migration
# is finished.

from __future__ import annotations

import re

from core.logger import get_logger
from features.folder_manager.naming_validator import (
    ACTIVE_VERSION_LABEL,
    parse_filename as legacy_parse_filename,
)
from features.production import production_store as store
from features.production.archive import is_archived

log = get_logger(__name__)


_VERSION_RE = re.compile(r"^v(\d+)$", re.IGNORECASE)
_SEQ_RE = re.compile(r"^SEQ\d+$", re.IGNORECASE)
_SHOT_RE = re.compile(r"^SHOT\d+$", re.IGNORECASE)
_SEQ_NUM_RE  = re.compile(r"^SEQ(\d+)",  re.IGNORECASE)
_SHOT_NUM_RE = re.compile(r"^SHOT(\d+)", re.IGNORECASE)


def _parse_num(name: str, kind: str) -> int | None:
    rx = _SEQ_NUM_RE if kind == "SEQ" else _SHOT_NUM_RE
    m = rx.match(name or "")
    return int(m.group(1)) if m else None


def _insert_seq_by_number(production: dict, name: str) -> dict:
    """Create an auto sequence numerically placed among *other auto* siblings.

    User-placed sequences (``origin='user'``) keep their exact order value;
    the new auto seq slides in next to the first auto sibling with a
    strictly greater SEQ number (or after every auto if none is greater).
    Only auto orders shift — user positions never move.
    """
    n = _parse_num(name, "SEQ")
    return _insert_entity_numerically(
        production, "sequences", name, "SEQ", n,
        make=lambda: {
            "id": store.new_id("seq"), "name": name.upper(),
            "tasks": [], "assets": [], "notes": "", "origin": "auto",
        },
    )


def _insert_shot_by_number(production: dict, seq_id: str, name: str) -> dict:
    n = _parse_num(name, "SHOT")
    return _insert_entity_numerically(
        production, "shots", name, "SHOT", n,
        sibling_filter=lambda s: s.get("seq_id") == seq_id,
        make=lambda: {
            "id": store.new_id("shot"), "seq_id": seq_id, "name": name.upper(),
            "inherit_tasks": True, "inherit_assets": True,
            "tasks": [], "assets": [], "task_details": {}, "origin": "auto",
        },
    )


def _insert_entity_numerically(
    production: dict,
    key: str,
    name: str,
    prefix: str,
    num: int | None,
    make,
    sibling_filter=None,
) -> dict:
    entities = production.setdefault(key, [])
    siblings = [e for e in entities if (sibling_filter is None or sibling_filter(e))]
    if num is None or not siblings:
        # No numeric hint or empty list: append at the end.
        pos = max((e.get("order", 0) for e in siblings), default=-1) + 1
        obj = make(); obj["order"] = pos
        entities.append(obj)
        return obj
    # Position among AUTO siblings only, using order as the ranking axis.
    autos = sorted(
        [e for e in siblings if (e.get("origin") or "user") == "auto"],
        key=lambda e: e.get("order", 0),
    )
    greater = next(
        (a for a in autos if (_parse_num(a.get("name", ""), prefix) or 10**9) > num),
        None,
    )
    if greater is not None:
        pos = greater.get("order", 0)
    else:
        # No auto with a greater number → place after the last auto (if any),
        # else at the very end.
        pos = (autos[-1].get("order", -1) + 1) if autos else \
              max((e.get("order", 0) for e in siblings), default=-1) + 1
    sibling_ids = {e["id"] for e in siblings}
    for e in entities:
        if e["id"] in sibling_ids and e.get("order", 0) >= pos:
            e["order"] = e.get("order", 0) + 1
    obj = make(); obj["order"] = pos
    entities.append(obj)
    return obj


# ── filename parsing (new order) ─────────────────────────────────────────────

def parse_flux_filename(filename: str) -> dict | None:
    """Parse a filename in the new nomenclature.

    Asset: CLASS_NAME_TASK_INSTANCE[_VARIANTE]_ITER.ext
    Shot:  CLASS_SEQ###_SHOT###_INSTANCE[_VARIANTE]_ITER.ext  (unchanged)

    Returns dict with keys CLASS/NAME/TASK/INSTANCE/VARIANTE/ITER/extension/is_shot,
    or None if unparseable.
    """
    if not filename:
        return None
    stem, _, ext = filename.rpartition(".")
    if not stem:
        stem = filename
        ext = ""

    parts = stem.split("_")
    if not parts or not parts[0]:
        return None

    has_iter = bool(_VERSION_RE.match(parts[-1])) or parts[-1].upper() == ACTIVE_VERSION_LABEL
    iter_val = parts[-1].upper() if has_iter else ""
    core = parts[:-1] if has_iter else list(parts)

    # shot, current form (ADR 0019): SEQ###_SHOT###_TASK[_VARIANTE]
    if core and _SEQ_RE.match(core[0]):
        dept = core[2].upper() if len(core) > 2 else ""
        return {
            "CLASS":     dept,
            "SEQ":       core[0].upper(),
            "SHOT":      core[1].upper() if len(core) > 1 else "",
            "INSTANCE":  core[3].upper() if len(core) > 3 else "",
            "VARIANTE":  core[4].upper() if len(core) > 4 else "",
            "TASK":      dept,
            "NAME":      "",
            "ITER":      iter_val,
            "extension": ext,
            "is_shot":   True,
        }

    # shot, legacy form: CLASS_SEQ###_SHOT###_INSTANCE[_VARIANTE]
    if len(core) >= 2 and _SEQ_RE.match(core[1]):
        return {
            "CLASS":     core[0].upper(),
            "SEQ":       core[1].upper(),
            "SHOT":      core[2].upper() if len(core) > 2 else "",
            "INSTANCE":  core[3].upper() if len(core) > 3 else "",
            "VARIANTE":  core[4].upper() if len(core) > 4 else "",
            "TASK":      core[0].upper(),
            "NAME":      "",
            "ITER":      iter_val,
            "extension": ext,
            "is_shot":   True,
        }

    # asset: CLASS_NAME_TASK_INSTANCE[_VARIANTE]
    if len(core) < 3:
        return None
    return {
        "CLASS":     core[0].upper(),
        "NAME":      core[1].upper(),
        "TASK":      core[2].upper(),
        "INSTANCE":  core[3].upper() if len(core) > 3 else "",
        "VARIANTE":  core[4].upper() if len(core) > 4 else "",
        "SEQ":       "",
        "SHOT":      "",
        "ITER":      iter_val,
        "extension": ext,
        "is_shot":   False,
    }


def _legacy_to_new(parsed: dict) -> dict:
    """Adapt the legacy CLASS_TYPE_NAME_INSTANCE parse into the new key layout."""
    return {
        "CLASS":     (parsed.get("CLASS") or "").upper(),
        "NAME":      (parsed.get("NAME") or "").upper(),
        "TASK":      (parsed.get("TYPE") or "").upper(),
        "INSTANCE":  (parsed.get("INSTANCE") or "").upper(),
        "VARIANTE":  (parsed.get("VARIANTE") or "").upper(),
        "SEQ":       (parsed.get("SEQ") or "").upper(),
        "SHOT":      (parsed.get("SHOT") or "").upper(),
        "ITER":      (parsed.get("ITER") or "").upper(),
        "extension": parsed.get("extension", ""),
        "is_shot":   parsed.get("is_shot", False),
    }


def parse_publish_event(event: dict, known_type_tokens: set[str] | None = None) -> dict | None:
    """Return tokens for an activite.json publish entry, or None if unparseable.

    Disambiguates old vs new nomenclature when a filename could parse under
    both orders:

      NEW order : CLASS_NAME_TASK_INSTANCE[_VARIANTE]_ITER
      OLD order : CLASS_TYPE_NAME_INSTANCE[_VARIANTE]_ITER

    Uses *known_type_tokens* (the project's TYPE dict + defaults) as the tie
    breaker: whichever candidate places a known TYPE token at its TASK slot
    wins. When both or neither match, prefers the NEW order (the target).
    """
    filename = event.get("file") or ""
    if not filename:
        return None

    new = parse_flux_filename(filename)
    legacy_raw = legacy_parse_filename(filename)
    legacy = _legacy_to_new(legacy_raw) if legacy_raw else None

    if new and new.get("is_shot"):
        return new     # shot parsing is unchanged between orders
    if legacy and legacy.get("is_shot"):
        return legacy

    if new is None and legacy is None:
        return None
    if new is None:
        return legacy
    if legacy is None:
        return new

    if known_type_tokens:
        new_task_is_known    = new["TASK"] in known_type_tokens
        legacy_task_is_known = legacy["TASK"] in known_type_tokens
        if legacy_task_is_known and not new_task_is_known:
            return legacy
        if new_task_is_known and not legacy_task_is_known:
            return new
    return new


# ── path-override matching ───────────────────────────────────────────────────
# dest_folder is stored in activite.json as a portable "$FLUX/…" prefix; we
# strip that and compare it against the task.path_override the user set. When
# the event's folder sits under the override, the publish belongs to that
# task. The immediate child folder (relative to the override) is used as
# INSTANCE for subtask grouping.

_FLUX_PREFIX = "$FLUX/"


def _normalize_rel(p: str) -> str:
    return p.replace("\\", "/").strip("/").lower()


def _event_rel_path(event: dict) -> str | None:
    """Return the project-relative posix path for *event.dest_folder*, or None.

    dest_folder in activite.json looks like
      "$FLUX/DOSSIER_PROJETS/<projectName>/<rel path inside project>"
    We normalise to lowercase and drop the trailing slash for comparison.
    """
    dest = event.get("dest_folder") or ""
    if not dest:
        return None
    norm = dest.replace("\\", "/")
    if norm.startswith(_FLUX_PREFIX):
        norm = norm[len(_FLUX_PREFIX):]
    # Strip "DOSSIER_PROJETS/<project>/" — leave the intra-project relative part.
    parts = norm.split("/")
    if len(parts) >= 2 and parts[0].lower() == "dossier_projets":
        parts = parts[2:]  # drop the project name segment too
    inside = "/".join(parts).strip("/").lower()
    return inside or None


def _try_override_match(
    event: dict,
    override_tasks: list[tuple[dict, dict, str]],
) -> tuple[dict, dict, str] | None:
    """Return (asset, task, subtask_or_empty) if the event sits under any
    task's path_override, else None."""
    rel = _event_rel_path(event)
    if rel is None:
        return None
    for asset, task, ovr in override_tasks:
        if not ovr:
            continue
        if rel == ovr or rel.startswith(ovr + "/"):
            # extract the subtask = first child segment after the override
            sub = ""
            if len(rel) > len(ovr):
                tail = rel[len(ovr):].strip("/")
                first = tail.split("/", 1)[0] if tail else ""
                if first and first != "null":
                    sub = first.upper()
            return asset, task, sub
    return None


# ── matching ─────────────────────────────────────────────────────────────────

def _instance_is_meaningful(instance: str) -> bool:
    """The default 'NULL' instance is not a real subtask — filter it out."""
    return bool(instance) and instance.upper() not in ("NULL", "NONE", "")


def match_or_create_asset_task(production: dict, tokens: dict) -> tuple[dict, dict] | None:
    """Locate (or create) the (asset, task) that owns *tokens*.

    Returns (asset, task), or None if the required fields are missing.
    Mutates *production* when an asset or task is auto-created.
    """
    cls = tokens.get("CLASS", "")
    name = tokens.get("NAME", "")
    task_token = tokens.get("TASK", "")
    if not cls or not name or not task_token:
        return None

    asset = store.find_asset(production, cls, name)
    if asset is None:
        asset = store.add_asset(production, cls, name, origin="auto")

    task = store.find_task_by_type(asset, task_token)
    if task is None:
        task = store.add_task(asset, name=task_token, type_tokens=[task_token], origin="auto")

    return asset, task


def match_or_create_seq_shot_task(production: dict, tokens: dict) -> tuple[dict, dict, dict] | None:
    """Locate (or create) the (sequence, shot, task) triple for a shot publish.

    tokens['CLASS']    → shot task token (LAYOUT / ANIM / FX / CFX / LIGHT / COMP).
    tokens['SEQ']      → SEQ###.
    tokens['SHOT']     → SHOT###.

    Returns (seq, shot, task), or None if the required fields are missing.
    Mutates *production* when a seq / shot / task is auto-created.
    """
    seq_name  = (tokens.get("SEQ")  or "").upper()
    shot_name = (tokens.get("SHOT") or "").upper()
    task_tok  = (tokens.get("CLASS") or "").upper()
    if not seq_name or not shot_name or not task_tok:
        return None

    seq = store.find_sequence(production, seq_name)
    if seq is None:
        seq = _insert_seq_by_number(production, seq_name)

    shot = store.find_shot(production, seq["id"], shot_name)
    if shot is None:
        shot = _insert_shot_by_number(production, seq["id"], shot_name)

    task = store.find_task_by_type(shot, task_tok)
    if task is None:
        task = store.add_task(shot, name=task_tok, type_tokens=[task_tok], origin="auto")

    return seq, shot, task


# ── main entry ───────────────────────────────────────────────────────────────

def reconcile(
    production: dict,
    events: list[dict],
    known_type_tokens: set[str] | None = None,
    disk_assets: list[dict] | None = None,
    disk_shots: list[dict] | None = None,
) -> tuple[dict, dict[str, list[dict]], list[dict]]:
    """Enrich *production* in place, return (production, publishes_by_task, unmatched).

    - production           : same dict, with auto assets/tasks + mined subtasks.
    - publishes_by_task    : { "<entity_id>|<task_id>": [event, ...] } newest-first.
                             entity_id is either an asset id or a shot id — the
                             frontend looks it up in state.assets / state.shots.
    - unmatched            : events that could not be parsed (kept for debug).
    """
    publishes_by_task: dict[str, list[dict]] = {}
    unmatched: list[dict] = []

    # Sort events oldest → newest so append order in known_subtasks reflects
    # chronology; we reverse for publishes_by_task afterwards.
    sorted_events = sorted(events, key=lambda e: (e.get("date", ""), e.get("time", "")))

    # Snapshot every path_override-driven task so we can try them BEFORE the
    # token-based route. If a publish matches an override, it belongs to that
    # task exclusively (the user has explicitly rerouted it).
    override_tasks: list[tuple[dict, dict, str]] = []
    for a in production["assets"]:
        for t in a.get("tasks", []):
            ovr = (t.get("path_override") or "").strip()
            if ovr:
                override_tasks.append((a, t, _normalize_rel(ovr)))
    for s in production["shots"]:
        for t in s.get("tasks", []):
            ovr = (t.get("path_override") or "").strip()
            if ovr:
                override_tasks.append((s, t, _normalize_rel(ovr)))

    for event in sorted_events:
        tokens = parse_publish_event(event, known_type_tokens)

        # ── override route first (explicit user choice wins over token match)
        matched_by_override = _try_override_match(event, override_tasks)
        if matched_by_override is not None:
            entity, task, sub = matched_by_override
            if sub:
                store.add_known_subtask(task, sub)
            key = f"{entity['id']}|{task['id']}"
            publishes_by_task.setdefault(key, []).append({
                **event, "instance": sub, "task_token": task.get("name", ""),
            })
            continue

        if tokens is None:
            unmatched.append(event)
            continue

        if tokens.get("is_shot"):
            # A publish made before its shot was deleted must not bring the shot back.
            when = f"{event.get('date', '')} {event.get('time', '')}".strip()
            if is_archived(production, tokens.get("SEQ", ""), tokens.get("SHOT", ""), when):
                continue
            matched = match_or_create_seq_shot_task(production, tokens)
            if matched is None:
                unmatched.append(event)
                continue
            _seq, shot, task = matched
            instance = tokens.get("INSTANCE", "")
            if _instance_is_meaningful(instance):
                store.add_known_subtask(task, instance)
            key = f"{shot['id']}|{task['id']}"
            publishes_by_task.setdefault(key, []).append({
                **event,
                "instance": instance if _instance_is_meaningful(instance) else "",
                "task_token": tokens.get("CLASS", ""),
            })
            continue

        matched = match_or_create_asset_task(production, tokens)
        if matched is None:
            unmatched.append(event)
            continue
        asset, task = matched

        instance = tokens.get("INSTANCE", "")
        if _instance_is_meaningful(instance):
            store.add_known_subtask(task, instance)

        key = f"{asset['id']}|{task['id']}"
        enriched_event = {
            **event,
            "instance": instance if _instance_is_meaningful(instance) else "",
            "task_token": tokens.get("TASK", ""),
        }
        publishes_by_task.setdefault(key, []).append(enriched_event)

    # Newest-first per bucket
    for key in publishes_by_task:
        publishes_by_task[key].reverse()

    # ── disk-scan phase ──────────────────────────────────────────────────────
    # For each on-disk asset the artist created outside Production Tab, adopt
    # the asset, materialise its non-empty tasks, and add every instance dir
    # as a subtask. Publishes have already been processed above; this fills
    # the gap for assets that were scaffolded but never published yet.
    for da in disk_assets or []:
        cls  = (da.get("class") or "").upper()
        name = (da.get("name")  or "").upper()
        if not cls or not name:
            continue
        asset = store.find_asset(production, cls, name)
        if asset is None:
            asset = store.add_asset(production, cls, name, origin="auto")
        for tsk in da.get("tasks", []):
            token = (tsk.get("token") or "").upper()
            if not token:
                continue
            existing = store.find_task_by_type(asset, token)
            if existing is None:
                existing = store.add_task(asset, name=token, type_tokens=[token], origin="auto")
            for sub in tsk.get("subtasks", []):
                if sub:
                    store.add_known_subtask(existing, sub)

    # ── disk-scan phase (shots) ───────────────────────────────────────────────
    for ds in disk_shots or []:
        seq_name  = (ds.get("seq")  or "").upper()
        shot_name = (ds.get("shot") or "").upper() if ds.get("shot") else ""
        if not seq_name:
            continue
        seq = store.find_sequence(production, seq_name)
        if seq is None:
            seq = _insert_seq_by_number(production, seq_name)
        if not shot_name:
            continue
        shot = store.find_shot(production, seq["id"], shot_name)
        if shot is None:
            shot = _insert_shot_by_number(production, seq["id"], shot_name)
        for tsk in ds.get("tasks", []):
            token = (tsk.get("token") or "").upper()
            if not token:
                continue
            existing = store.find_task_by_type(shot, token)
            if existing is None:
                existing = store.add_task(shot, name=token, type_tokens=[token], origin="auto")
            for sub in tsk.get("subtasks", []):
                if sub:
                    store.add_known_subtask(existing, sub)

    return production, publishes_by_task, unmatched
