# disk_usage.py — walk DOSSIER_PROJETS and list the heaviest files.
#
# A simple disk manager: scan the workspace, size every file, return the
# heaviest N and the total per project. No caching, no daemon — a plain
# rglob over the tree; on OneDrive / network shares the walk is slower
# but still bounded (the projects dir is capped by convention).

from __future__ import annotations

import os
from pathlib import Path

from core.logger import get_logger
from core.paths import get_projects_dir

log = get_logger(__name__)


def _iter_files(root: Path):
    """Yield every regular file under *root*, best-effort (skips unreadable dirs)."""
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        for name in filenames:
            full = Path(dirpath) / name
            try:
                st = full.stat()
            except OSError:
                continue
            yield full, st


def scan(project: str | None = None, limit: int = 200) -> dict:
    """Return heaviest files under DOSSIER_PROJETS (or one project).

    {
      "root":       str,            # scanned root
      "total_bytes":int,            # sum of all files scanned
      "file_count": int,
      "top_files":  [{"rel", "project", "size", "mtime"}...],  # sorted desc, up to *limit*
      "by_project": [{"project", "size", "file_count"}...],    # only when scanning all
    }
    """
    projects_dir = get_projects_dir()
    if project:
        root = projects_dir / project
    else:
        root = projects_dir
    if not root.exists():
        return {"root": str(root), "total_bytes": 0, "file_count": 0, "top_files": [], "by_project": []}

    top: list[tuple[int, str, str, float]] = []  # (size, rel, project, mtime)
    total = 0
    count = 0
    by_project: dict[str, list[int]] = {}
    projects_dir_resolved = projects_dir.resolve()
    for full, st in _iter_files(root):
        size = int(st.st_size)
        total += size
        count += 1
        try:
            rel = full.resolve().relative_to(projects_dir_resolved)
        except (ValueError, OSError):
            rel = Path(full.name)
        rel_posix = rel.as_posix()
        proj = rel.parts[0] if rel.parts else ""
        if proj:
            agg = by_project.setdefault(proj, [0, 0])
            agg[0] += size
            agg[1] += 1
        top.append((size, rel_posix, proj, float(st.st_mtime)))
        # Cap the heap-ish list at 4x limit so a huge workspace does not accumulate
        # every file in memory; trim by size and keep going.
        if len(top) > limit * 4:
            top.sort(key=lambda x: x[0], reverse=True)
            top = top[:limit]

    top.sort(key=lambda x: x[0], reverse=True)
    top = top[:limit]
    by_project_list = [
        {"project": p, "size": v[0], "file_count": v[1]}
        for p, v in sorted(by_project.items(), key=lambda kv: kv[1][0], reverse=True)
    ]
    return {
        "root":        str(root),
        "total_bytes": total,
        "file_count":  count,
        "top_files":   [{"rel": r, "project": pr, "size": s, "mtime": m} for (s, r, pr, m) in top],
        "by_project":  [] if project else by_project_list,
    }
