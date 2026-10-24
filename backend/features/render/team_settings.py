# Per-project render (Tractor) team settings stored in render.json beside project.json.
# Keys are stable (ADR 0004): never rename them, only add new ones.
from __future__ import annotations

import copy
import os
import re
from pathlib import Path

from core import paths
from core.json_manager import read_json, write_json
from features.render import farm_targets, studio_env

# 2 (2026-10-23): default priority 100 -> 1. A v1 file holding 100 had the old default, not a choice.
SCHEMA_VERSION = 2
_OLD_DEFAULT_PRIORITY = 100
# Tractor: a higher number goes first (tq chpri help). Every job starts at 1: same as everyone.
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
    "renderer": "",                # "" = choose at launch (studio environment may set one)
    "freeze_by_default": True,
    # Scheduled job ("Lancer a"): freeze when the render starts (on the blade) or at submit (2026-10-23).
    "freeze_when": "start",
    # Houdini on the blades: its embedded python + pxr freeze at start (no Houdini license).
    # Empty = the studio environment value; still empty => freeze at start is refused (require_houdini).
    "houdini_path": "",
    # RenderMan denoise after the render: denoise_batch on the blades, crossframe by default.
    # Empty = the studio environment value; still empty => denoise is refused (require_denoise).
    "denoise_path": "",
    "denoise_crossframe": True,
    # Night window off by default (2026-10-22): opt-in in the advanced settings.
    "schedule": {"enabled": False, "start": "18:00", "end": "08:00", "kill_at_end": False},
    "service_karma": "",
    "service_renderman": "",
    "envkeys": [],
    "husk_path": "",               # empty => environment, then "husk" from the blade PATH
    "bridge_python": "",           # Tractor's Python 2.7
    "bridge_script": "",
    "engine": "",                  # host:port, empty => TRACTOR_ENGINE of the machine
    "engine_user": "",             # engine login, empty => environment, then the FLUX user name
    # Network folder of the engine's limits.config (UNC). Only the locked farm screen writes there.
    "engine_config_dir": "",
    # Real farm by default (validated by an echo job, 2026-10-23, the maintainer); simulation stays opt-in.
    "dry_run": False,
    # Farm throttling (2026-10-23). percent 0 = off; "of" = alive blades or blades free right now.
    "job_share": {"percent": 0, "of": "alive"},   # default per-job share, overridable at submit
    # Kept for old render.json files, never applied since 2026-10-23 (the engine's Shares decide).
    "team_cap": {"percent": 0, "of": "alive"},
    "host_groups": {},             # team machine groups {"name": ["PC01", ...]}
    "exclude_hosts": [],           # never render on these machines
}
_SHARE_KEYS = ("job_share", "team_cap")
_OBJECT_KEYS = ("schedule",) + _SHARE_KEYS

RENDERERS = ("karma", "renderman")
# Settings the studio environment can provide: stored in render.json = the project's own choice,
# otherwise the environment value (precedence: render.json > studio environment > empty).
ENV_BACKED = ("renderer", "priority", "houdini_path", "denoise_path", "husk_path", "bridge_python", "engine",
              "engine_user", "engine_config_dir", "service_karma", "service_renderman", "envkeys")
# Environment values the render code reads but render.json never stores.
ENV_ONLY = ("blade_tractor_python", "render_tag", "default_share", "denoise_tag", "room_pattern",
            "forbid_drive_letters")
FREEZE_WHEN = ("start", "submit")
# Shipped beside this module (scripts/backend.spec copies it in frozen mode).
BUNDLED_BRIDGE = Path(__file__).resolve().parent / "bridge" / "flux_tractor_bridge.py"
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_STR_KEYS = (
    "tractor_project", "service_karma", "service_renderman",
    "husk_path", "bridge_python", "bridge_script", "engine", "engine_user", "engine_config_dir",
)
_BOOL_KEYS = ("freeze_by_default", "dry_run", "denoise_crossframe")


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
        if value != "" and value not in RENDERERS:
            raise ValueError(f"renderer must be empty or one of: {', '.join(RENDERERS)}")
        return value
    if key == "freeze_when":
        if value not in FREEZE_WHEN:
            raise ValueError(f"freeze_when must be one of: {', '.join(FREEZE_WHEN)}")
        return value
    if key == "houdini_path":
        if not isinstance(value, str):
            raise ValueError("houdini_path must be the Houdini install folder of the blades (or empty)")
        return value.strip().replace("\\", "/").rstrip("/")
    if key == "denoise_path":
        if not isinstance(value, str):
            raise ValueError("denoise_path must be denoise_batch.exe on the blades (or empty)")
        return value.strip().replace("\\", "/")
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


def _raw(project_name: str, path=None) -> dict:
    raw = read_json(_resolve(project_name, path))
    if not isinstance(raw, dict):
        return {}
    if raw.get("schema_version", 1) < 2 and raw.get("priority") == _OLD_DEFAULT_PRIORITY:
        raw = {k: v for k, v in raw.items() if k != "priority"}  # the old default, not a choice
        raw["priority"] = DEFAULT_PRIORITY
        raw["_priority_migrated"] = True
    return raw


def read_settings(project_name: str, path=None) -> dict:
    """Stored settings merged over DEFAULTS. Never raises on bad content."""
    raw = _raw(project_name, path)
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


def stored_keys(project_name: str, path=None) -> set:
    """Environment-backed settings this project's render.json sets itself (non-empty valid value)."""
    raw = _raw(project_name, path)
    if raw.pop("_priority_migrated", False):
        raw.pop("priority", None)
    stored = set()
    for key in ENV_BACKED:
        if key not in raw:
            continue
        try:
            value = _check_value(key, raw[key])
        except ValueError:
            continue
        if value not in ("", []):
            stored.add(key)
    return stored


def write_settings(project_name: str, patch: dict, path=None) -> dict:
    """Validate and merge *patch* into the stored settings. Raises ValueError.

    An environment-backed key is written only if the project already stores it or the patch sets
    it to something other than the studio value, so the project keeps following the environment.
    """
    if not isinstance(patch, dict):
        raise ValueError("settings patch must be an object")
    target = _resolve(project_name, path)
    merged = read_settings(project_name, path)
    stored = stored_keys(project_name, path)
    env_farm = studio_env.farm()
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
    out = copy.deepcopy(merged)
    for key in ENV_BACKED:
        if key in stored:
            continue
        follows_env = key not in clean or clean[key] in ("", []) or clean[key] == env_farm.get(key)
        if follows_env:
            out.pop(key, None)  # not the project's own choice
            merged[key] = copy.deepcopy(DEFAULTS[key])
    if not write_json(target, out):
        raise ValueError("could not write render settings")
    return merged


def effective_settings(project_name: str, path=None) -> dict:
    """Settings the render code uses: render.json > studio environment > empty.

    Adds the environment-only values (blade_tractor_python, render_tag, default_share, denoise_tag,
    room_pattern, forbid_drive_letters) and value_sources {key: "project" | "studio" | ""}.
    """
    settings = read_settings(project_name, path)
    stored = stored_keys(project_name, path)
    env_farm = studio_env.farm()
    sources: dict = {}
    for key in ENV_BACKED:
        if key in stored:
            sources[key] = "project"
        elif env_farm.get(key) not in ("", [], None, DEFAULTS[key]):
            settings[key] = copy.deepcopy(env_farm[key])
            sources[key] = "studio"
        else:
            sources[key] = ""
    for key in ENV_ONLY:
        settings[key] = env_farm[key]
    if not settings["tractor_project"]:
        settings["tractor_project"] = project_name
    if not settings["bridge_script"]:
        settings["bridge_script"] = str(BUNDLED_BRIDGE)
    # Machine default: the Tractor client sets TRACTOR_ENGINE.
    if not settings["engine"]:
        settings["engine"] = os.environ.get("TRACTOR_ENGINE", "").strip()
    if not settings["husk_path"]:
        settings["husk_path"] = "husk"  # from the blade PATH
    settings["value_sources"] = sources
    return settings


def require_houdini(settings: dict) -> str:
    """Houdini folder of the blades, needed by freeze at start. Raises ValueError (French, names the setting)."""
    if not settings.get("houdini_path"):
        raise ValueError("Gel au demarrage impossible : le dossier Houdini des blades (reglage houdini_path) "
                         "n'est pas renseigne. Le renseigner dans Avance ou dans l'environnement du studio.")
    if not settings.get("blade_tractor_python"):
        raise ValueError("Gel au demarrage impossible : le Python de Tractor sur les blades "
                         "(reglage blade_tractor_python) n'est pas renseigne dans l'environnement du studio.")
    return settings["houdini_path"]


def require_denoise(settings: dict) -> str:
    """denoise_batch of the blades. Raises ValueError (French, names the setting)."""
    if not settings.get("denoise_path"):
        raise ValueError("Denoise impossible : le chemin de denoise_batch sur les blades (reglage denoise_path) "
                         "n'est pas renseigne. Le renseigner dans Avance ou dans l'environnement du studio.")
    return settings["denoise_path"]


def priority_warning(settings: dict) -> str | None:
    """Short warning when priority is above the default (it impacts other teams)."""
    priority = settings.get("priority", DEFAULT_PRIORITY)
    if _is_int(priority) and priority > DEFAULT_PRIORITY:
        return (f"Priorite {priority} au-dessus de la priorite par defaut ({DEFAULT_PRIORITY}) : "
                "vos jobs passent avant ceux des autres equipes.")
    return None
