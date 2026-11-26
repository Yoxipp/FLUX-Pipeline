# disk_usage.py - heaviest files under DOSSIER_PROJETS, read from the pipeline index.
#
# scan() only reads the per-project index (features/system/pipeline_index.py,
# ADR 0093): it never walks the tree. refresh() walks and rewrites the indexes.
# Display only: nothing here may decide a write.

from __future__ import annotations

import heapq
from pathlib import Path

from core.logger import get_logger
from core.paths import get_projects_dir
from features.system import pipeline_index

log = get_logger(__name__)


def _project_dirs(project: str | None) -> list[Path]:
    """Project folders in scope. A name with a path in it is refused (we write there)."""
    root = get_projects_dir()
    if project:
        if project in (".", "..") or Path(project).name != project:
            return []
        folder = root / project
        return [folder] if folder.is_dir() else []
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir())


def _view(project: str | None, limit: int, indexes: dict[str, dict | None]) -> dict:
    """Disk page payload from {project name: index or None}."""
    root = get_projects_dir()
    present = {name: idx for name, idx in indexes.items() if idx is not None}
    files = ((size, f"{name}/{rel}", name, mtime)
             for name, idx in present.items() for rel, size, mtime in idx["files"])
    top = heapq.nlargest(limit, files, key=lambda f: f[0])
    by_project = [{"project": name, "size": sum(f[1] for f in idx["files"]), "file_count": len(idx["files"])}
                  for name, idx in present.items()]
    by_project.sort(key=lambda p: p["size"], reverse=True)
    # Several projects: show the oldest scan, the one that limits how fresh the page is.
    oldest = min(present.values(), key=lambda i: i["scanned_at"], default=None)
    return {
        "root":        str(root / project if project else root),
        "total_bytes": sum(p["size"] for p in by_project),
        "file_count":  sum(p["file_count"] for p in by_project),
        "top_files":   [{"rel": r, "project": pr, "size": s, "mtime": m} for (s, r, pr, m) in top],
        "by_project":  [] if project else by_project,
        "scanned_at":  oldest["scanned_at"] if oldest else None,
        "scanned_by":  oldest["scanned_by"] if oldest else "",
        "not_indexed": [name for name, idx in indexes.items() if idx is None],
        "errors":      [],
    }


def scan(project: str | None = None, limit: int = 200) -> dict:
    """Heaviest files of DOSSIER_PROJETS (or one project) as of the last refresh."""
    indexes = {p.name: pipeline_index.load(p) for p in _project_dirs(project)}
    return _view(project, limit, indexes)


def refresh(project: str | None = None, limit: int = 200, *, author: str) -> dict:
    """Walk the projects in scope, rewrite their index, return the fresh view."""
    indexes: dict[str, dict | None] = {}
    errors: list[str] = []
    for folder in _project_dirs(project):
        index = pipeline_index.build(folder, author)
        indexes[folder.name] = index
        try:
            pipeline_index.write(folder, index)
        except OSError as exc:
            log.warning("pipeline index of %s not written: %s", folder.name, exc)
            errors.append(f"{folder.name} : index non enregistré ({exc})")
    return {**_view(project, limit, indexes), "errors": errors}
