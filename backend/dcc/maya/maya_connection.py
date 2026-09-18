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
    """Open Maya commandPort on *port*. Must be called from inside Maya (ideally via executeDeferred)."""
    if not _IN_MAYA:
        log.error("start_server: not running inside Maya")
        return False
    try:
        # Loopback only (security S3): a bare ":port" can listen on the whole network.
        port_str = f"127.0.0.1:{port}"
        if not _cmds.commandPort(port_str, query=True):
            _cmds.commandPort(name=port_str, sourceType="python", noreturn=False)
        log.info("Maya commandPort open on port %d", port)
        return True
    except Exception as exc:
        log.error("start_server failed: %s", exc)
        return False


def stop_server(port: int = MAYA_PORT) -> bool:
    """Close Maya commandPort on *port*. Must be called from inside Maya."""
    if not _IN_MAYA:
        log.error("stop_server: not running inside Maya")
        return False
    try:
        _cmds.commandPort(name=f"127.0.0.1:{port}", close=True)
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
    s: _socket.socket | None = None
    try:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        if s is not None:
            try:
                s.close()
            except OSError:
                pass


def execute_command(command: str) -> str | None:
    """Send a Python command string to Maya and return the response string.

    Must be called from the Hub (Python 3.13). Returns None on error.
    Uses a fresh TCP connection so the call works even on first use.
    """
    return send_command_direct(command)


def send_command_direct(command: str, timeout: float = 60.0, port: int = MAYA_PORT) -> str | None:
    """Open a fresh TCP connection to a Maya commandPort, send *command*, return response.

    Uses a dedicated socket (not the persistent socket_manager) so it:
      - Works without a prior socket_manager.connect() call.
      - Supports custom timeouts for long-running exports.
      - Avoids socket state issues between calls.

    *port* selects which Maya instance to talk to (multi-instance, cluster C);
    it defaults to the base commandPort so existing single-instance callers are
    unchanged.

    Returns the response string on success, None on any error.
    """
    import socket as _sock_mod
    s: _sock_mod.socket | None = None
    try:
        s = _sock_mod.socket(_sock_mod.AF_INET, _sock_mod.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(("127.0.0.1", port))
        s.sendall((command + "\n").encode("utf-8"))
        response = s.recv(65536).decode("utf-8", errors="replace").strip()
        log.debug("Maya command OK (len=%d)", len(response))
        return response
    except OSError as exc:
        log.error("send_command_direct failed: %s", exc)
        return None
    finally:
        # Always release the fd: on a connect() failure the socket is otherwise
        # leaked, and rapid open/close/relaunch cycles hammer this path.
        if s is not None:
            try:
                s.close()
            except OSError:
                pass



# ── ghost sessions ───────────────────────────────────────────────────────────────
# Live 2026-09-18: a Maya whose main window was gone (a session that never finished
# quitting) still held the commandPort, so FLUX exported its empty scene instead of
# the artist's. A Maya that answers but shows no main window is never a target.

_WINDOW_EXPR = (
    "(lambda c: bool(c.window('MayaWindow', exists=True)"
    " and c.window('MayaWindow', q=True, visible=True)))"
    "(__import__('maya.cmds', fromlist=['cmds']))"
)


def maya_window_visible(port: int, timeout: float = 1.5) -> bool | None:
    """True / False when the Maya on *port* shows its main window, None when it does
    not answer (closed port, busy Maya)."""
    resp = send_command_direct(_WINDOW_EXPR, timeout=timeout, port=port)
    if resp is None:
        return None
    return resp.strip().strip("\x00").lower() in ("true", "1")


class GhostMayaError(RuntimeError):
    """The only Maya reachable by FLUX has no main window."""


def pick_live_port(requested: int, candidates: list[int], *, probe=None) -> int:
    """*requested* unless its Maya is a ghost (answers, no window): then another
    instance in *candidates* that shows its window, else GhostMayaError. Busy / silent
    Mayas are kept: only a proven ghost is skipped."""
    probe_fn = probe or maya_window_visible
    if probe_fn(requested) is not False:
        return requested
    for port in candidates:
        if port != requested and probe_fn(port) is True:
            log.warning("Maya :%d n'a pas de fenetre (session fantome) : cible :%d", requested, port)
            return port
    raise GhostMayaError(
        f"Le Maya connecte a FLUX (port {requested}) n'a pas de fenetre : c'est une session "
        "qui ne s'est pas fermee. Ferme maya.exe en trop dans le Gestionnaire des taches, "
        "puis relance Maya (ou le bouton de connexion du shelf FLUX).")
