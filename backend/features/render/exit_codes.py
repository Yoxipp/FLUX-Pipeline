# Exit codes seen on the team's FLUX render commands (husk), kept in the project beside render.json,
# so the Advanced tab can propose them for "retry on exit codes" (2026-10-23).
# Keys are stable (ADR 0004): never rename them, only add new ones.
from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional

from core import paths
from core.json_manager import read_json, write_json

SCHEMA_VERSION = 1
STORE_NAME = "render_exit_codes.json"
# What FLUX knows for sure (seen on a real farm); other codes stay unexplained.
KNOWN: Dict[int, str] = {10111: "Tue par Tractor : duree max d'un morceau depassee"}
# A timeout kill is not transient: retrying it would hit the same bound again.
NEVER_PROPOSED = frozenset({10111})
_RENDER_PROGRAMS = ("husk",)
_SEEN_MAX = 5000
_CHECKED_MAX = 500


def store_path(project_name: str, path=None) -> Path:
    return Path(path) if path is not None else paths.get_project_render_path(project_name).with_name(STORE_NAME)


def _empty() -> dict:
    return {"schema_version": SCHEMA_VERSION, "codes": {}, "seen": [], "checked": {}}


def read_store(project_name: str, path=None) -> dict:
    raw = read_json(store_path(project_name, path))
    out = _empty()
    if isinstance(raw, dict):
        for key in ("codes", "checked"):
            if isinstance(raw.get(key), dict):
                out[key] = raw[key]
        if isinstance(raw.get("seen"), list):
            out["seen"] = [s for s in raw["seen"] if isinstance(s, str)]
    return out


def is_render_program(program: str) -> bool:
    name = (program or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name.startswith(_RENDER_PROGRAMS)


def _error_count(job: dict) -> int:
    try:
        return int(job.get("numError") or 0)
    except (TypeError, ValueError):
        return 0


def jobs_to_check(project_name: str, jobs: Iterable[dict], tractor_project: str, path=None,
                  limit: int = 20) -> List[dict]:
    """FLUX jobs of this team whose error count changed since the last check (newest first)."""
    checked = read_store(project_name, path)["checked"]
    todo = []
    for job in jobs:
        meta = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
        projects = job.get("projects") or []
        projects = projects if isinstance(projects, list) else [projects]
        if meta.get("flux_project") != project_name or tractor_project not in projects:
            continue
        errors = _error_count(job)
        if errors and checked.get(str(job.get("jid"))) != errors:
            todo.append(job)
    todo.sort(key=lambda j: int(j.get("jid") or 0), reverse=True)
    return todo[:limit]


def record(project_name: str, jobs: List[dict], invocations: Iterable[dict], path=None) -> int:
    """Count each failed render execution once. Returns how many were new."""
    store = read_store(project_name, path)
    seen = set(store["seen"])
    titles = {j.get("jid"): str(j.get("title") or "") for j in jobs}
    new = 0
    for inv in invocations:
        if not is_render_program(inv.get("program", "")):
            continue
        key = f"{inv.get('jid')}:{inv.get('tid')}:{inv.get('cid')}:{inv.get('stoptime')}"
        if key in seen:
            continue
        seen.add(key)
        store["seen"].append(key)
        entry = store["codes"].setdefault(str(int(inv["rcode"])), {"count": 0})
        entry["count"] = int(entry.get("count") or 0) + 1
        if str(inv.get("stoptime") or "") >= str(entry.get("last_seen") or ""):
            entry.update(last_seen=str(inv.get("stoptime") or ""), last_jid=inv.get("jid"),
                         last_title=titles.get(inv.get("jid"), ""))
        new += 1
    for job in jobs:
        store["checked"][str(job.get("jid"))] = _error_count(job)
    store["seen"] = store["seen"][-_SEEN_MAX:]
    if len(store["checked"]) > _CHECKED_MAX:
        keep = sorted(store["checked"], key=lambda k: int(k) if k.isdigit() else 0)[-_CHECKED_MAX:]
        store["checked"] = {k: store["checked"][k] for k in keep}
    if not write_json(store_path(project_name, path), store):
        raise OSError("could not write render exit codes")
    return new


def suggestions(project_name: str, retry_codes: Optional[Iterable[int]] = None, path=None) -> List[dict]:
    """Codes seen, most frequent first: {code, count, last_seen, last_title, label, active, proposed}."""
    active = set(retry_codes or [])
    out = []
    for key, entry in read_store(project_name, path)["codes"].items():
        try:
            code = int(key)
        except ValueError:
            continue
        out.append({"code": code, "count": int(entry.get("count") or 0),
                    "last_seen": str(entry.get("last_seen") or ""), "last_title": str(entry.get("last_title") or ""),
                    "label": KNOWN.get(code, ""), "active": code in active,
                    "proposed": code not in active and code not in NEVER_PROPOSED})
    return sorted(out, key=lambda s: (-s["count"], s["code"]))
