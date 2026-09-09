# sync.py — materialize Production planning entities onto disk. CREATE-ONLY.
#
# This closes the Production → Disk half of the bidirectional sync (the Disk →
# Production half already runs at GET time via disk_scan + reconcile). Whenever
# production.json is saved, every asset / sequence / shot / task / subtask it
# declares is ensured to exist on disk.
#
# ── SAFEGUARD CONTRACT (critical) ────────────────────────────────────────────
# This module can only ADD folders. It NEVER deletes, moves, empties, renames or
# overwrites anything on disk. Every filesystem call it makes is ensure_dir() on
# a folder path — there is no unlink / rmtree / rename / replace / copy anywhere
# in this file. A Production edit can therefore never destroy on-disk data:
#   * renaming an asset creates the new folder and LEAVES the old one untouched;
#   * removing a task in Production leaves its disk folder in place;
#   * a task/subtask folder is only ever created when missing.
# Deletion is a separate, explicit user operation — it must never be a side
# effect of a create/sync.

from __future__ import annotations

import re
from pathlib import Path

from core.constants import DEFAULT_CLASS_TOKENS, DEFAULT_TYPE_TOKENS
from core.logger import get_logger
from core.paths import ensure_dir
from features.folder_manager.seq_shot_creator import update_sequence
from features.folder_manager.tokens import add_token, load_tokens

log = get_logger(__name__)

_SEQ_NUM_RE = re.compile(r"(\d+)")


def _num(name: str) -> int | None:
    """Extract the trailing number from a SEQ###/SHOT### token."""
    m = _SEQ_NUM_RE.search(name or "")
    return int(m.group(1)) if m else None


def _is_templated(rel: str) -> bool:
    return "{" in rel or "}" in rel


def sync_production_to_disk(project_path: Path, production: dict) -> dict:
    """Ensure every entity declared in *production* exists on disk. Create-only.

    Returns a summary ``{"assets": n, "tasks": n, "subtasks": n, "sequences": n}``
    counting the folders newly created (best-effort; used for logging only).
    Never raises for a single bad entity — each is guarded so one failure cannot
    abort the whole sync or, worse, leave disk half-changed in a destructive way
    (nothing here is destructive to begin with).
    """
    tokens = load_tokens(project_path)
    class_map = {**DEFAULT_CLASS_TOKENS, **(tokens.get("CLASS") or {})}
    type_map  = {**DEFAULT_TYPE_TOKENS,  **(tokens.get("TYPE")  or {})}
    name_map  = tokens.get("NAME") or {}

    created = {"assets": 0, "tasks": 0, "subtasks": 0, "sequences": 0}

    for asset in production.get("assets", []):
        try:
            created_here = _sync_asset(project_path, asset, class_map, type_map, name_map)
            for k, v in created_here.items():
                created[k] += v
        except Exception as exc:  # noqa: BLE001 — never let one asset abort the sync
            log.warning("sync_asset failed for %r: %s", asset.get("name"), exc)

    # Sequences + shots + their tasks/subtasks reuse update_sequence, which is
    # itself strictly additive (ensure_dir only) and authors the USD/hip lighting
    # templates once, when a seq/shot folder is first created.
    shots_by_seq: dict[str, list[dict]] = {}
    seq_by_id = {s.get("id"): s for s in production.get("sequences", [])}
    for shot in production.get("shots", []):
        seq = seq_by_id.get(shot.get("seq_id"))
        if not seq:
            continue
        n = _num(shot.get("name", ""))
        if n is None:
            continue
        shots_by_seq.setdefault(seq.get("name", ""), []).append({
            "number": n,
            "tasks": [
                {"token": t.get("name") or (t.get("type_tokens") or [""])[0],
                 "subtasks": list(t.get("known_subtasks") or [])}
                for t in shot.get("tasks", [])
            ],
        })

    for seq in production.get("sequences", []):
        seq_name = seq.get("name", "")
        seq_num = _num(seq_name)
        if seq_num is None:
            continue
        try:
            update_sequence(project_path, seq_num, shots_by_seq.get(seq_name, []), class_map)
            created["sequences"] += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("sync sequence %r failed: %s", seq_name, exc)

    if any(created.values()):
        log.info("Production→disk sync (%s): %s", project_path.name, created)
    return created


def _sync_asset(
    project_path: Path,
    asset: dict,
    class_map: dict[str, str],
    type_map: dict[str, str],
    name_map: dict[str, str],
) -> dict:
    """Create (only-if-missing) an asset root and its task/subtask folders."""
    created = {"assets": 0, "tasks": 0, "subtasks": 0}

    cls = (asset.get("class") or "").upper()
    name = (asset.get("name") or "").upper()
    if not cls or not name:
        return created

    class_rel = class_map.get(cls)
    if not class_rel or _is_templated(class_rel):
        return created  # unknown/templated class — not an on-disk asset root

    name_rel = name_map.get(name) or f"{class_rel}/{name}"
    asset_root = project_path / name_rel
    if not asset_root.exists():
        ensure_dir(asset_root)
        created["assets"] += 1
        # Register the NAME token so the publisher resolves this asset the same
        # way whether it was born in Production or the Folder Manager.
        if name_map.get(name) is None:
            add_token(project_path, "NAME", name, name_rel)

    # Task folders: same resolution the publisher uses (TYPE value, else lower()).
    for task in asset.get("tasks", []):
        tokens_for_task = [t for t in (task.get("type_tokens") or []) if t] or \
                          ([task.get("name")] if task.get("name") else [])
        for token in tokens_for_task:
            type_sub = type_map.get(token.upper()) or token.lower()
            task_dir = project_path / name_rel / type_sub
            if not task_dir.exists():
                ensure_dir(task_dir)
                created["tasks"] += 1
            for sub in task.get("known_subtasks", []) or []:
                sub_label = str(sub).strip()
                if not sub_label or sub_label.lower() == "null":
                    continue
                sub_dir = task_dir / sub_label.lower()
                if not sub_dir.exists():
                    ensure_dir(sub_dir)
                    created["subtasks"] += 1

    return created
