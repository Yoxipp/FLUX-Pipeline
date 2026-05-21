# maya_connection.py — commandPort server management (Maya side) + command dispatch (hub side).
#
# Imported from two contexts:
#   Maya (Python 3.10) : start_server, stop_server, open_hub
#   Hub  (Python 3.13) : execute_command, is_server_running

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from core.constants import DCC_PORTS
from core.logger import get_logger

log = get_logger(__name__)

MAYA_PORT: int = DCC_PORTS["Maya"]

# Maya modules — only available inside a running Maya session
try:
    import maya.cmds as _cmds  # type: ignore[import]
    _IN_MAYA = True
except ImportError:
    _cmds = None
    _IN_MAYA = False

# socket_manager depends on PySide6, which Maya 2024 does not ship — guard it
try:
    from core.socket_manager import socket_manager as _socket_manager
    _HAS_SOCKET_MANAGER = True
except ImportError:
    _socket_manager = None
    _HAS_SOCKET_MANAGER = False


# ── Maya-side functions ───────────────────────────────────────────────────────

def start_server(port: int = MAYA_PORT) -> bool:
    """Open Maya commandPort on *port*. Must be called from inside Maya."""
    if not _IN_MAYA:
        log.error("start_server: not running inside Maya")
        return False
    try:
        _cmds.commandPort(name=f":{port}", sourceType="python", noreturn=False)
        log.info("Maya commandPort open on port %d", port)
        return True
    except RuntimeError as exc:
        if "already" in str(exc).lower():
            log.debug("commandPort already open on port %d", port)
            return True
        log.error("start_server failed: %s", exc)
        return False
    except Exception as exc:
        log.error("start_server failed: %s", exc)
        return False


def stop_server(port: int = MAYA_PORT) -> bool:
    """Close Maya commandPort on *port*. Must be called from inside Maya."""
    if not _IN_MAYA:
        log.error("stop_server: not running inside Maya")
        return False
    try:
        _cmds.commandPort(name=f":{port}", close=True)
        log.info("Maya commandPort closed on port %d", port)
        return True
    except Exception as exc:
        log.error("stop_server failed: %s", exc)
        return False


def open_hub() -> None:
    """Launch the Flux Hub as a subprocess. Called from Maya shelf button.

    Tries hub.exe (prod) then main.py with system python (dev).
    """
    try:
        pkg_root = Path(__file__).resolve().parent.parent.parent.parent
        hub_exe = pkg_root / "hub.exe"
        if hub_exe.is_file():
            subprocess.Popen([str(hub_exe)])
            return
        main_py = pkg_root / "main.py"
        python_exe = shutil.which("python") or shutil.which("python3")
        if main_py.is_file() and python_exe:
            subprocess.Popen([python_exe, str(main_py)])
            return
        log.error("open_hub: hub.exe and main.py not found under %s", pkg_root)
    except Exception as exc:
        log.error("open_hub failed: %s", exc)


# ── Hub-side functions ────────────────────────────────────────────────────────

def is_server_running(port: int = MAYA_PORT) -> bool:
    """Check if the Maya commandPort is reachable via TCP. Works from any context."""
    if _HAS_SOCKET_MANAGER:
        return _socket_manager.probe("Maya")  # type: ignore[union-attr]
    # Fallback: raw TCP probe (used inside Maya where PySide6 is unavailable)
    import socket as _socket
    try:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(("127.0.0.1", port))
        s.close()
        return True
    except OSError:
        return False


def execute_command(command: str) -> str | None:
    """Send a Python command string to Maya and return the response string.

    Must be called from the Hub (Python 3.13). Returns None on error.
    Uses a fresh TCP connection so the call works even on first use.
    """
    return send_command_direct(command)


def send_command_direct(command: str, timeout: float = 60.0) -> str | None:
    """Open a fresh TCP connection to Maya's commandPort, send *command*, return response.

    Uses a dedicated socket (not the persistent socket_manager) so it:
      - Works without a prior socket_manager.connect() call.
      - Supports custom timeouts for long-running exports.
      - Avoids socket state issues between calls.

    Returns the response string on success, None on any error.
    """
    import socket as _sock_mod
    try:
        s = _sock_mod.socket(_sock_mod.AF_INET, _sock_mod.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(("127.0.0.1", MAYA_PORT))
        s.sendall((command + "\n").encode("utf-8"))
        response = s.recv(65536).decode("utf-8", errors="replace").strip()
        s.close()
        log.debug("Maya command OK (len=%d)", len(response))
        return response
    except OSError as exc:
        log.error("send_command_direct failed: %s", exc)
        return None

