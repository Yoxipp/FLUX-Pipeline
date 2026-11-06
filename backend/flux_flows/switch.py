# switch.py - publish v1 / v2 of a project (ADR 0070, P8).
#
# One choice per project, "publish_engine" in <project>/project.json (project advanced
# settings): "v1" (default, key absent) = the current path of each POST /dcc/<soft>/publish
# route (v1 engine for Maya / Houdini, dcc/* functions for the others, FLUX_LEGACY_PUBLISH
# untouched below it); "v2" = the route runs the shipped flow publish_<soft>. Read at each
# publish, so the switch flips without a restart. The DCC bridges are the same for both.
# Temporary: removed once v2 is validated live on every soft (ADR 0070 §6).

from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.logger import get_logger

log = get_logger(__name__)

ENGINES = ("v1", "v2")
DEFAULT_ENGINE = "v1"

# Softs that have a shipped publish_<soft> flow (Photoshop has none: always v1).
FLOW_SOFTS = ("maya", "houdini", "nuke", "painter", "designer", "mari", "marvelous", "zbrush")


def publish_engine(project: Optional[str]) -> str:
    """"v1" or "v2" for *project*; anything unreadable or unknown is v1."""
    name = str(project or "").strip()
    if not name:
        return DEFAULT_ENGINE
    try:
        from core.paths import get_project_path
        from features.folder_manager.project_config import read_project_config

        cfg = read_project_config(Path(get_project_path(name))) or {}
    except Exception as exc:  # noqa: BLE001 - a broken project.json never blocks a publish
        log.warning("publish_engine: project.json of %s unreadable, v1 used: %s", name, exc)
        return DEFAULT_ENGINE
    value = str(cfg.get("publish_engine") or DEFAULT_ENGINE).strip().lower()
    return value if value in ENGINES else DEFAULT_ENGINE


def flows_publish_enabled(project: Optional[str], soft: str) -> bool:
    """True when a publish of *soft* in *project* must go through publish_<soft> (v2)."""
    return soft.strip().lower() in FLOW_SOFTS and publish_engine(project) == "v2"
