# Per-project render (Tractor) team settings stored in render.json beside project.json.
# Keys are stable (ADR 0004): never rename them, only add new ones.
from __future__ import annotations

import copy
import os
import re
from pathlib import Path

from core import paths
from core.json_manager import read_json, write_json
from features.render import farm_targets

# 2 (2026-10-23): default priority 100 -> 1. A v1 file holding 100 had the old default, not a choice.
SCHEMA_VERSION = 2
_OLD_DEFAULT_PRIORITY = 100
# Tractor: a higher number goes first (tq chpri help). Every school job is at 1 (2026-10-23): same as everyone.
DEFAULT_PRIORITY = 1

DEFAULTS: dict = {
    "schema_version": SCHEMA_VERSION,
    "tractor_project": "",        # empty => FLUX project name (see effective_settings)
    "priority": DEFAULT_PRIORITY,  # 1..10000
    "maxactive": 0,                # 0 = no cap
    "chunk_size": 5,
    # Per render chunk (2026-10-23): killed past this many minutes (Tractor -maxrunsecs), 0 = no bound;
    # ready again when husk exits with one of these codes (-retryrc), [] = never.
    "max_task_minutes": 0,
    "retry_exit_codes": [],
    "renderer": "renderman",       # 2026-10-23
    "freeze_by_default": True,
    # Scheduled job ("Lancer a"): freeze when the render starts (on the blade) or at submit (2026-10-23).
    "freeze_when": "start",
    # Houdini on the blades (20.5 to 22): its embedded python + pxr freeze at start (no Houdini
    # license, probe job 34027). A blade without it uses its newest Houdini.
    "houdini_path": "C:/Program Files/Side Effects Software/Houdini 20.5.445",
    # Night window off by default (2026-10-22): opt-in in the advanced settings.
    "schedule": {"enabled": False, "start": "18:00", "end": "08:00", "kill_at_end": False},
    "service_karma": "",
    "service_renderman": "",
    "envkeys": [],
    "husk_path": "husk",
    "bridge_python": "",           # Tractor's Python 2.7
    "bridge_script": "",
    "engine": "",                  # host:port, empty => TRACTOR_ENGINE of the machine
    "engine_user": "",             # engine login, empty => "root" (read only for FLUX)
    # Real farm by default since the school echo test (job 34026, 2026-10-23, the maintainer); simulation stays opt-in.
    "dry_run": False,
    # Farm throttling (2026-10-23). percent 0 = off; "of" = alive blades or blades free right now.
    "job_share": {"percent": 0, "of": "alive"},   # default per-job share, overridable at submit
    "team_cap": {"percent": 0, "of": "alive"},    # budget shared by every FLUX job of the team
    "host_groups": {},             # team machine groups {"name": ["ROOM1701", ...]}
    "exclude_hosts": [],           # never render on these machines
}
_SHARE_KEYS = ("job_share", "team_cap")
_OBJECT_KEYS = ("schedule",) + _SHARE_KEYS

RENDERERS = ("karma", "renderman")
FREEZE_WHEN = ("start", "submit")
# Shipped beside this module (scripts/backend.spec copies it in frozen mode).
BUNDLED_BRIDGE = Path(__file__).resolve().parent / "bridge" / "flux_tractor_bridge.py"
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_STR_KEYS = (
    "tractor_project", "service_karma", "service_renderman",
    "husk_path", "bridge_python", "bridge_script", "engine", "engine_user",
)
# Tractor client install on school machines (phase 0, 2026-10-22): its rmanpy.exe is Python 2.7.
TRACTOR_PYTHON_CANDIDATES = (Path(r"C:\Program Files\Pixar\Tractor-2.4\bin\rmanpy.exe"),)
# Same install on every blade (blade service, probe job 34027): starts the freeze-at-start script.
BLADE_TRACTOR_PYTHON = "C:/Program Files/Pixar/Tractor-2.4/bin/rmanpy.exe"
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


def _check_share(key: str, value) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    unknown = sorted(set(value) - set(DEFAULTS[key]))
    if unknown:
        raise ValueError(f"unknown {key} key: {', '.join(unknown)}")
    out = {**DEFAULTS[key], **value}
    if not _is_int(out["percent"]) or not 0 <= out["percent"] <= 100:
        raise ValueError(f"{key}.percent must be an integer between 0 and 100")
    if out["of"] not in farm_targets.SHARE_BASES:
        raise ValueError(f"{key}.of must be one of: {', '.join(farm_targets.SHARE_BASES)}")
    return out


def _check_hosts(key: str, value) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list of machine names")
    return sorted({farm_targets.check_host(str(h).strip()) for h in value if str(h).strip()})


def _check_object(key: str, value) -> dict:
    return _check_schedule(value) if key == "schedule" else _check_share(key, value)


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
    if key == "max_task_minutes":
        if not _is_int(value) or value < 0:
            raise ValueError("max_task_minutes must be an integer >= 0 (0 = no bound)")
        return value
    if key == "retry_exit_codes":
        if not isinstance(value, list) or not all(_is_int(v) and v != 0 for v in value):
            raise ValueError("retry_exit_codes must be a list of non-zero integers (0 = success)")
        return sorted(set(value))
    if key == "chunk_size":
        if not _is_int(value) or value < 1:
            raise ValueError("chunk_size must be an integer >= 1")
        return value
    if key == "renderer":
        if value not in RENDERERS:
            raise ValueError(f"renderer must be one of: {', '.join(RENDERERS)}")
        return value
    if key == "freeze_when":
        if value not in FREEZE_WHEN:
            raise ValueError(f"freeze_when must be one of: {', '.join(FREEZE_WHEN)}")
        return value
    if key == "houdini_path":
        if not isinstance(value, str) or not value.strip():
            raise ValueError("houdini_path must be the Houdini install folder of the blades")
        return value.strip().replace("\\", "/").rstrip("/")
    if key in _BOOL_KEYS:
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")
        return value
    if key in _OBJECT_KEYS:
        return _check_object(key, value)
    if key == "exclude_hosts":
        try:
            return _check_hosts(key, value)
        except ValueError as exc:
            raise ValueError(f"exclude_hosts: {exc}") from None
    if key == "host_groups":
        if not isinstance(value, dict):
            raise ValueError("host_groups must be an object {name: [machines]}")
        groups = {}
        for name, hosts in value.items():
            name = str(name).strip()
            if not name or not farm_targets.check_host(name):
                raise ValueError(f"host_groups: invalid group name '{name}'")
            groups[name] = _check_hosts(f"host_groups.{name}", hosts)
        return dict(sorted(groups.items()))
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
    if raw.get("schema_version", 1) < 2 and raw.get("priority") == _OLD_DEFAULT_PRIORITY:
        raw = {**raw, "priority": DEFAULT_PRIORITY}
    out = copy.deepcopy(DEFAULTS)
    for key in DEFAULTS:
        if key not in raw:
            continue
        if key in _OBJECT_KEYS and isinstance(raw[key], dict):
            # per sub-key fallback so one bad field keeps the others
            obj = dict(DEFAULTS[key])
            for sub, default in DEFAULTS[key].items():
                if sub in raw[key]:
                    try:
                        obj[sub] = _check_object(key, {**DEFAULTS[key], sub: raw[key][sub]})[sub]
                    except ValueError:
                        obj[sub] = default
            out[key] = obj
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
        if key in _OBJECT_KEYS and isinstance(value, dict):
            # partial patch: keep the stored sub-keys it does not name
            value = {**merged[key], **value}
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
    if not settings["bridge_script"]:
        settings["bridge_script"] = str(BUNDLED_BRIDGE)
    # Machine defaults: the Tractor client sets TRACTOR_ENGINE and ships rmanpy.exe.
    if not settings["engine"]:
        settings["engine"] = os.environ.get("TRACTOR_ENGINE", "").strip()
    if not settings["bridge_python"]:
        found = next((p for p in TRACTOR_PYTHON_CANDIDATES if p.is_file()), None)
        settings["bridge_python"] = str(found) if found else ""
    return settings


def priority_warning(settings: dict) -> str | None:
    """Short warning when priority is above the default (it impacts other teams)."""
    priority = settings.get("priority", DEFAULT_PRIORITY)
    if _is_int(priority) and priority > DEFAULT_PRIORITY:
        return (f"Priorite {priority} au-dessus des autres jobs de l'ecole ({DEFAULT_PRIORITY}) : "
                "vos jobs passent avant ceux des autres equipes.")
    return None
