# nuke_publish.py — ingest a Nuke Write node's output into the FLUX layout (V6 B1).
#
# Level 2 publish: FLUX does NOT re-render (Tractor owns rendering). It reads the
# active Write node's output path from Nuke, then ingests that already-rendered
# file under FLUX naming/versioning via publish_core.publish_file.
#
# The Nuke-side snippet is a constant string (unit-testable); publish_from_nuke
# wires the bridge to the existing publisher.

from __future__ import annotations

from pathlib import Path

from core.logger import get_logger
from dcc.nuke.client import nuke_client

log = get_logger(__name__)

# Runs inside Nuke: pick the selected Write node, else the first Write in the
# script, and set `result` to its resolved file path (or None when there is none).
# nuke.filename() expands the Write's file knob to a concrete path.
ACTIVE_WRITE_PATH_CODE = "\n".join([
    "_w = None",
    "for _n in nuke.selectedNodes():",
    "    if _n.Class() == 'Write':",
    "        _w = _n",
    "        break",
    "if _w is None:",
    "    _ws = nuke.allNodes('Write')",
    "    _w = _ws[0] if _ws else None",
    "result = None if _w is None else nuke.filename(_w)",
])


def get_active_write_path() -> dict:
    """Return {ok, path} for the active Write node, or {ok: False, error}."""
    res = nuke_client.run(ACTIVE_WRITE_PATH_CODE)
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error", "Nuke run failed")}
    path = res.get("result")
    if not path:
        return {"ok": False, "error": "No Write node found in the Nuke script"}
    return {"ok": True, "path": path}


def publish_from_nuke(
    project: str,
    description: str = "",
    user: str = "unknown",
    target_name: str | None = None,
) -> dict:
    """Ingest the active Write node's output into the FLUX layout.

    Returns {ok, path} with the published LAST path, or {ok: False, error}.
    Single-file for now; multi-frame EXR sequences are a follow-up (they need the
    sequence-aware publish path, not this single-file ingest).
    """
    from core.paths import get_project_path
    from features.publisher.publish_core import publish_file

    wp = get_active_write_path()
    if not wp.get("ok"):
        return wp

    source = Path(wp["path"])
    if not source.exists():
        return {"ok": False, "error": f"Write output not found on disk: {source}"}

    project_path = get_project_path(project)
    dest = publish_file(source, project_path, description, user, project, target_name)
    if dest is None:
        return {"ok": False, "error": "Publish failed (unresolvable FLUX name?)"}
    return {"ok": True, "path": str(dest)}
