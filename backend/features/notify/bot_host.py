# bot_host.py - who runs the Discord bots of this PC, and the headless mode (ADR 0076).
#
# One host per PC (per Windows account): a local lock %APPDATA%/FluxPipeline/discord_bot.lock
# {pid, mode: app | headless, at}. The process that runs the bots holds it; a lock whose
# process is dead is taken over. Two Gateway connections on one token stay avoided (0073).
#
# Headless mode: `flux_backend.exe --discord-bot` (dev: `pythonw main.py --discord-bot`),
# no HTTP, no window. Started at Windows logon by a shortcut in the user's Startup folder
# (no admin, nothing else changed on the PC). While FLUX is open and runs the bots, the
# headless process waits and takes over when FLUX closes.

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from core.logger import get_logger
from features.notify import bot_secret

log = get_logger(__name__)

FLAG = "--discord-bot"
SHORTCUT_NAME = "FLUX bot Discord.lnk"
REFRESH_S = 60.0
NO_WINDOW = 0x08000000                     # CREATE_NO_WINDOW
STARTUP_OVERRIDE: Path | None = None       # tests

MODE = "app"                               # "headless" in the --discord-bot process


# ── lock ──────────────────────────────────────────────────────────────────────

def lock_path() -> Path:
    return bot_secret.tokens_path().parent / "discord_bot.lock"


def pid_alive(pid: int) -> bool:
    """True when process *pid* runs (never signals it: os.kill on Windows terminates)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259                         # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def holder() -> dict | None:
    """{pid, mode, at} of the live process holding the lock, None when free."""
    try:
        data = json.loads(lock_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        pid = int(data.get("pid") or 0)
    except (TypeError, ValueError):
        return None
    return data if pid_alive(pid) else None


def claim() -> bool:
    """Take the lock for this process (or keep it). False when another live process holds it."""
    current = holder()
    if current and int(current["pid"]) != os.getpid():
        return False
    if current:
        return True
    path = lock_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"pid": os.getpid(), "mode": MODE, "at": time.time()}), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        log.warning("discord bot lock not written: %s", exc)
        return True             # no lock possible: behave as before the lock existed
    # Two processes may have written at once: the last write wins, the other backs off.
    current = holder()
    return not current or int(current["pid"]) == os.getpid()


def release() -> None:
    current = holder()
    if current and int(current["pid"]) == os.getpid():
        try:
            lock_path().unlink()
        except OSError:
            pass


# ── startup shortcut ──────────────────────────────────────────────────────────

def startup_dir() -> Path:
    if STARTUP_OVERRIDE is not None:
        return STARTUP_OVERRIDE
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def shortcut_path() -> Path:
    return startup_dir() / SHORTCUT_NAME


def command() -> tuple[str, list[str], str]:
    """(exe, args, working dir) of the headless mode for this install."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        return str(exe), [FLAG], str(exe.parent)
    backend = Path(__file__).resolve().parents[2]
    pythonw = Path(sys.executable).with_name("pythonw.exe")     # no console window
    exe = pythonw if pythonw.is_file() else Path(sys.executable)
    return str(exe), [str(backend / "main.py"), FLAG], str(backend)


def background_enabled() -> bool:
    return shortcut_path().is_file()


def _powershell(script: str, env: dict) -> None:
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                   env={**os.environ, **env}, check=True, timeout=30, capture_output=True,
                   creationflags=NO_WINDOW if os.name == "nt" else 0)


def install_startup() -> Path:
    """Shortcut in the user's Startup folder. Paths go through env vars, never in the script."""
    if os.name != "nt":
        raise OSError("Le bot en arriere-plan n'existe que sous Windows")
    exe, args, cwd = command()
    path = shortcut_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _powershell(
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:FLUX_LNK); "
        "$s.TargetPath = $env:FLUX_EXE; $s.Arguments = $env:FLUX_ARGS; "
        "$s.WorkingDirectory = $env:FLUX_CWD; $s.WindowStyle = 7; "
        "$s.Description = 'FLUX : bots Discord de ce PC (ADR 0076)'; $s.Save()",
        {"FLUX_LNK": str(path), "FLUX_EXE": exe, "FLUX_CWD": cwd,
         "FLUX_ARGS": subprocess.list2cmdline(args)})
    return path


def remove_startup() -> None:
    try:
        shortcut_path().unlink()
    except FileNotFoundError:
        pass


def spawn() -> None:
    """Start the headless process now, outside FLUX's process tree: Electron closes the
    backend with taskkill /T, which would take a direct child with it."""
    exe, args, cwd = command()
    subprocess.Popen(["cmd", "/c", "start", "", exe, *args], cwd=cwd,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=NO_WINDOW if os.name == "nt" else 0, close_fds=True)


def stop_headless() -> bool:
    """End the headless process of this PC, if it is the one holding the lock."""
    current = holder()
    if not current or current.get("mode") != "headless":
        return False
    try:
        os.kill(int(current["pid"]), 15)      # Windows: TerminateProcess
    except OSError as exc:
        log.warning("headless discord bot not stopped: %s", exc)
        return False
    try:
        lock_path().unlink()
    except OSError:
        pass
    return True


def status() -> dict:
    current = holder()
    return {"background": background_enabled(),
            "runs_in": (current or {}).get("mode", "")}


# ── headless loop ─────────────────────────────────────────────────────────────

def run_headless(stop_after: float | None = None) -> int:
    """Body of `--discord-bot`. Waits while FLUX runs the bots, then hosts them; every
    minute picks up a token added, changed or removed here, and a share back online."""
    global MODE
    MODE = "headless"
    from features.notify import discord_bot
    if not discord_bot.enabled():
        log.info("headless discord bot: disabled by env")
        return 0
    log.info("headless discord bot: started (pid %d)", os.getpid())
    started = time.time()
    while stop_after is None or time.time() - started < stop_after:
        if not bot_secret.hosted_projects():
            log.info("headless discord bot: no token on this PC, exiting")
            break
        if claim():
            discord_bot.refresh()
        time.sleep(REFRESH_S if stop_after is None else min(REFRESH_S, 0.05))
    discord_bot.stop_all()
    return 0


def run_cli() -> int:
    """Entry of main.py --discord-bot: the config is read from the same config.json."""
    try:
        from core import config
        user = config.get("username")
        if user:
            config.set_current_user(user)
    except Exception as exc:  # noqa: BLE001 - the bot needs no user to answer
        log.warning("headless discord bot: config not read: %s", exc)
    try:
        return run_headless()
    finally:
        release()
