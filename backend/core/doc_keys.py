# doc_keys.py - logical document keys for shared metadata backends (ADR 0004, V8 U2).
#
# The stores address documents by what they already compute: an absolute path
# (project folder, publish folder, CONFIG file) or a project name. A path is only
# valid on the machine that computed it, so a base shared between machines must not
# store it. This module translates, at the repository seam, store keys <-> logical keys:
#
#   tokens, locks        <project dir>              -> <project_id>
#   production, calendar <project name>             -> <project_id>
#   modif_log            <project dir>/<rel folder> -> <project_id>/<rel folder>
#   feeds, read_state,   <FLUX_ROOT>/<rel file>     -> ws:<rel file>
#   feed_archive
#   user_settings, config: already logical, unchanged.
#
# Anything that cannot be translated (no FLUX_ROOT, path outside the workspace, project
# without project.json yet) keeps its store key: never guessed, never lost.
# Applied only to the SQLite / remote backends (2026-09-16, option 1): the JSON
# backend keeps using paths locally, which never get written to disk.
# to_logical is read-only: it never creates project.json (U1 does, then rekeys).

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from core.constants import JSON_PROJECT
from core.project_setup import setup_path

WS_PREFIX = "ws:"
PROJECT_PATH_COLLECTIONS = frozenset({"tokens", "locks"})
PROJECT_NAME_COLLECTIONS = frozenset({"production", "calendar"})
FOLDER_COLLECTIONS = frozenset({"modif_log"})
WORKSPACE_COLLECTIONS = frozenset(
    {"read_state", "activity_log", "chat_log", "mentions_log", "feed_archive"}
)

# project dir (normcased) -> (project.json mtime_ns, project_id)
_pid_cache: dict[str, tuple[int, str]] = {}


# ── roots ─────────────────────────────────────────────────────────────────────

def _default_roots() -> tuple[Path | None, Path | None]:
    """(flux_root, projects_dir) of this machine, or (None, None) when unset."""
    from core import paths  # local: avoid a bootstrap import cycle

    root = paths.get_flux_root()
    if root is None:
        return None, None
    try:
        return Path(root), paths.get_projects_dir()
    except RuntimeError:
        return Path(root), None


def _norm(p: Path | str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(str(p))))


def _rel_under(path: Path | str, root: Path | str) -> str | None:
    """Posix relative path of *path* under *root* ("" for root itself), else None."""
    np, nr = _norm(path), _norm(root)
    if np == nr:
        return ""
    if not np.startswith(nr.rstrip(os.sep) + os.sep):
        return None
    original = os.path.normpath(os.path.abspath(str(path)))
    return original[len(nr.rstrip(os.sep)) + 1:].replace(os.sep, "/")


def _looks_like_path(doc_id: str) -> bool:
    return os.path.isabs(doc_id)


# ── project identity ──────────────────────────────────────────────────────────

def project_id_of(project_dir: Path) -> str | None:
    """project_id read from the project.json of *project_dir* (cached on mtime), or None."""
    cfg = setup_path(project_dir, JSON_PROJECT)
    try:
        mtime = cfg.stat().st_mtime_ns
    except OSError:
        return None
    key = _norm(project_dir)
    cached = _pid_cache.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    pid = data.get("project_id") if isinstance(data, dict) else None
    if not isinstance(pid, str) or not pid:
        return None
    _pid_cache[key] = (mtime, pid)
    return pid


def project_dir_of(project_id: str, projects_dir: Path | None) -> Path | None:
    """Project folder whose project.json holds *project_id*, or None."""
    if projects_dir is None:
        return None
    try:
        children = [p for p in Path(projects_dir).iterdir() if p.is_dir()]
    except OSError:
        return None
    for child in children:
        if project_id_of(child) == project_id:
            return child
    return None


# ── translation ───────────────────────────────────────────────────────────────

def to_logical(
    collection: str,
    doc_id: str,
    *,
    flux_root: Path | None = None,
    projects_dir: Path | None = None,
) -> str:
    """Store key -> logical key (identity when not translatable or already logical)."""
    doc_id = str(doc_id)
    if flux_root is None and projects_dir is None:
        flux_root, projects_dir = _default_roots()

    if collection in WORKSPACE_COLLECTIONS:
        if flux_root is None or not _looks_like_path(doc_id):
            return doc_id
        rel = _rel_under(doc_id, flux_root)
        return f"{WS_PREFIX}{rel}" if rel else doc_id

    if projects_dir is None:
        return doc_id

    if collection in PROJECT_PATH_COLLECTIONS:
        if not _looks_like_path(doc_id):
            return doc_id
        rel = _rel_under(doc_id, projects_dir)
        if not rel or "/" in rel:
            return doc_id
        return project_id_of(Path(projects_dir) / rel) or doc_id

    if collection in PROJECT_NAME_COLLECTIONS:
        if _looks_like_path(doc_id) or "/" in doc_id or "\\" in doc_id:
            return doc_id
        return project_id_of(Path(projects_dir) / doc_id) or doc_id

    if collection in FOLDER_COLLECTIONS:
        if not _looks_like_path(doc_id):
            return doc_id
        rel = _rel_under(doc_id, projects_dir)
        if not rel:
            return doc_id
        name, _, rest = rel.partition("/")
        pid = project_id_of(Path(projects_dir) / name)
        if not pid:
            return doc_id
        return f"{pid}/{rest}" if rest else pid

    return doc_id


def to_store(
    collection: str,
    key: str,
    *,
    flux_root: Path | None = None,
    projects_dir: Path | None = None,
) -> str:
    """Logical key -> store key of this machine (identity when not a logical key)."""
    key = str(key)
    if flux_root is None and projects_dir is None:
        flux_root, projects_dir = _default_roots()

    if collection in WORKSPACE_COLLECTIONS:
        if flux_root is None or not key.startswith(WS_PREFIX):
            return key
        return str(Path(flux_root) / key[len(WS_PREFIX):])

    if _looks_like_path(key):
        return key

    if collection in PROJECT_PATH_COLLECTIONS:
        found = project_dir_of(key, projects_dir)
        return str(found) if found else key

    if collection in PROJECT_NAME_COLLECTIONS:
        found = project_dir_of(key, projects_dir)
        return found.name if found else key

    if collection in FOLDER_COLLECTIONS:
        pid, _, rest = key.partition("/")
        found = project_dir_of(pid, projects_dir)
        if not found:
            return key
        return str(found / rest) if rest else str(found)

    return key


# ── repository wrapper ────────────────────────────────────────────────────────

class LogicalKeyRepository:
    """MetadataRepository that stores logical keys in *inner* (SQLite / remote).

    Stores keep passing their usual keys; every doc_id is translated on the way in.
    Other attributes (backend specific helpers) are forwarded untouched.
    """

    def __init__(self, inner, key_fn: Callable[[str, str], str] = to_logical) -> None:
        self._inner = inner
        self._key = key_fn

    @property
    def inner(self):
        return self._inner

    def get(self, collection: str, doc_id: str):
        return self._inner.get(collection, self._key(collection, doc_id))

    def set(self, collection: str, doc_id: str, data) -> bool:
        return self._inner.set(collection, self._key(collection, doc_id), data)

    def update(self, collection: str, doc_id: str, patch: dict) -> bool:
        return self._inner.update(collection, self._key(collection, doc_id), patch)

    def delete(self, collection: str, doc_id: str) -> None:
        return self._inner.delete(collection, self._key(collection, doc_id))

    def read_log(self, collection: str, doc_id: str, *, fresh: bool = False, sig=None) -> list[dict]:
        return self._inner.read_log(collection, self._key(collection, doc_id), fresh=fresh, sig=sig)

    def append_log(self, collection: str, doc_id: str, entries: list[dict]) -> bool:
        return self._inner.append_log(collection, self._key(collection, doc_id), entries)

    def replace_log(self, collection: str, doc_id: str, entries: list[dict]) -> bool:
        return self._inner.replace_log(collection, self._key(collection, doc_id), entries)

    @contextmanager
    def log_transaction(self, collection: str, doc_id: str) -> Iterator[None]:
        with self._inner.log_transaction(collection, self._key(collection, doc_id)):
            yield

    def version_token(self, collection: str, doc_id: str) -> str:
        return self._inner.version_token(collection, self._key(collection, doc_id))

    def __getattr__(self, name: str):
        return getattr(self._inner, name)
