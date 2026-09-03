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
from typing import Any

from core.logger import get_logger
from features.folder_manager.naming_validator import (
    ACTIVE_VERSION_LABEL,
    parse_filename as legacy_parse_filename,
)
from features.production import production_store as store

log = get_logger(__name__)


_VERSION_RE = re.compile(r"^v(\d+)$", re.IGNORECASE)
_SEQ_RE = re.compile(r"^SEQ\d+$", re.IGNORECASE)
_SHOT_RE = re.compile(r"^SHOT\d+$", re.IGNORECASE)


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

    # shot: CLASS_SEQ###_SHOT###_INSTANCE[_VARIANTE]
    if len(core) >= 2 and _SEQ_RE.match(core[1]):
        return {
            "CLASS":     core[0].upper(),
            "SEQ":       core[1].upper(),
            "SHOT":      core[2].upper() if len(core) > 2 else "",
            "INSTANCE":  core[3].upper() if len(core) > 3 else "",
            "VARIANTE":  core[4].upper() if len(core) > 4 else "",
            "TASK":      "",
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


# ── main entry ───────────────────────────────────────────────────────────────

def reconcile(
    production: dict,
    events: list[dict],
    known_type_tokens: set[str] | None = None,
    disk_assets: list[dict] | None = None,
) -> tuple[dict, dict[str, list[dict]], list[dict]]:
    """Enrich *production* in place, return (production, publishes_by_task, unmatched).

    - production           : same dict, with auto assets/tasks + mined subtasks.
    - publishes_by_task    : { "<asset_id>|<task_id>": [event, ...] } newest-first.
    - unmatched            : events that could not be parsed (kept for debug).

    Only asset publishes are handled in Phase 1. Shot publishes are recognised
    as `is_shot=True` and skipped — they surface in the unmatched list so the
    caller can decide what to do with them.
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

    for event in sorted_events:
        tokens = parse_publish_event(event, known_type_tokens)
        if tokens is None or (tokens or {}).get("is_shot"):
            # Try the override route even for shot / unparseable events, as long
            # as the event carries a portable dest_folder.
            matched_by_override = _try_override_match(event, override_tasks)
            if matched_by_override is not None:
                asset, task, sub = matched_by_override
                if sub:
                    store.add_known_subtask(task, sub)
                key = f"{asset['id']}|{task['id']}"
                publishes_by_task.setdefault(key, []).append({
                    **event, "instance": sub, "task_token": task.get("name", ""),
                })
                continue
            unmatched.append(event)
            continue

        # ── override route first (explicit user choice wins over token match)
        matched_by_override = _try_override_match(event, override_tasks)
        if matched_by_override is not None:
            asset, task, sub = matched_by_override
            if sub:
                store.add_known_subtask(task, sub)
            key = f"{asset['id']}|{task['id']}"
            publishes_by_task.setdefault(key, []).append({
                **event, "instance": sub, "task_token": task.get("name", ""),
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

    return production, publishes_by_task, unmatched
