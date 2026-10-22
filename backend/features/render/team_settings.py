# Per-project render (Tractor) team settings stored in render.json beside project.json.
# Keys are stable (ADR 0004): never rename them, only add new ones.
from __future__ import annotations

import copy
import re
from pathlib import Path

from core import paths
from core.json_manager import read_json, write_json

SCHEMA_VERSION = 1
DEFAULT_PRIORITY = 100

DEFAULTS: dict = {
    "schema_version": SCHEMA_VERSION,
    "tractor_project": "",        # empty => FLUX project name (see effective_settings)
    "priority": DEFAULT_PRIORITY,  # 1..10000
    "maxactive": 0,                # 0 = no cap
    "chunk_size": 5,
    "renderer": "karma",
    "freeze_by_default": True,
    "schedule": {"enabled": True, "start": "18:00", "end": "08:00", "kill_at_end": True},
    "service_karma": "",
    "service_renderman": "",
    "envkeys": [],
    "husk_path": "husk",
    "bridge_python": "",           # Tractor's Python 2.7
    "bridge_script": "",
    "engine": "",                  # host:port
    "dry_run": True,               # stays True until school phase 0 is done
}

RENDERERS = ("karma", "renderman")
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_STR_KEYS = (
    "tractor_project", "service_karma", "service_renderman",
    "husk_path", "bridge_python", "bridge_script", "engine",
)
_BOOL_KEYS = ("freeze_by_default", "dry_run")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_schedule(value) -> dict:
    if not isinstance(value, dict):
        raise ValueError("schedule must be an object")
    allowed = set(DEFAULTS["schedule"])
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"unknown schedule key: {', '.join(unknown)}")
    out = dict(DEFAULTS["schedule"])
    out.update(value)
    for key in ("enabled", "kill_at_end"):
        if not isinstance(out[key], bool):
            raise ValueError(f"schedule.{key} must be true or false")
    for key in ("start", "end"):
        if not isinstance(out[key], str) or not _HHMM.match(out[key]):
            raise ValueError(f"schedule.{key} must be HH:MM (00:00 to 23:59)")
    return out


def _check_value(key: str, value):
    """Return the normalized value or raise ValueError with a readable message."""
    if key == "schema_version":
        if value != SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SCHEMA_VERSION}")
        return SCHEMA_VERSION
    if key == "priority":
        if not _is_int(value) or not 1 <= value <= 10000:
            raise ValueError("priority must be an integer between 1 and 10000")
        return value
    if key == "maxactive":
        if not _is_int(value) or value < 0:
            raise ValueError("maxactive must be an integer >= 0 (0 = no cap)")
        return value
    if key == "chunk_size":
        if not _is_int(value) or value < 1:
            raise ValueError("chunk_size must be an integer >= 1")
        return value
    if key == "renderer":
        if value not in RENDERERS:
            raise ValueError(f"renderer must be one of: {', '.join(RENDERERS)}")
        return value
    if key in _BOOL_KEYS:
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")
        return value
    if key == "schedule":
        return _check_schedule(value)
    if key == "envkeys":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValueError("envkeys must be a list of strings")
        return list(value)
    if key in _STR_KEYS:
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        return value.strip()
    raise ValueError(f"unknown setting: {key}")


def _resolve(project_name: str, path) -> Path:
    return Path(path) if path is not None else paths.get_project_render_path(project_name)


def read_settings(project_name: str, path=None) -> dict:
    """Stored settings merged over DEFAULTS. Never raises on bad content."""
    raw = read_json(_resolve(project_name, path))
    if not isinstance(raw, dict):
        raw = {}
    out = copy.deepcopy(DEFAULTS)
    for key in DEFAULTS:
        if key not in raw:
            continue
        if key == "schedule" and isinstance(raw[key], dict):
            # per sub-key fallback so one bad field keeps the others
            sched = dict(DEFAULTS["schedule"])
            for sub, default in DEFAULTS["schedule"].items():
                if sub in raw[key]:
                    try:
                        sched[sub] = _check_schedule({**DEFAULTS["schedule"], sub: raw[key][sub]})[sub]
                    except ValueError:
                        sched[sub] = default
            out[key] = sched
            continue
        try:
            out[key] = _check_value(key, raw[key])
        except ValueError:
            pass  # keep default
    return out


def write_settings(project_name: str, patch: dict, path=None) -> dict:
    """Validate and merge *patch* into the stored settings. Raises ValueError."""
    if not isinstance(patch, dict):
        raise ValueError("settings patch must be an object")
    target = _resolve(project_name, path)
    merged = read_settings(project_name, path)
    clean: dict = {}
    for key, value in patch.items():
        if key not in DEFAULTS:
            raise ValueError(f"unknown setting: {key}")
        if key == "schedule" and isinstance(value, dict):
            # partial patch: keep the stored sub-keys it does not name
            value = {**merged["schedule"], **value}
        clean[key] = _check_value(key, value)
    merged.update(clean)
    merged["schema_version"] = SCHEMA_VERSION
    if not write_json(target, merged):
        raise ValueError("could not write render settings")
    return merged


def effective_settings(project_name: str, path=None) -> dict:
    """Settings with tractor_project defaulted to the FLUX project name."""
    settings = read_settings(project_name, path)
    if not settings["tractor_project"]:
        settings["tractor_project"] = project_name
    return settings


def priority_warning(settings: dict) -> str | None:
    """Short warning when priority is above the default (it impacts other teams)."""
    priority = settings.get("priority", DEFAULT_PRIORITY)
    if _is_int(priority) and priority > DEFAULT_PRIORITY:
        return (f"Priorite {priority} au-dessus du defaut ({DEFAULT_PRIORITY}) : "
                "vos jobs passent avant ceux des autres equipes.")
    return None
