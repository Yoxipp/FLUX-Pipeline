# pipeline_index.py - on-disk snapshot of a project tree (ADR 0093).
#
# <project>/_flux_setup/pipeline_index.json holds the folders, files and sizes seen
# by the last "Recharger", with its date and author. It is written only on that
# explicit request, atomically (tmp + os.replace).
#
# RULE: the index is a possibly stale snapshot, for display and search only. It is
# NEVER used to decide a write (next version number, LAST, publish, deletion):
# those always read the live filesystem. A reader that gets None must walk the disk.

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

from core.constants import SETUP_DIR
from core.logger import get_logger

log = get_logger(__name__)

INDEX_NAME = "pipeline_index.json"
VERSION = 1


def index_path(project: str | Path) -> Path:
    return Path(project) / SETUP_DIR / INDEX_NAME


def build(project: str | Path, author: str) -> dict:
    """Walk *project* and return its index (nothing is written).

    "dirs": project-relative posix paths; "files": [rel, size, mtime]."""
    root = Path(project)
    started = time.time()
    dirs: list[str] = []
    files: list[list] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath).relative_to(root)
        dirs.extend((here / name).as_posix() for name in dirnames)
        for name in filenames:
            if here.as_posix() == SETUP_DIR and name.startswith(INDEX_NAME):
                continue                                 # the index and its tmp files
            try:
                st = os.stat(os.path.join(dirpath, name))
            except OSError:
                continue
            files.append([(here / name).as_posix(), int(st.st_size), float(st.st_mtime)])
    return {"version": VERSION, "project": root.name, "scanned_at": started,
            "scanned_by": author, "dirs": dirs, "files": files}


def write(project: str | Path, index: dict) -> None:
    """Replace the index in one step; on failure the previous one stays (OSError raised)."""
    target = index_path(project)
    target.parent.mkdir(exist_ok=True)                    # never creates the project itself
    tmp = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def load(project: str | Path) -> dict | None:
    """The last index of *project*, None if missing, unreadable or malformed."""
    try:
        data = json.loads(index_path(project).read_text(encoding="utf-8"))
        if data["version"] != VERSION:
            return None
        valid = (isinstance(data["scanned_at"], (int, float))
                 and isinstance(data["scanned_by"], str)
                 and isinstance(data["dirs"], list) and all(isinstance(d, str) for d in data["dirs"])
                 and isinstance(data["files"], list)
                 and all(isinstance(r, str) and isinstance(s, int) and isinstance(m, (int, float))
                         for r, s, m in data["files"]))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError, KeyError) as exc:
        log.warning("pipeline index of %s unreadable: %s", Path(project).name, exc)
        return None
    return data if valid else None
