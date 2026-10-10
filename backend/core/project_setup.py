# core/project_setup.py — the per-project setup folder (2026-10-10).
#
# FLUX's own files of a project (project.json, tokens.json, production.json,
# calendar.json, teamChat.json, locks.json and the _production/ media folder) live in
# <project>/_flux_setup/ instead of the project root, so the artists' tree stays clean.
# The folder is locked in the Folder Manager and hidden there unless "Setup files" is on.
#
# Old projects keep them at the root until migrate_project_setup() runs (on project
# open). Until then setup_path() falls back to the root copy, so nothing is lost and
# reads/writes keep hitting the one real file:
#   1. <project>/_flux_setup/<name> exists  -> that one
#   2. <project>/<name> exists (legacy)       -> that one
#   3. neither                                -> the _flux_setup one (new projects)

from __future__ import annotations

import logging
import os
from pathlib import Path

from core.constants import (
    JSON_CALENDAR,
    JSON_CHAT,
    JSON_LOCKS,
    JSON_PRODUCTION,
    JSON_PROJECT,
    JSON_TOKENS,
    PRODUCTION_MEDIA_DIR,
    SETUP_DIR,
)

log = logging.getLogger(__name__)

SETUP_FILES: tuple[str, ...] = (JSON_PROJECT, JSON_TOKENS, JSON_PRODUCTION, JSON_CALENDAR, JSON_CHAT, JSON_LOCKS)
SETUP_DIRS: tuple[str, ...] = (PRODUCTION_MEDIA_DIR,)
SETUP_NAMES: frozenset[str] = frozenset((SETUP_DIR, *SETUP_FILES, *SETUP_DIRS))


def setup_dir(project: Path | str) -> Path:
    return Path(project) / SETUP_DIR


def setup_path(project: Path | str, name: str) -> Path:
    """Where the setup file/folder *name* of *project* lives (see header)."""
    new = setup_dir(project) / name
    if new.exists():
        return new
    legacy = Path(project) / name
    if legacy.exists():
        return legacy
    return new


def resolve_project_rel(project: Path | str, rel: str) -> Path:
    """<project>/<rel>, with a leading setup name (e.g. the "_production/thumbnails/..."
    stored in production.json) routed through setup_path."""
    parts = [p for p in (rel or "").replace("\\", "/").split("/") if p]
    if parts and parts[0] in SETUP_FILES + SETUP_DIRS:
        return setup_path(project, parts[0]).joinpath(*parts[1:])
    return Path(project).joinpath(*parts)


def is_project_root(folder: Path | str) -> bool:
    """True when *folder* is a FLUX project (project.json or tokens.json, either place)."""
    folder = Path(folder)
    return any((base / name).is_file()
               for base in (folder / SETUP_DIR, folder)
               for name in (JSON_PROJECT, JSON_TOKENS))


def is_setup_rel(rel: str) -> bool:
    """True when the project-relative *rel* is the setup folder or a setup file/folder
    (or anything under them). Used by the Folder Manager lock and filter."""
    first = (rel or "").replace("\\", "/").strip("/").split("/", 1)[0]
    if not first:
        return False
    if first in SETUP_NAMES:
        return True
    # json_manager lock companions (teamChat.json.lock ...).
    return first.endswith(".lock") and first[:-5] in SETUP_FILES


def migrate_project_setup(project: Path | str) -> list[str]:
    """Move the legacy root setup files/folders of *project* into _flux_setup/.

    Idempotent and never destructive: an item already present in _flux_setup/ is left
    alone at the root (logged, e.g. recreated by an older FLUX). Returns the moved names.
    A failed move (OneDrive / file in use) is logged and retried on the next open; the
    fallback of setup_path keeps reading the root copy meanwhile."""
    project = Path(project)
    if not project.is_dir():
        return []
    moved: list[str] = []
    target_dir = setup_dir(project)
    for name in (*SETUP_FILES, *SETUP_DIRS):
        legacy = project / name
        if not legacy.exists():
            continue
        target = target_dir / name
        if target.exists():
            log.warning("setup migration %s: %s exists in both places, root copy left as is", project.name, name)
            continue
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            os.replace(legacy, target)
            moved.append(name)
        except OSError as exc:
            log.warning("setup migration %s: cannot move %s (%s)", project.name, name, exc)
            continue
        # Stale lock companion of a moved JSON file: recreated next to the new one.
        lock = project / f"{name}.lock"
        if lock.is_file():
            try:
                lock.unlink()
            except OSError:
                pass
    if moved:
        log.info("setup migration %s: moved %s into %s/", project.name, ", ".join(moved), SETUP_DIR)
    return moved
