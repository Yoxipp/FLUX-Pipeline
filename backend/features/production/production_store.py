# production_store.py — read/write production.json for a project.
#
# production.json holds the planning layer: sequences, shots, assets, tasks,
# notes, retakes. Never duplicates disk data. Publishes are matched at read
# time by reconcile.py, not stored here.

from __future__ import annotations

import hashlib
import json
import threading
import uuid

from core.logger import get_logger
from core.repository_factory import get_repository

log = get_logger(__name__)

# Metadata frontier (V5 Phase 1a): production.json is one document in the
# "production" collection, keyed by project name. The factory resolves it to
# get_project_production_path(); no store here touches json_manager directly.
_COLLECTION = "production"

SCHEMA_VERSION = 1

# Serialises writers of this process (HTTP routes, bot thread) so that the
# version check and the write of save_production_if are one step.
_WRITE_LOCK = threading.RLock()


class StaleProductionError(Exception):
    """The store moved since the caller loaded it. *current* is the stored doc."""

    def __init__(self, current: dict, version: str) -> None:
        super().__init__("production.json changed since it was loaded")
        self.current = current
        self.version = version


def version_of(data: dict) -> str:
    """Content hash of a production document, not stored in it. Same value on every
    backend, and an identical rewrite does not move it (a file stat would)."""
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def default_schema() -> dict:
    return {
        "version": SCHEMA_VERSION,
        "sequences": [],
        "shots": [],
        "assets": [],
        "asset_groups": [],
    }


def load_production(project_name: str) -> dict:
    """Read production.json for *project_name*, or return the default schema.

    Missing keys are healed against the default schema so callers can rely on
    every top-level list being present.
    """
    data = get_repository().get(_COLLECTION, project_name)
    if not isinstance(data, dict):
        return default_schema()
    return _heal(data)


def save_production(project_name: str, data: dict) -> bool:
    """Write production.json atomically. Returns True on success."""
    with _WRITE_LOCK:
        ok = get_repository().set(_COLLECTION, project_name, _heal(data))
    if not ok:
        log.error("Failed to write production.json for project %r", project_name)
    return ok


def save_production_if(project_name: str, data: dict, base_version: str | None) -> str | None:
    """save_production only when the store still is at *base_version* (None: no check).
    Returns the new version, None when the write failed. Raises StaleProductionError."""
    with _WRITE_LOCK:
        if base_version:
            current = load_production(project_name)
            version = version_of(current)
            if version != base_version:
                raise StaleProductionError(current, version)
        if not save_production(project_name, data):
            return None
        return version_of(load_production(project_name))


def _heal(data: dict) -> dict:
    """Ensure the returned dict carries every top-level field of the schema."""
    base = default_schema()
    for key, val in base.items():
        data.setdefault(key, val)
    data["version"] = SCHEMA_VERSION
    return data


# ── id helpers ───────────────────────────────────────────────────────────────

def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# ── pure mutation helpers ────────────────────────────────────────────────────
# These operate on *data* in place and return the affected entity for the caller.

def add_asset(
    data: dict,
    class_token: str,
    name: str,
    group_id: str | None = None,
    origin: str = "user",
) -> dict:
    asset = {
        "id": new_id("asset"),
        "class": class_token.upper(),
        "name": name.upper(),
        "group_id": group_id,
        "order": len(data["assets"]),
        "origin": origin,
        "tasks": [],
        "task_details": {},
    }
    data["assets"].append(asset)
    return asset


def find_asset(data: dict, class_token: str, name: str) -> dict | None:
    cls = class_token.upper()
    nm = name.upper()
    for a in data["assets"]:
        if a.get("class") == cls and a.get("name") == nm:
            return a
    return None


def add_sequence(data: dict, name: str, origin: str = "user") -> dict:
    seq = {
        "id": new_id("seq"),
        "name": name.upper(),
        "order": len(data["sequences"]),
        "origin": origin,
        "tasks": [],
        "assets": [],
        "task_details": {},
        "notes": "",
    }
    data["sequences"].append(seq)
    return seq


def find_sequence(data: dict, name: str) -> dict | None:
    nm = name.upper()
    for s in data["sequences"]:
        if s.get("name") == nm:
            return s
    return None


def add_shot(data: dict, seq_id: str, name: str, origin: str = "user") -> dict:
    shot = {
        "id": new_id("shot"),
        "seq_id": seq_id,
        "name": name.upper(),
        "order": len([s for s in data["shots"] if s.get("seq_id") == seq_id]),
        "origin": origin,
        "inherit_tasks": True,
        "inherit_assets": True,
        "tasks": [],
        "assets": [],
        "task_details": {},
    }
    data["shots"].append(shot)
    return shot


def find_shot(data: dict, seq_id: str, name: str) -> dict | None:
    nm = name.upper()
    for s in data["shots"]:
        if s.get("seq_id") == seq_id and s.get("name") == nm:
            return s
    return None


def add_asset_group(data: dict, class_token: str, name: str) -> dict:
    grp = {
        "id": new_id("g"),
        "class": class_token.upper(),
        "name": name.upper(),
        "order": len(data["asset_groups"]),
    }
    data["asset_groups"].append(grp)
    return grp


def add_task(
    entity: dict,
    name: str,
    type_tokens: list[str] | None = None,
    origin: str = "user",
) -> dict:
    """Append a task to *entity* (asset, shot or seq). Returns the new task."""
    tasks = entity.setdefault("tasks", [])
    task = {
        "id": new_id("t"),
        "name": name.upper(),
        "order": len(tasks),
        "type_tokens": [t.upper() for t in (type_tokens or [])],
        "known_subtasks": [],
        "origin": origin,
    }
    tasks.append(task)
    return task


def find_task_by_type(entity: dict, type_token: str) -> dict | None:
    """Return the first task of *entity* whose type_tokens contain *type_token*."""
    tt = type_token.upper()
    for t in entity.get("tasks", []):
        if tt in [x.upper() for x in t.get("type_tokens", [])]:
            return t
    return None


def add_known_subtask(task: dict, subtask: str) -> bool:
    """Add *subtask* to task.known_subtasks if new. Returns True when added."""
    if not subtask:
        return False
    val = subtask.upper()
    known = task.setdefault("known_subtasks", [])
    if val in [k.upper() for k in known]:
        return False
    known.append(val)
    return True


def update_task_detail(entity: dict, task_name: str, patch: dict) -> dict:
    """Merge *patch* into entity.task_details[task_name]. Returns the detail dict."""
    details = entity.setdefault("task_details", {})
    key = task_name.upper()
    detail = details.setdefault(key, {"notes": "", "progress": "", "links": [], "retakes": []})
    detail.update(patch)
    return detail


def add_retake(
    entity: dict, task_name: str, text: str, author: str, date: str
) -> dict:
    detail = update_task_detail(entity, task_name, {})
    retake = {
        "id": new_id("r"),
        "text": text,
        "author": author.upper(),
        "date": date,
        "status": "open",
    }
    detail.setdefault("retakes", []).append(retake)
    return retake


def add_shot_retake_comment(data: dict, seq: str, shot: str, task: str, text: str,
                            author: str, date: str, time: str) -> dict:
    """Append a 'retake' comment (the kind the task panel and the home "Tes retakes" read)
    to task *task* of shot *seq*/*shot* (ADR 0083, shotboard idea sent to Production).
    *task* must be one of the shot's tasks (its own, or its sequence's when inherited).
    Raises ValueError when the shot or the task is unknown or the text is empty."""
    text = (text or "").strip()
    if not text:
        raise ValueError("retake vide")
    seq_entry = next((s for s in data.get("sequences", []) if str(s.get("name", "")).upper() == seq.upper()), None)
    shot_entry = None if seq_entry is None else next(
        (sh for sh in data.get("shots", [])
         if sh.get("seq_id") == seq_entry.get("id") and str(sh.get("name", "")).upper() == shot.upper()), None)
    if shot_entry is None:
        raise ValueError(f"shot {seq}/{shot} introuvable dans Production")
    tasks = list(shot_entry.get("tasks") or [])
    if shot_entry.get("inherit_tasks", True):
        tasks += list(seq_entry.get("tasks") or [])
    name = next((str(t.get("name")) for t in tasks if str(t.get("name", "")).upper() == task.upper()), None)
    if name is None:
        raise ValueError(f"tache {task} inconnue pour {seq}/{shot}")
    details = shot_entry.setdefault("task_details", {})
    # The task panel keys details by the task name as written; reuse a key of another case.
    key = next((k for k in details if k.upper() == name.upper()), name)
    detail = details.setdefault(key, {})
    comment = {"id": new_id("c"), "text": text[:10_000], "author": (author or "unknown").upper(),
               "date": date, "time": time, "kind": "retake"}
    detail.setdefault("comments", []).append(comment)
    return comment


def collect_project_type_tokens(data: dict) -> list[str]:
    """Return every TYPE token currently used across all tasks (for suggestions)."""
    seen: set[str] = set()
    for a in data["assets"]:
        for t in a.get("tasks", []):
            for tk in t.get("type_tokens", []):
                seen.add(tk.upper())
    for s in data["shots"]:
        for t in s.get("tasks", []):
            for tk in t.get("type_tokens", []):
                seen.add(tk.upper())
    return sorted(seen)
