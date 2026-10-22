# disk_scan.py — surface on-disk assets that were never published (yet).
#
# reconcile() ingests activity events; that's enough for tasks/subtasks the
# artist has already published. But an asset can exist on disk (folders
# scaffolded by the folder manager) with no publish yet — the artist still
# expects it to appear in the Production tab.
#
# This module walks the standard asset trees and returns triples that
# reconcile() then materializes:
#   { class, name, tasks: [{ task_token, subtasks: [instance_token, …] }] }
#
# Rules:
#   * Only static CLASS paths are walked (skip templated ones like
#     "shot/{seq}/{shot}"). Phase 1 handles assets only.
#   * A task is included only when its folder has at least one child
#     (folder or file) — matches the user's "task apparaît quand le
#     dossier est non vide" rule.
#   * Subtasks are the child directories of a task folder, minus the
#     default INSTANCE placeholder ("null").
#   * Disk folder names are reverse-mapped to TYPE tokens (model → GEO
#     etc.) so labels line up with the publisher's vocabulary.

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from core.constants import DEFAULT_TYPE_TOKENS
from core.logger import get_logger

log = get_logger(__name__)

# The four categories the Production Tab surfaces at the root.
_PROD_CLASSES = ("CHAR", "PROPS", "ENV", "FXRIG")

# Folder names never treated as an INSTANCE subtask.
_INSTANCE_IGNORED = {"null"}


def scan_project_assets(
    project_path: Path,
    class_tokens: dict[str, str],
    type_tokens: dict[str, str] | None = None,
) -> list[dict]:
    """Walk *project_path* for on-disk assets in the 4 Production categories.

    *class_tokens* : mapping CLASS → relative path (from tokens.json[CLASS] merged
                     with DEFAULT_CLASS_TOKENS). Only entries with a *static*
                     path (no "{seq}", "{shot}") are walked.
    *type_tokens*  : mapping TYPE → relative path (defaults + project custom).
                     Used to reverse-map a top-level task dir ("model") to a
                     token ("GEO"). Falls back to the disk name uppercased.

    Returns a list of dicts, one per asset:
        {"class": "CHAR", "name": "UTAH",
         "tasks": [{"token": "GEO", "subtasks": ["SCULPT", "BLOCK"]}, …]}
    """
    types = type_tokens or DEFAULT_TYPE_TOKENS
    disk_to_type = _build_disk_to_type_map(types)

    out: list[dict] = []
    for cls in _PROD_CLASSES:
        rel = class_tokens.get(cls)
        if not rel or _is_templated(rel):
            continue
        class_dir = (project_path / rel).resolve()
        if not class_dir.is_dir():
            continue
        asset_dirs = _sorted_subdirs(class_dir)
        walked = _POOL.map(lambda d: _walk_asset(d, disk_to_type), asset_dirs)
        for asset_dir, tasks in zip(asset_dirs, walked):
            if not tasks:
                # Asset dir exists but has no non-empty task folder → still
                # surface the asset (empty task list) so the artist sees it
                # in the Production tab.
                out.append({"class": cls, "name": asset_dir.name.upper(), "tasks": []})
                continue
            out.append({"class": cls, "name": asset_dir.name.upper(), "tasks": tasks})
    return out


# Generated USD folders (asset component, shot stage : ADR 0018 / 0020) hold versions,
# not work: never read as a task (else Production grows a "USD" task whose subtasks
# are version folders, and the create-only sync copies them into other shots).
_NOT_TASK_DIRS = frozenset({"usd"})


def scan_project_shots(
    project_path: Path,
    class_tokens: dict[str, str],
) -> list[dict]:
    """Walk the shot trees for every CLASS whose path template contains
    ``{seq}`` and ``{shot}`` (LAYOUT / ANIM / FX / CFX …).

    Returns a list of dicts, one per (seq, shot) pair found:
        {"seq": "SEQ001", "shot": "SHOT010",
         "tasks": [{"token": "ANIM", "subtasks": ["BLOCK", "SPLINE"]}, …]}

    Multiple CLASS tokens can share a prefix like ``shot/{seq}/{shot}``; the
    scanner deduplicates by (seq, shot) and merges tasks. A task is included
    only when its folder holds at least one child (matches the artist's
    "folder non-empty" rule). Subtasks are the child directories minus the
    ``null`` placeholder.
    """
    # Group class tokens by the fixed prefix before ``{seq}`` so we walk each
    # root at most once (LAYOUT and ANIM both live under ``shot`` in the
    # defaults, but a project could override to different roots).
    prefixes: set[str] = set()
    class_task_map: dict[str, str] = {}   # last-segment dir name → CLASS token
    for cls, rel in class_tokens.items():
        if not rel or "{seq}" not in rel or "{shot}" not in rel:
            continue
        norm = rel.replace("\\", "/").strip("/")
        # Expect "<root...>/{seq}/{shot}[/<task_dir>]".
        parts = norm.split("/")
        try:
            seq_idx = parts.index("{seq}")
        except ValueError:
            continue
        if seq_idx + 1 >= len(parts) or parts[seq_idx + 1] != "{shot}":
            continue
        root = "/".join(parts[:seq_idx]).strip("/")
        if not root:
            continue
        prefixes.add(root)
        # Optional task dir after {shot} — e.g. shot/{seq}/{shot}/anim.
        if seq_idx + 2 < len(parts):
            task_dir = parts[seq_idx + 2].lower()
            class_task_map[task_dir] = cls.upper()

    out_map: dict[tuple[str, str | None], dict] = {}
    for root_rel in sorted(prefixes):
        root_dir = (project_path / root_rel).resolve()
        if not root_dir.is_dir():
            continue
        for seq_dir in _sorted_subdirs(root_dir):
            if not seq_dir.name.upper().startswith("SEQ"):
                continue
            # Surface the seq even when it holds no shots yet.
            seq_key: tuple[str, str | None] = (seq_dir.name.upper(), None)
            out_map.setdefault(seq_key, {"seq": seq_key[0], "shot": None, "tasks": []})
            shot_dirs = [d for d in _sorted_subdirs(seq_dir) if d.name.upper().startswith("SHOT")]
            walked = _POOL.map(lambda d: _walk_shot(d, class_task_map), shot_dirs)
            for shot_dir, shot_tasks in zip(shot_dirs, walked):
                key: tuple[str, str | None] = (seq_dir.name.upper(), shot_dir.name.upper())
                entry = out_map.setdefault(key, {"seq": key[0], "shot": key[1], "tasks": []})
                for token, subtasks in shot_tasks:
                    # Merge if two prefixes hit the same shot with same task token.
                    existing = next((t for t in entry["tasks"] if t["token"] == token), None)
                    if existing is None:
                        entry["tasks"].append({"token": token, "subtasks": subtasks})
                    else:
                        for s in subtasks:
                            if s not in existing["subtasks"]:
                                existing["subtasks"].append(s)
    return list(out_map.values())


# ── helpers ──────────────────────────────────────────────────────────────────

# Asset / shot folders are listed concurrently: on the share each listing waits a
# network round trip, so a few threads cut the scan time without more requests.
_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="flux-disk-scan")


def _walk_shot(shot_dir: Path, class_task_map: dict[str, str]) -> list[tuple[str, list[str]]]:
    """(task token, subtasks) of one shot directory, non-empty task folders only."""
    found: list[tuple[str, list[str]]] = []
    for task_dir in _sorted_subdirs(shot_dir):
        if task_dir.name.lower() in _NOT_TASK_DIRS:
            continue
        has_child, task_subdirs = _list_dir(task_dir)
        if not has_child:
            continue
        token = class_task_map.get(task_dir.name.lower(), task_dir.name.upper())
        found.append((token, [d.name.upper() for d in task_subdirs
                              if d.name.lower() not in _INSTANCE_IGNORED]))
    return found


def _walk_asset(asset_dir: Path, disk_to_type: dict[str, str]) -> list[dict]:
    """Return the tasks (with subtasks) for one asset directory."""
    tasks: list[dict] = []
    for task_dir in _sorted_subdirs(asset_dir):
        if task_dir.name.lower() in _NOT_TASK_DIRS:
            continue
        has_child, task_subdirs = _list_dir(task_dir)
        if not has_child:
            continue
        token = disk_to_type.get(task_dir.name.lower(), task_dir.name.upper())
        subtasks = [
            d.name.upper()
            for d in task_subdirs
            if d.name.lower() not in _INSTANCE_IGNORED
        ]
        tasks.append({"token": token.upper(), "subtasks": subtasks})
    return tasks


def _build_disk_to_type_map(type_tokens: dict[str, str]) -> dict[str, str]:
    """Reverse mapping so 'model' → 'GEO'. Only single-segment values are used
    (nested values like 'model/sculpt' would collide with a top-level task)."""
    reverse: dict[str, str] = {}
    for token, path in type_tokens.items():
        if not path or "/" in path or "\\" in path:
            continue
        reverse.setdefault(path.strip().lower(), token.upper())
    return reverse


def _is_templated(rel: str) -> bool:
    return "{" in rel or "}" in rel


# os.scandir, not Path.iterdir + is_dir: on Windows the directory listing already
# carries the entry type, so a folder costs one network round trip on the share
# instead of one per child (2026-10-22: scan ~850 ms -> see school_opti_prompt).

def _list_dir(root: Path) -> tuple[bool, list[Path]]:
    """(has any child, sorted child directories) of *root*, in one listing."""
    try:
        with os.scandir(root) as it:
            entries = list(it)
    except OSError:
        return False, []
    dirs = []
    for e in entries:
        try:
            if e.is_dir():
                dirs.append(Path(e.path))
        except OSError:
            continue
    return bool(entries), sorted(dirs, key=lambda p: p.name.lower())


def _sorted_subdirs(root: Path) -> list[Path]:
    return _list_dir(root)[1]


def _dir_has_child(root: Path) -> bool:
    return _list_dir(root)[0]
