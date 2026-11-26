# launcher_core.py — detect installed DCCs and launch them as detached processes.

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
from pathlib import Path

from core import config
from core.constants import (
    DCC_EXE_ENV, DCC_EXE_PATTERN_GROUPS, DEFAULT_FRAME_END, DEFAULT_FRAME_START,
)
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

# Map frontend lowercase keys → DCC_EXE_PATTERN_GROUPS keys
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
    "unreal":             "Unreal",
}

# Public list of launcher keys (per-user enabled_dccs validation, V8 U10).
DCC_FRONTEND_KEYS: frozenset[str] = frozenset(_FRONTEND_KEY_MAP)


# ── public API ────────────────────────────────────────────────────────────────

def get_installed_dccs() -> dict[str, str]:
    """Return {frontend_key: exe_path} — keys are lowercase (e.g. 'houdini', 'maya').

    Checks user-configured custom paths first, then the Windows registry and the
    default install dirs of every Program Files root; the newest version wins.
    """
    found: dict[str, str] = {}
    for frontend_key in _FRONTEND_KEY_MAP:
        custom = _valid_custom_exe(frontend_key)
        if custom:
            found[frontend_key] = custom
            continue
        candidates = list_dcc_candidates(frontend_key)
        if candidates:
            found[frontend_key] = candidates[0]
    return found


def list_dcc_candidates(dcc_key: str) -> list[str]:
    """Every install of *dcc_key* found on this machine, newest version first.

    Sources: the Windows registry (Maya, Photoshop) then the glob patterns of
    DCC_EXE_PATTERN_GROUPS (all Program Files roots). Only existing files are kept.
    Order: priority group first (registry entries join the first group), then the
    newest version inside a group. FLUX_<DCC>_EXE naming an existing file is the only
    candidate (registry and Epic launcher included).
    """
    internal = _FRONTEND_KEY_MAP.get(dcc_key)
    if not internal:
        return []
    forced = _env_exe(internal)
    if forced:
        return [forced]
    seen: set[str] = set()

    def _collect(paths: list[str], into: list[str]) -> None:
        for path in paths:
            norm = os.path.normcase(os.path.normpath(path))
            if norm not in seen and os.path.isfile(path):
                seen.add(norm)
                into.append(os.path.normpath(path))

    result: list[str] = []
    groups = DCC_EXE_PATTERN_GROUPS.get(internal, []) or [[]]
    for index, group in enumerate(groups):
        found: list[str] = []
        if index == 0:
            _collect(_registry_candidates(dcc_key), found)
        for pattern in group:
            _collect(glob.glob(pattern), found)
        # Stable sort: equal versions keep the discovery order (registry, then patterns).
        result.extend(sorted(found, key=_version_key, reverse=True))
    return result


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
    if dcc_name == "unreal" and not scene:
        scene = _unreal_host_project(exe)
    extra = () if scene else _frame_range_args(dcc_name)
    if extra:
        env["FLUX_FRAME_START"] = str(DEFAULT_FRAME_START)
        env["FLUX_FRAME_END"] = str(DEFAULT_FRAME_END)
    return launch_exe(exe, scene, extra=extra, env=env, label=dcc_name)


def launch_exe(exe: str, scene: str | None = None, *, extra: tuple = (), env: dict | None = None,
               label: str | None = None) -> bool:
    """Start *exe* (optionally on *scene*) detached from the hub, environment cleaned.

    Extracted from launch_dcc (Flows P6c): an extension bridge (3ds Max...) is not in the
    launcher constants but starts the same way. See launch_dcc for why detaching matters."""
    env = env if env is not None else _child_env()
    args = [exe, *extra, scene] if scene else [exe, *extra]
    dcc_name = label or os.path.basename(exe)
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


def _unreal_host_project(exe: str) -> str | None:
    """Unreal opens the FLUX host project (bridge plugin refreshed), ADR 0052."""
    from dcc.unreal import autostart as unreal_autostart

    try:
        return str(unreal_autostart.ensure_project(exe))
    except OSError as exc:
        log.error("Unreal host project not written (%s): launching Unreal without it", exc)
        return None


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
    candidates = list_dcc_candidates(dcc_key)
    if candidates:
        path = candidates[0]
        # An env-forced exe is not persisted: it must stop applying with the variable.
        if not _env_exe(internal):
            config.set_dcc_exe(dcc_key, path)
        others = f" (autres versions : {', '.join(candidates[1:])})" if len(candidates) > 1 else ""
        log.info("Auto-found %s → %s%s", dcc_key, path, others)
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
    custom = _valid_custom_exe(dcc_name)
    if custom:
        return custom
    return get_installed_dccs().get(dcc_name)


# Custom paths already reported missing (warn once per path, the scan is polled).
_warned_missing: set[str] = set()


def _valid_custom_exe(dcc_key: str) -> str | None:
    """The configured exe of *dcc_key* when it still exists. A configured path that
    vanished (DCC uninstalled, upgraded to a new version folder) is logged once and
    ignored, so auto-detection takes over."""
    custom = config.get_dcc_exe(dcc_key)
    if not custom:
        return None
    if Path(custom).is_file():
        return custom
    if custom not in _warned_missing:
        _warned_missing.add(custom)
        log.warning("Chemin configure introuvable pour %s : %s (detection automatique utilisee)",
                    dcc_key, custom)
    return None


def _env_exe(internal: str) -> str | None:
    """The exe named by FLUX_<DCC>_EXE when set and existing; a missing file is logged
    once and ignored, so the usual detection takes over."""
    var = DCC_EXE_ENV.get(internal, "")
    value = (os.environ.get(var) or "").strip().strip('"')
    if not value:
        return None
    if os.path.isfile(value):
        return os.path.normpath(value)
    if f"{var}={value}" not in _warned_missing:
        _warned_missing.add(f"{var}={value}")
        log.warning("%s introuvable : %s (detection automatique utilisee)", var, value)
    return None


_VERSION_RE = re.compile(r"\d+")
_UE_DIR_RE = re.compile(r"[\\/]UE_([\d.]+)[\\/]", re.IGNORECASE)


def _version_key(path: str) -> tuple:
    """Sort key: the numbers of the deepest folder holding digits.

    Maya2025 -> (2025,), "Adobe Photoshop 2025" -> (2025,) > "Adobe Photoshop CC 2019"
    -> (2019,), "Houdini 20.5.332" -> (20, 5, 332), Nuke15.1v3 -> (15, 1, 3).
    Unreal: UE_5.6\\Engine\\Binaries\\Win64 -> (5, 6) (Win64 would tie every version).
    """
    unreal = _UE_DIR_RE.search(path)
    if unreal:
        return tuple(int(n) for n in _VERSION_RE.findall(unreal.group(1)))
    for part in reversed(Path(path).parent.parts):
        numbers = _VERSION_RE.findall(part)
        if numbers:
            return tuple(int(n) for n in numbers)
    return ()


# ── Windows registry (guarded: absent off Windows, mocked in tests) ─────────────

try:  # pragma: no cover - platform dependent
    import winreg as _winreg
except ImportError:  # pragma: no cover
    _winreg = None

_MAYA_KEY = r"SOFTWARE\Autodesk\Maya"
_PHOTOSHOP_KEY = r"SOFTWARE\Adobe\Photoshop"
_APP_PATHS_PHOTOSHOP = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Photoshop.exe"


def _reg_subkeys(key_path: str) -> list[str]:
    """Names of the subkeys of HKLM\\<key_path> (64-bit view), [] when absent."""
    if _winreg is None:
        return []
    try:
        with _winreg.OpenKey(_winreg.HKEY_LOCAL_MACHINE, key_path, 0,
                             _winreg.KEY_READ | getattr(_winreg, "KEY_WOW64_64KEY", 0)) as key:
            names: list[str] = []
            index = 0
            while True:
                try:
                    names.append(_winreg.EnumKey(key, index))
                except OSError:
                    return names
                index += 1
    except OSError:
        return []


def _reg_value(key_path: str, name: str = "") -> str | None:
    """A string value of HKLM\\<key_path> ("" = default value), None when absent."""
    if _winreg is None:
        return None
    try:
        with _winreg.OpenKey(_winreg.HKEY_LOCAL_MACHINE, key_path, 0,
                             _winreg.KEY_READ | getattr(_winreg, "KEY_WOW64_64KEY", 0)) as key:
            value, _kind = _winreg.QueryValueEx(key, name)
    except OSError:
        return None
    return str(value) if value else None


def _registry_candidates(dcc_key: str) -> list[str]:
    """Exe paths the registry declares for *dcc_key* (may not exist: filtered later)."""
    out: list[str] = []
    if dcc_key == "maya":
        # HKLM\SOFTWARE\Autodesk\Maya\2025\Setup\InstallPath  MAYA_INSTALL_LOCATION
        for version in _reg_subkeys(_MAYA_KEY):
            loc = _reg_value(rf"{_MAYA_KEY}\{version}\Setup\InstallPath", "MAYA_INSTALL_LOCATION")
            if loc:
                out.append(os.path.join(loc, "bin", "maya.exe"))
    elif dcc_key == "photoshop":
        # HKLM\SOFTWARE\Adobe\Photoshop\<ver>  ApplicationPath (folder holding Photoshop.exe)
        for version in _reg_subkeys(_PHOTOSHOP_KEY):
            app = _reg_value(rf"{_PHOTOSHOP_KEY}\{version}", "ApplicationPath")
            if app:
                out.append(os.path.join(app, "Photoshop.exe"))
        # App Paths\Photoshop.exe default value = the exe itself
        exe = _reg_value(_APP_PATHS_PHOTOSHOP)
        if exe:
            out.append(exe.strip('"'))
    elif dcc_key == "unreal":
        out.extend(_epic_launcher_candidates())
    return out


def _epic_launcher_candidates() -> list[str]:
    """UnrealEditor.exe of every engine the Epic Games Launcher installed (any drive).

    %PROGRAMDATA%\\Epic\\UnrealEngineLauncher\\LauncherInstalled.dat is JSON:
    {"InstallationList": [{"InstallLocation": "D:\\Epic\\UE_5.6", "AppName": "UE_5.6"}, ...]}."""
    data_file = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Epic" / "UnrealEngineLauncher" \
        / "LauncherInstalled.dat"
    try:
        installs = json.loads(data_file.read_text(encoding="utf-8")).get("InstallationList", [])
    except (OSError, ValueError, AttributeError):
        return []
    out = []
    for item in installs:
        if isinstance(item, dict) and str(item.get("AppName", "")).upper().startswith("UE_"):
            location = str(item.get("InstallLocation") or "")
            if location:
                out.append(os.path.join(location, "Engine", "Binaries", "Win64", "UnrealEditor.exe"))
    return out

