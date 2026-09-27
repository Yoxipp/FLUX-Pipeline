# launcher_core.py — detect installed DCCs and launch them as detached processes.

from __future__ import annotations

import glob
import os
import subprocess
from pathlib import Path

from core import config
from core.constants import DCC_EXE_PATTERNS, DEFAULT_FRAME_END, DEFAULT_FRAME_START
from core.logger import get_logger

log = get_logger(__name__)

# Startup scripts that set the FLUX default frame range on an empty scene. Passed on
# the command line, so nothing has to be installed in the DCC prefs. Same resources
# root as dcc/maya/maya_rigs.py (bundled by scripts/backend.spec in the frozen build).
_STARTUP_DIR = Path(__file__).resolve().parents[2] / "resources" / "startup"
_FRAME_RANGE_ARGS: dict[str, tuple[str, ...]] = {
    "maya":    ("-script", str(_STARTUP_DIR / "flux_frame_range.mel")),
    "houdini": (str(_STARTUP_DIR / "flux_frame_range.cmd"),),
}

# Windows process-creation flags — DETACHED keeps the DCC alive after the hub closes.
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200

# Env vars FLUX's OWN runtime injects that must NOT leak into a launched DCC.
# flux_backend.exe is a PyInstaller bundle (sets PYTHON*/_MEIPASS/SSL_CERT_*), and
# FLUX may be started from a shell (e.g. Git Bash) that sets HOME. Inherited by a DCC
# these break its startup — most visibly on Windows, where a stray HOME makes Houdini
# read $HOME/houdiniX.Y instead of %USERPROFILE%/Documents/houdiniX.Y, so the user's
# prefs, desktops, shelves and HDAs never load. FLUX_PORT is deliberately KEPT so the
# Houdini importer HDA bootstrap can still find the backend.
# PYTHONUSERBASE is set by the Microsoft Store Python that runs the dev backend: Houdini
# (also py3.13) then adds that user site to sys.path and imports the pip usd-core pxr
# instead of its own, which breaks every LopNode.stage() and Python LOP.
_ENV_LEAK_VARS: tuple[str, ...] = (
    "_MEIPASS", "_MEIPASS2", "_PYI_ARCHIVE_FILE", "_PYI_APPLICATION_HOME_DIR",
    "PYINSTALLER_RESET_ENVIRONMENT",
    "PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONEXECUTABLE",
    "PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE", "PYTHONHASHSEED", "PYTHONUSERBASE",
    "SSL_CERT_FILE", "SSL_CERT_DIR",
    "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH",
)


def _child_env() -> dict[str, str]:
    """Return a copy of the environment cleaned of FLUX/PyInstaller/dev-shell leakage,
    so a launched DCC starts exactly as a normal Start-menu launch would."""
    env = dict(os.environ)
    for var in _ENV_LEAK_VARS:
        env.pop(var, None)
    if os.name == "nt":
        # HOME is non-standard on Windows (a normal login/Start-menu launch has none);
        # only ever set by a dev shell, and it hijacks Houdini's pref-dir resolution.
        env.pop("HOME", None)
    return env

# Map frontend lowercase keys → DCC_EXE_PATTERNS keys
_FRONTEND_KEY_MAP: dict[str, str] = {
    "maya":               "Maya",
    "houdini":            "Houdini",
    "nuke":               "Nuke",
    "substance_painter":  "SubstanceP",
    "substance_designer": "SubstanceD",
    "zbrush":             "ZBrush",
    "marvelous":          "Marvelous",
    "photoshop":          "Photoshop",
    "mari":               "Mari",
}

# Public list of launcher keys (per-user enabled_dccs validation, V8 U10).
DCC_FRONTEND_KEYS: frozenset[str] = frozenset(_FRONTEND_KEY_MAP)


# ── public API ────────────────────────────────────────────────────────────────

def get_installed_dccs() -> dict[str, str]:
    """Return {frontend_key: exe_path} — keys are lowercase (e.g. 'houdini', 'maya').

    Checks user-configured custom paths first, then glob-scans default install dirs.
    """
    found: dict[str, str] = {}
    for frontend_key, internal_key in _FRONTEND_KEY_MAP.items():
        patterns = DCC_EXE_PATTERNS.get(internal_key, [])
        custom = config.get_dcc_exe(frontend_key)
        if custom and Path(custom).is_file():
            found[frontend_key] = custom
            continue
        for pattern in patterns:
            matches = glob.glob(pattern)
            if matches:
                found[frontend_key] = sorted(matches)[-1]
                break
    return found


# Characters cmd.exe still interprets inside double quotes: a quote ends the quoting
# (then & | > run extra commands) and %VAR% is expanded. Refused in launch arguments.
_CMD_UNSAFE_CHARS = ('"', "%", "\n", "\r")


def _cmd_quoted(value: str) -> str:
    """Return *value* double-quoted for cmd.exe, refusing anything that could escape it."""
    if any(ch in value for ch in _CMD_UNSAFE_CHARS):
        raise ValueError(f"unsafe character in launch argument: {value!r}")
    return f'"{value}"'


def launch_dcc(dcc_name: str, scene: str | None = None) -> bool:
    """Launch *dcc_name* fully independent of the hub. Returns True on start.

    *scene* : an optional scene file to open (e.g. a preset .hip / .ma). When set the
    DCC is launched with the file as its command-line argument ("New Scene" flow).

    CRITICAL: the DCC must NOT be a descendant of the FastAPI backend, otherwise the
    hub's shutdown (taskkill /PID <backend> /T) tree-kills it — closing FLUX would kill
    an open Maya/Houdini with unsaved work. On Windows we reparent via cmd's `start`,
    which spawns the DCC as an independent process (not a child of cmd/backend), so it
    survives the hub closing; DETACHED_PROCESS alone is NOT enough (taskkill /T walks
    parent->child links regardless). `start` (unlike os.startfile) also lets us hand the
    DCC a cleaned environment — see _child_env(): without it Houdini launches without the
    user's prefs/desktops/shelves/HDAs because FLUX's env leaks a stray HOME.
    """
    exe = _resolve_exe(dcc_name)
    if exe is None:
        log.warning("No executable found for '%s'", dcc_name)
        return False
    env = _child_env()
    # Empty Maya / Houdini session: start on the FLUX frame range (1001-1050). A scene
    # (preset, sequence render scene) keeps its own range.
    extra = () if scene else _frame_range_args(dcc_name)
    if extra:
        env["FLUX_FRAME_START"] = str(DEFAULT_FRAME_START)
        env["FLUX_FRAME_END"] = str(DEFAULT_FRAME_END)
    args = [exe, *extra, scene] if scene else [exe, *extra]
    try:
        if os.name == "nt":
            # `start "" "<exe>" [args]` — the empty "" is start's window-title arg.
            # The DCC is reparented away from the backend, so taskkill /T won't reach it.
            # Every argument is quoted and checked (security S4): a scene path holding
            # a quote or %VAR% could otherwise inject commands through the shell.
            cmd = 'start "" ' + " ".join(_cmd_quoted(str(a)) for a in args)
            subprocess.Popen(
                cmd, shell=True, close_fds=True, env=env,
                creationflags=_DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP,
            )
        else:
            # POSIX: new session detaches from the hub's process group.
            subprocess.Popen(args, start_new_session=True, close_fds=True, env=env)
        log.info("Launched %s — %s%s", dcc_name, exe, f" (scene: {scene})" if scene else "")
        return True
    except (OSError, ValueError) as e:
        log.error("Failed to launch %s: %s", dcc_name, e)
        return False


def set_custom_exe_path(dcc_name: str, path: str) -> None:
    """Persist a custom exe path for *dcc_name* in user settings."""
    config.set_dcc_exe(dcc_name, path)
    log.info("Custom exe set for %s: %s", dcc_name, path)


def find_dcc_exe(dcc_key: str) -> str | None:
    """Glob-scan default install dirs for *dcc_key*, save to config if found.

    *dcc_key* is the frontend lowercase key (e.g. 'maya', 'substance_painter').
    Returns the found path, or None if nothing matches.
    """
    internal = _FRONTEND_KEY_MAP.get(dcc_key)
    if not internal:
        log.warning("find_dcc_exe: unknown key '%s'", dcc_key)
        return None
    patterns = DCC_EXE_PATTERNS.get(internal, [])
    for pattern in patterns:
        matches = glob.glob(pattern)
        if matches:
            path = sorted(matches)[-1]
            config.set_dcc_exe(dcc_key, path)
            log.info("Auto-found %s → %s", dcc_key, path)
            return path
    log.info("Auto-find: no exe found for '%s'", dcc_key)
    return None


# ── private ───────────────────────────────────────────────────────────────────

def _frame_range_args(dcc_name: str) -> tuple[str, ...]:
    """Command-line args running the frame-range startup script, or () when the DCC
    has none or the script is missing (the DCC then starts normally)."""
    args = _FRAME_RANGE_ARGS.get((dcc_name or "").lower(), ())
    script = Path(args[-1]) if args else None
    if script is None or not script.is_file():
        if script is not None:
            log.warning("Frame range startup script missing: %s", script)
        return ()
    return args


def _resolve_exe(dcc_name: str) -> str | None:
    """Return exe path: custom setting first, then auto-detected, then None."""
    custom = config.get_dcc_exe(dcc_name)
    if custom and Path(custom).is_file():
        return custom
    return get_installed_dccs().get(dcc_name)

