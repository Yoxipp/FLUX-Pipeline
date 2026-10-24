# runs.py — run records of the Flows (01_ARCHITECTURE §6 "Runs").
#
#   team (and shipped)  <FLUX_ROOT>/CONFIG/extensions/runs/<flow>/<run_id>.json
#   project             <project>/_flux_setup/flows/_runs/<flow>/<run_id>.json
#   perso               <FLUX_ROOT>/USER/<NAME>/flows/_runs/<flow>/<run_id>.json
#
# run_id = %Y%m%dT%H%M%S_<USER>_<6hex> (shape of activity_writer._make_id): the
# file names sort by start time. The engine rewrites the record during the run
# (1 write per second at most, temp file + os.replace) so another machine can
# follow it. Retention (proposition 01 §6): 200 runs per flow (20 dry runs),
# 200 log lines per node, 1 KB per link value; purged when a run closes.
# A record left "running" by a previous backend of this host reads "interrupted".

from __future__ import annotations

import json
import os
import socket
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from flux_flows.model import NAME_RE

RUN_STATUSES = ("queued", "running", "ok", "error", "cancelled", "interrupted", "skipped", "refused")
NODE_STATES = ("idle", "running", "ok", "error", "error_handled", "skipped", "cancelled")
LIVE_STATUSES = ("queued", "running")

KEEP_REAL = 200
KEEP_DRY = 20
MAX_LOGS_PER_NODE = 200
MAX_VALUE_BYTES = 1024
PREVIEW_CHARS = 200

SUMMARY_KEYS = ("run_id", "flow", "scope", "project", "version", "draft", "mode", "status", "trigger",
                "user", "host", "started", "ended", "duration_ms", "error")


def make_run_id(user: Optional[str]) -> str:
    who = "".join(c for c in (user or "UNKNOWN") if c.isalnum() or c in "-_") or "UNKNOWN"
    return f"{datetime.now().strftime('%Y%m%dT%H%M%S')}_{who}_{uuid.uuid4().hex[:6]}"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def runs_dir(scope: str, *, project: Optional[str] = None, user: Optional[str] = None) -> Optional[Path]:
    """Folder of the run records of *scope*; None when it is unavailable (no FLUX_ROOT)."""
    from flux_flows import locations

    try:
        if scope in ("team", "shipped"):
            return locations.extensions_dir() / "runs"
        if scope == "project" and project:
            return locations.project_flows_dir(project) / "_runs"
        if scope == "perso" and user:
            return locations.user_flows_dir(user) / "_runs"
    except RuntimeError:
        return None
    return None


def new_record(*, run_id: str, flow: str, scope: str, project: Optional[str], version: Optional[int],
               draft: bool, mode: str, trigger: Dict[str, Any], user: Optional[str],
               base_revision: Optional[int] = None) -> Dict[str, Any]:
    return {
        "run_id": run_id, "flow": flow, "scope": scope, "project": project, "version": version,
        "draft": draft, "base_revision": base_revision, "mode": mode, "status": "queued",
        "trigger": trigger, "user": user, "host": socket.gethostname(), "pid": os.getpid(),
        "started": None, "ended": None, "duration_ms": None, "error": None, "issues": [],
        "nodes": {}, "links": {}, "report": [], "nodes_simulated": [],
    }


def preview(value: Any, limit: int = PREVIEW_CHARS) -> str:
    """Short text of a value for the WS and the record (never raises)."""
    try:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = repr(value)
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


def clip_value(value: Any) -> str:
    """Link value kept in the record: 1 KB at most."""
    return preview(value, MAX_VALUE_BYTES)


def add_log(entry: Dict[str, Any], line: Dict[str, Any]) -> None:
    logs = entry.setdefault("logs", [])
    if len(logs) < MAX_LOGS_PER_NODE:
        logs.append(line)
    elif len(logs) == MAX_LOGS_PER_NODE:
        logs.append({"level": "warn", "text": f"logs tronques a {MAX_LOGS_PER_NODE} lignes"})


def record_path(folder: Path, flow: str, run_id: str) -> Path:
    if not NAME_RE.match(flow or ""):
        raise ValueError(f"nom de flow invalide '{flow}'")
    return Path(folder) / flow / f"{run_id}.json"


def write_record(folder: Optional[Path], record: Dict[str, Any]) -> Optional[Path]:
    """Atomic write (temp file + os.replace). No folder = the record stays in memory."""
    if folder is None:
        return None
    path = record_path(folder, record["flow"], record["run_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".flux_tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(record, fh, ensure_ascii=False, indent=1, default=str)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def _read(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("status") in LIVE_STATUSES and data.get("host") == socket.gethostname() \
            and data.get("pid") != os.getpid():
        # Left running by a previous backend of this machine (crash, killed sidecar).
        data["status"] = "interrupted"
        data["error"] = data.get("error") or "backend arrete pendant le run"
        try:
            write_record(path.parent.parent, data)
        except (OSError, ValueError):
            pass
    return data


def summary(record: Dict[str, Any]) -> Dict[str, Any]:
    return {k: record.get(k) for k in SUMMARY_KEYS}


def purge(folder: Optional[Path], flow: str, *, keep_real: int = KEEP_REAL, keep_dry: int = KEEP_DRY) -> int:
    """Drop the oldest records of *flow* beyond the retention. Returns the count removed."""
    if folder is None:
        return 0
    flow_dir = Path(folder) / flow
    if not flow_dir.is_dir():
        return 0
    removed = 0
    kept = {"real": 0, "dry": 0}
    for path in sorted(flow_dir.glob("*.json"), reverse=True):   # newest first
        data = _read(path)
        mode = (data or {}).get("mode") if (data or {}).get("mode") in kept else "real"
        kept[mode] += 1
        if kept[mode] > (keep_dry if mode == "dry" else keep_real):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def trigger_matches(record: Dict[str, Any], event: str) -> bool:
    trigger = record.get("trigger") or {}
    return event in (trigger.get("event"), trigger.get("button"))


def list_runs(folders: Iterable[Optional[Path]], *, flow: Optional[str] = None, status: Optional[str] = None,
              mode: Optional[str] = None, scope: Optional[str] = None, event: Optional[str] = None,
              limit: int = 50) -> List[Dict[str, Any]]:
    """Run summaries, newest first. *event*: the start node id or the page button_id (P7)."""
    paths: List[Path] = []
    for folder in folders:
        if folder is None or not Path(folder).is_dir():
            continue
        flow_dirs = [Path(folder) / flow] if flow else [d for d in Path(folder).iterdir() if d.is_dir()]
        for d in flow_dirs:
            if d.is_dir():
                paths.extend(d.glob("*.json"))
    out: List[Dict[str, Any]] = []
    for path in sorted(paths, key=lambda p: p.name, reverse=True):
        data = _read(path)
        if data is None:
            continue
        if (status and data.get("status") != status) or (mode and data.get("mode") != mode) \
                or (scope and data.get("scope") != scope) or (event and not trigger_matches(data, event)):
            continue
        out.append(summary(data))
        if len(out) >= limit:
            break
    return out


def find_run(folders: Iterable[Optional[Path]], run_id: str) -> Optional[Dict[str, Any]]:
    """Full record of *run_id* from the given folders."""
    if not run_id or "/" in run_id or "\\" in run_id or ".." in run_id:
        return None
    for folder in folders:
        if folder is None or not Path(folder).is_dir():
            continue
        for path in Path(folder).glob(f"*/{run_id}.json"):
            data = _read(path)
            if data is not None:
                return data
    return None
