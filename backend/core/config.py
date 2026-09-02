# config.py — read/write local config.json (next to the exe).
# Contains: workspace, username, last_project, theme, dcc_paths, dcc_ports.
# One file per user-machine install — no shared state on the network drive.

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.constants import (
    THEME_DEFAULT_BG, THEME_DEFAULT_SURFACE,
    THEME_DEFAULT_FG, THEME_DEFAULT_ACCENT,
)
from core.json_manager import read_json, write_json
from core.logger import get_logger
from core.paths import get_config_json_path, get_prefs_path, get_users_dir

log = get_logger(__name__)

# ── Default config structure ──────────────────────────────────────────────────

def _defaults(name: str, workspace: str) -> dict:
    return {
        "workspace":    workspace,
        "username":     name,
        "last_project": None,
        "theme": {
            "bg":      THEME_DEFAULT_BG,
            "surface": THEME_DEFAULT_SURFACE,
            "fg":      THEME_DEFAULT_FG,
            "accent":  THEME_DEFAULT_ACCENT,
        },
        "dcc_paths": {},
        "dcc_ports": {},
    }


# ── In-memory active user (set at startup, never written here) ────────────────

_active_user: str | None = None


# ── Internal read/write ───────────────────────────────────────────────────────

def _load() -> dict:
    return read_json(get_prefs_path())  # type: ignore[return-value]


def _save(data: dict) -> None:
    ok = write_json(get_prefs_path(), data)
    if not ok:
        log.warning("Could not write prefs file")


# ── Public API ────────────────────────────────────────────────────────────────

def is_first_launch() -> bool:
    """Return True if config.json is missing workspace or username."""
    cfg = _load()
    return not (cfg.get("workspace") and cfg.get("username"))


def create_user(name: str, workspace: str | Path) -> None:
    """Write defaults into config.json and create USER/<name>/ in the workspace.

    Called once at the end of the first-launch wizard.
    Merges with any existing config.json keys so workspace/username written
    by paths.set_flux_root / paths.set_config_username are preserved.
    """
    global _active_user
    name = name.strip().upper()   # artist names are always FULL UPPERCASE
    _active_user = name

    cfg = _load()
    defaults = _defaults(name, str(workspace))
    for key, val in defaults.items():
        cfg.setdefault(key, val)
    cfg["workspace"] = str(workspace)
    cfg["username"]  = name
    _save(cfg)

    user_dir = Path(workspace) / "USER" / name
    user_dir.mkdir(parents=True, exist_ok=True)
    log.info("User '%s' ready — workspace=%s", name, workspace)


def set_current_user(name: str) -> None:
    """Set the active user in memory (called at startup from config.json)."""
    global _active_user
    _active_user = name
    log.debug("Active user: '%s'", name)


def get_current_user() -> str | None:
    return _active_user


def get(key: str, default: Any = None) -> Any:
    return _load().get(key, default)


def set(key: str, value: Any) -> None:  # noqa: A001
    cfg = _load()
    cfg[key] = value
    _save(cfg)


# ── Convenience shortcuts ─────────────────────────────────────────────────────

def get_last_project() -> str | None:
    return get("last_project")


def set_last_project(name: str) -> None:
    set("last_project", name)


def get_theme() -> dict:
    """Return the 4-color theme dict, migrating old primary/secondary keys if needed."""
    t = get("theme", {}) or {}
    return {
        "bg":      t.get("bg",      t.get("primary",   THEME_DEFAULT_BG)),
        "surface": t.get("surface", THEME_DEFAULT_SURFACE),
        "fg":      t.get("fg",      THEME_DEFAULT_FG),
        "accent":  t.get("accent",  t.get("secondary", THEME_DEFAULT_ACCENT)),
    }


def set_theme(bg: str, surface: str, fg: str, accent: str) -> None:
    cfg = _load()
    cfg["theme"] = {"bg": bg, "surface": surface, "fg": fg, "accent": accent}
    _save(cfg)


# Log levels the console lets the user recolor. Anything else (e.g. critical)
# falls back to the frontend's theme-driven default.
_LOG_COLOR_LEVELS = ("debug", "info", "warning", "error")


def get_log_colors() -> dict:
    """Return the user's console log-color overrides, keyed by level name.

    Empty when the user kept the defaults — the frontend then uses its own
    theme-aware colors, so nothing is forced here.
    """
    raw = get("log_colors", {}) or {}
    return {
        k: v for k, v in raw.items()
        if k in _LOG_COLOR_LEVELS and isinstance(v, str) and v
    }


def set_log_colors(colors: dict) -> None:
    """Persist console log-color overrides (only known levels, non-empty strings)."""
    cfg = _load()
    cfg["log_colors"] = {
        k: v for k, v in (colors or {}).items()
        if k in _LOG_COLOR_LEVELS and isinstance(v, str) and v
    }
    _save(cfg)


def get_dcc_exe(dcc_name: str) -> str | None:
    return get("dcc_paths", {}).get(dcc_name)


def set_dcc_exe(dcc_name: str, path: str) -> None:
    cfg = _load()
    cfg.setdefault("dcc_paths", {})[dcc_name] = path
    _save(cfg)

