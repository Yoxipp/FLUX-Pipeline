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
        for asset_dir in _sorted_subdirs(class_dir):
            tasks = _walk_asset(asset_dir, disk_to_type)
            if not tasks:
                # Asset dir exists but has no non-empty task folder → still
                # surface the asset (empty task list) so the artist sees it
                # in the Production tab.
                out.append({"class": cls, "name": asset_dir.name.upper(), "tasks": []})
                continue
            out.append({"class": cls, "name": asset_dir.name.upper(), "tasks": tasks})
    return out


# ── helpers ──────────────────────────────────────────────────────────────────

def _walk_asset(asset_dir: Path, disk_to_type: dict[str, str]) -> list[dict]:
    """Return the tasks (with subtasks) for one asset directory."""
    tasks: list[dict] = []
    for task_dir in _sorted_subdirs(asset_dir):
        if not _dir_has_child(task_dir):
            continue
        token = disk_to_type.get(task_dir.name.lower(), task_dir.name.upper())
        subtasks = [
            d.name.upper()
            for d in _sorted_subdirs(task_dir)
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


def _sorted_subdirs(root: Path) -> list[Path]:
    try:
        return sorted((d for d in root.iterdir() if d.is_dir()), key=lambda p: p.name.lower())
    except OSError:
        return []


def _dir_has_child(root: Path) -> bool:
    try:
        return any(True for _ in root.iterdir())
    except OSError:
        return False
