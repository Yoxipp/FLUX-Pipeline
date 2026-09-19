# import_tracking.py — which DCC imports are behind their published file (X4, ADR 0017).
#
# A FLUX import in Maya carries a tag (dcc/maya/maya_update.py): project, the project-
# relative published file, its stamp at import time and the mode. An import of a LAST
# file follows new publishes; an import of a vNNN file is frozen on purpose.

from __future__ import annotations

import re
from pathlib import Path

_FROZEN_RE = re.compile(r"(^|[_/\\])v\d{3,}([_./\\]|$)")


def source_stamp(path: str | Path) -> str:
    """State of a published file: changes when its LAST is rewritten ("" when missing)."""
    try:
        st = Path(path).stat()
    except OSError:
        return ""
    return f"{st.st_mtime_ns}:{st.st_size}"


def is_frozen(rel: str) -> bool:
    """True for a file inside a version folder or named after a version (vNNN)."""
    return bool(_FROZEN_RE.search(str(rel).replace("\\", "/")))


def plan_updates(items: list[dict], project_paths: dict[str, Path]) -> list[dict]:
    """Status of every tagged import: {"node", "project", "source", "mode", "status", "stamp"}.

    status: "update" (the published file changed), "current", "frozen" (vNNN import),
    "missing" (published file or project gone)."""
    out = []
    for item in items:
        rel = str(item.get("source") or "")
        project = project_paths.get(str(item.get("project") or ""))
        entry = {k: item.get(k, "") for k in ("node", "project", "source", "mode")}
        path = project / rel if project is not None and rel else None
        stamp = source_stamp(path) if path is not None else ""
        if not stamp:
            status = "missing"
        elif is_frozen(rel):
            status = "frozen"
        elif stamp != str(item.get("stamp") or ""):
            status = "update"
        else:
            status = "current"
        entry.update(status=status, stamp=stamp)
        out.append(entry)
    return out


def summary(plan: list[dict], done: int, failed: list[str]) -> str:
    """One line for the Maya view message (no em dash, the maintainer)."""
    if not plan:
        return "Aucun import FLUX dans la scene"
    counts = {s: sum(1 for p in plan if p["status"] == s) for s in ("update", "current", "frozen", "missing")}
    parts = [f"{done} mis a jour" if done else "rien a mettre a jour"]
    if counts["current"]:
        parts.append(f"{counts['current']} deja a jour")
    if counts["frozen"]:
        parts.append(f"{counts['frozen']} figes (vNNN)")
    if counts["missing"]:
        parts.append(f"{counts['missing']} introuvables")
    if failed:
        parts.append(f"{len(failed)} en echec : " + ", ".join(failed[:3]))
    return "Imports FLUX : " + ", ".join(parts)
