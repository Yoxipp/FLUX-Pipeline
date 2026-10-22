# advanced.py — "Parametres avances" (N8): deep settings behind a typed confirmation.
#
# Two groups:
#   * project settings = <project>/project.json (ADR 0006): fps, resolution, USD units,
#     OCIO, env, LAST storage (ADR 0017). Only these keys can be written, validated
#     against the schema; project_id / schema_version / created_at never change.
#   * publish switches of this machine (decision D1): texture conform .tx, USD proxy,
#     proxy reduction, portable $FLUX paths. flux_actions.switch reads them from env
#     vars; the page saves a value in the prefs ("advanced_switches") and puts it in
#     the env of the backend right away and at every start. A var set at launch (dev
#     .bat) wins at start; a value saved from the page wins after that.

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from core import config
from core.logger import get_logger

log = get_logger(__name__)

_PREFS_KEY = "advanced_switches"

# name -> (env var, kind)
SWITCHES: dict[str, tuple[str, str]] = {
    "conform_tx":              ("FLUX_CONFORM_TX", "bool"),
    "conform_tx_colorconvert": ("FLUX_CONFORM_TX_COLORCONVERT", "bool"),
    "proxy_usd":               ("FLUX_PROXY_USD", "bool"),
    "proxy_reduction":         ("FLUX_PROXY_REDUCTION", "reduction"),
    "portable_paths":          ("FLUX_PORTABLE_PATHS", "bool"),
    # Publish copy caps of this machine (features/publisher/copy_limits.py).
    "publish_max_parallel":    ("FLUX_PUBLISH_MAX_PARALLEL", "count"),
    "publish_max_mbps":        ("FLUX_PUBLISH_MAX_MBPS", "mbps"),
}

# Env vars present when the backend started (dev .bat, CI): restored when a saved value is cleared.
_launch_env: dict[str, str] = {}


def _current(name: str) -> Any:
    """Effective value, as the publish code sees it right now."""
    from features.publisher import copy_limits
    from flux_actions import switch

    return {
        "conform_tx": switch.conform_tx_enabled,
        "conform_tx_colorconvert": switch.conform_tx_colorconvert,
        "proxy_usd": switch.proxy_usd_enabled,
        "proxy_reduction": switch.proxy_usd_reduction,
        "portable_paths": switch.portable_paths_enabled,
        "publish_max_parallel": copy_limits.max_parallel,
        "publish_max_mbps": copy_limits.max_mbps,
    }[name]()


def _to_env(kind: str, value: Any) -> str:
    if kind == "bool":
        return "1" if value else "0"
    if kind == "count":
        return str(int(value))
    return repr(float(value))


def _check(name: str, value: Any) -> Any:
    if name not in SWITCHES:
        raise ValueError(f"reglage inconnu : {name}")
    kind = SWITCHES[name][1]
    if value is None:
        return None
    if kind == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"{name} : vrai ou faux attendu")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} : nombre attendu")
    if kind == "count":
        if int(value) != value or not 1 <= value <= 64:
            raise ValueError(f"{name} : entier entre 1 et 64 attendu")
        return int(value)
    if kind == "mbps":
        if not 0.0 <= float(value) <= 10000.0:
            raise ValueError(f"{name} : debit entre 0 (desactive) et 10000 Mo/s attendu")
        return float(value)
    if not 0.0 < float(value) < 1.0:
        raise ValueError(f"{name} : nombre entre 0 et 1 (exclus) attendu")
    return float(value)


def _saved() -> dict:
    raw = config.get(_PREFS_KEY) or {}
    return {k: v for k, v in raw.items() if k in SWITCHES} if isinstance(raw, dict) else {}


def apply_saved_switches() -> list[str]:
    """At backend start: put the saved switches in the env, unless set at launch."""
    applied = []
    for env, _kind in SWITCHES.values():
        if env in os.environ:
            _launch_env[env] = os.environ[env]
    for name, value in _saved().items():
        env, kind = SWITCHES[name]
        if env in _launch_env:
            continue
        try:
            os.environ[env] = _to_env(kind, _check(name, value))
            applied.append(name)
        except (TypeError, ValueError) as exc:
            log.warning("Saved switch %s ignored: %s", name, exc)
    return applied


def read_switches() -> dict:
    """{name: {"value", "saved", "env", "source": "page" | "lancement" | "defaut"}}."""
    saved = _saved()
    out = {}
    for name, (env, _kind) in SWITCHES.items():
        if name in saved and os.environ.get(env) == _to_env(SWITCHES[name][1], saved[name]):
            source = "page"
        elif env in _launch_env:
            source = "lancement"
        else:
            source = "defaut"
        out[name] = {"value": _current(name), "saved": saved.get(name), "env": env, "source": source}
    return out


def save_switches(values: dict) -> dict:
    """Save and apply *values* ({name: value, or None to go back to the default})."""
    checked = {name: _check(name, value) for name, value in values.items()}
    saved = _saved()
    for name, value in checked.items():
        env, kind = SWITCHES[name]
        if value is None:
            saved.pop(name, None)
            if env in _launch_env:
                os.environ[env] = _launch_env[env]
            else:
                os.environ.pop(env, None)
        else:
            saved[name] = value
            os.environ[env] = _to_env(kind, value)
    config.set(_PREFS_KEY, saved)
    log.info("Advanced switches saved: %s", saved)
    return read_switches()


# ── project.json ────────────────────────────────────────────────────────────────

PROJECT_KEYS = ("fps", "resolution", "usd", "ocio_config", "env", "storage")


def read_project_settings(project_path: str | Path) -> dict:
    """The editable part of project.json + its id (read only) and the LAST modes."""
    from features.folder_manager.project_config import ensure_project_config
    from features.publisher.last_pointer import DEFAULT_LINK_THRESHOLD_GB, MODES

    data, warnings = ensure_project_config(Path(project_path))
    storage = data.get("storage") if isinstance(data.get("storage"), dict) else {}
    return {
        "project_id": data.get("project_id", ""),
        "values": {
            "fps": data.get("fps"),
            "resolution": data.get("resolution"),
            "usd": {"meters_per_unit": (data.get("usd") or {}).get("meters_per_unit"),
                    "up_axis": (data.get("usd") or {}).get("up_axis")},
            "ocio_config": data.get("ocio_config", ""),
            "env": data.get("env") or {},
            "storage": {"last_mode": storage.get("last_mode") or {},
                        "last_link_threshold_gb": storage.get("last_link_threshold_gb",
                                                              DEFAULT_LINK_THRESHOLD_GB)},
        },
        "last_modes": list(MODES),
        "warnings": warnings,
    }


def _merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict) and key != "env" and key != "last_mode":
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def write_project_settings(project_path: str | Path, patch: dict) -> dict:
    """Merge *patch* (only PROJECT_KEYS) into project.json after validation.
    Raises ValueError with every problem found; the file is untouched then."""
    from core.json_manager import write_json
    from features.folder_manager.project_config import (
        ensure_project_config, project_config_path, validate_project_config,
    )
    from features.publisher.last_pointer import MODES

    unknown = [k for k in patch if k not in PROJECT_KEYS]
    if unknown:
        raise ValueError("reglages non modifiables ici : " + ", ".join(unknown))
    current, _ = ensure_project_config(Path(project_path))
    merged = _merge(current, patch)
    errors = validate_project_config(merged)
    storage = merged.get("storage") if isinstance(merged.get("storage"), dict) else {}
    modes = storage.get("last_mode", {})
    if not isinstance(modes, dict):
        errors.append("storage/last_mode : objet {extension: mode} attendu")
    else:
        errors += [f"storage/last_mode/{ext} : {mode!r} n'est pas un mode ({', '.join(MODES)})"
                   for ext, mode in modes.items() if mode not in MODES]
    threshold = storage.get("last_link_threshold_gb")
    if threshold is not None and (isinstance(threshold, bool) or not isinstance(threshold, (int, float))
                                  or threshold <= 0):
        errors.append("storage/last_link_threshold_gb : nombre positif attendu")
    env = merged.get("env", {})
    if isinstance(env, dict) and any(not isinstance(v, str) for v in env.values()):
        errors.append("env : valeurs texte attendues")
    if errors:
        raise ValueError(" ; ".join(errors))
    if not write_json(project_config_path(Path(project_path)), merged):
        raise ValueError("ecriture de project.json impossible")
    log.info("project.json updated (%s): %s", Path(project_path).name, sorted(patch))
    return read_project_settings(project_path)
