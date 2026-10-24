# config.py — the dispatcher config of the pipe (ADR 0067).
#
# CONFIG/dispatcher.json (pipe, the whole team) overridden key by key by
# <project>/_flux_setup/dispatcher.json. No file = backend "local". Keys are stable
# (ADR 0004): never rename them, only add new ones. The Tractor connection settings stay
# in the project render.json (ADR 0015): one source for Tractor.

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, Optional

FILE_NAME = "dispatcher.json"
SCHEMA_VERSION = 1
BACKENDS = ("local", "tractor")

# The only executables a job may start, per backend (a white list: no shell, no free command).
DEFAULT_PROGRAMS: Dict[str, Dict[str, str]] = {
    "husk": {"local": "husk", "tractor": "husk"},
    "hython": {"local": "hython", "tractor": "hython"},
    "mayapy": {"local": "mayapy", "tractor": "mayapy"},
}

DEFAULTS: Dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "backend": "local",
    "local": {"max_parallel": 2},
    "programs": DEFAULT_PROGRAMS,
    "priority": 100,
    "chunk_size": 5,
}


class ConfigError(ValueError):
    """The dispatcher config is wrong. The message says which file and key."""


def pipe_path() -> Optional[Path]:
    from core import paths

    try:
        return paths.get_config_dir() / FILE_NAME
    except Exception:  # noqa: BLE001 - no FLUX_ROOT (tests, first launch): defaults only
        return None


def project_path_of(project: Optional[Path]) -> Optional[Path]:
    if not project:
        return None
    from core.project_setup import setup_path

    return setup_path(Path(project), FILE_NAME)


def _read(path: Optional[Path]) -> Dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    from core.json_manager import read_json

    data = read_json(path)
    if not isinstance(data, dict):
        raise ConfigError(f"{path} : un objet JSON est attendu")
    return data


def _merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    """Key by key; the dict sections (local, programs and each program) one level deeper."""
    out = copy.deepcopy(base)
    for key, value in over.items():
        if key == "programs" and isinstance(value, dict):
            progs = out.setdefault("programs", {})
            for name, by_backend in value.items():
                if isinstance(by_backend, dict):
                    progs[name] = {**progs.get(name, {}), **{k: str(v) for k, v in by_backend.items()}}
        elif isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = {**out[key], **value}
        else:
            out[key] = value
    return out


def _check(cfg: Dict[str, Any], where: str) -> Dict[str, Any]:
    if cfg.get("backend") not in BACKENDS:
        raise ConfigError(f"{where} : backend `{cfg.get('backend')}` inconnu ({', '.join(BACKENDS)})")
    try:
        cfg["local"]["max_parallel"] = max(1, int(cfg["local"].get("max_parallel", 2)))
        cfg["priority"] = int(cfg.get("priority", 100))
        cfg["chunk_size"] = max(1, int(cfg.get("chunk_size", 5)))
    except (TypeError, ValueError, KeyError) as exc:
        raise ConfigError(f"{where} : valeur invalide ({exc})") from None
    return cfg


def load(project: Optional[Path] = None) -> Dict[str, Any]:
    """Effective config for *project* (its folder), else the pipe config alone."""
    pipe, proj = pipe_path(), project_path_of(project)
    cfg = _merge(DEFAULTS, _read(pipe))
    cfg = _merge(cfg, _read(proj))
    return _check(cfg, str(proj if proj and proj.is_file() else pipe or "dispatcher.json"))


def program(cfg: Dict[str, Any], name: str, backend: str) -> str:
    """The executable of *name* for *backend*; a program not declared = refused."""
    entry = (cfg.get("programs") or {}).get(name)
    if not isinstance(entry, dict) or not entry.get(backend):
        declared = ", ".join(sorted(cfg.get("programs") or {})) or "aucun"
        raise ConfigError(f"Programme `{name}` non autorise pour le backend {backend} : declare-le dans `programs` "
                          f"de CONFIG/dispatcher.json (declares : {declared})")
    return str(entry[backend])
