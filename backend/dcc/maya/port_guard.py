# port_guard.py — detect and reap a stuck ("zombie") Maya holding the commandPort.
#
# Hub-side only (never imported inside Maya). Pure stdlib — no psutil.
#
# The bug it guards against:
#   A Maya instance closed before it finished starting (or force-killed) can leave a
#   headless maya.exe alive, still holding the commandPort socket (:7001) LISTENING.
#   Every Maya launched afterwards then fails to bind that port (Windows socket 10048),
#   and the hub can't talk to the zombie either — its listener accepts no connection
#   (observed as a stuck SYN_SENT). The port never frees on its own, so a retry can't
#   help: the orphan process has to be terminated.
#
# Detection is deliberately conservative so we NEVER offer to kill a healthy Maya:
#   stuck  ⇔  the port is bound by a maya.exe process  AND  a TCP connect to it fails.
# A legitimately busy Maya (mid-export) still ACCEPTS the TCP connection instantly —
# only the command reply is slow — so it connects fine and is never flagged.

from __future__ import annotations

import os
import re
import socket
import subprocess
import time

from core.constants import DCC_PORTS
from core.logger import get_logger

log = get_logger(__name__)

MAYA_PORT: int = DCC_PORTS["Maya"]

# Hide the transient console window when shelling out on Windows.
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _run(args: list[str]) -> str:
    """Run a short console command, return stdout (empty string on any failure)."""
    return _run_rc(args)[1]


def _run_rc(args: list[str]) -> tuple[int, str]:
    """Run a short console command, return (returncode, stdout).

    Decodes as latin-1: console tools (netstat/tasklist/taskkill) emit locale/OEM-
    codepage bytes that crash the default text decoder on non-English Windows, but
    every field we parse (IP:port, TCP state, PID, image name) is ASCII, and latin-1
    maps all 256 bytes without ever raising. Returncode is -1 on spawn failure.
    """
    try:
        out = subprocess.run(
            args, capture_output=True, timeout=8,
            creationflags=_NO_WINDOW,  # type: ignore[arg-type]
        )
        return out.returncode, (out.stdout or b"").decode("latin-1", "replace")
    except (OSError, subprocess.SubprocessError):
        return -1, ""


def _listener_pids(port: int) -> list[int]:
    """Return PIDs LISTENING on *port* (127.0.0.1 or 0.0.0.0). Windows: netstat -ano."""
    pids: list[int] = []
    if os.name == "nt":
        # netstat columns: Proto  Local  Foreign  State  PID — states/numbers are
        # English + numeric regardless of Windows UI locale.
        for line in _run(["netstat", "-ano", "-p", "TCP"]).splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            local, state, pid = parts[1], parts[3], parts[-1]
            if local.endswith(f":{port}") and state.upper().startswith("LISTEN"):
                if pid.isdigit():
                    pids.append(int(pid))
    else:
        # POSIX best-effort via lsof.
        for line in _run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"]).splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                pids.append(int(parts[1]))
    return list(dict.fromkeys(pids))  # de-dup, keep order


def _proc_name(pid: int) -> str:
    """Return the image name for *pid* (e.g. 'maya.exe'), or '' if unknown."""
    if os.name == "nt":
        out = _run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"])
        m = re.match(r'"([^"]+)"', out.strip())
        return m.group(1) if m else ""
    out = _run(["ps", "-p", str(pid), "-o", "comm="])
    return out.strip()


def _connect_ok(port: int, timeout: float = 2.0) -> bool:
    """True if a TCP connect to 127.0.0.1:*port* completes — i.e. a live listener
    accepts the connection. A zombie's socket is bound but never accepts, so this
    fails; a busy-but-alive Maya accepts instantly."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _reachable(port: int, attempts: int = 3, gap: float = 0.3) -> bool:
    """True if ANY of *attempts* quick TCP connects to *port* succeeds.

    A live listener accepts a connection immediately; a zombie's bound socket never
    accepts. We retry (not a single shot) so a Maya that JUST bound the port — but
    whose commandPort thread is a beat away from accepting — is never mistaken for a
    zombie. One accepted connection is enough to prove the instance is alive.
    """
    for i in range(attempts):
        if _connect_ok(port, timeout=1.0):
            return True
        if i < attempts - 1:
            time.sleep(gap)
    return False


def _is_maya(name: str) -> bool:
    return "maya" in name.lower()


def find_stuck_maya(port: int = MAYA_PORT) -> dict | None:
    """Return {'pid', 'name', 'port'} for a stuck Maya holding *port*, else None.

    Stuck ⇔ a maya.exe process is LISTENING on the port AND a TCP connect fails
    across several quick attempts. Returns None when the port is free, held by a
    responsive (or still-initialising) Maya, or held by a non-Maya process (we never
    propose to kill something that isn't Maya).
    """
    pids = _listener_pids(port)
    if not pids:
        return None
    if _reachable(port):
        return None  # a live listener accepts connections → not a zombie
    for pid in pids:
        name = _proc_name(pid)
        if _is_maya(name):
            log.warning("Stuck Maya detected: pid=%s (%s) holding port %d", pid, name, port)
            return {"pid": pid, "name": name, "port": port}
    return None


def reap_stuck_maya(port: int = MAYA_PORT) -> dict:
    """Terminate the stuck Maya holding *port*, after re-verifying it is still a
    stuck maya.exe. Returns {'killed': bool, 'pid': int|None, 'message': str}.

    Re-checks identity immediately before killing so a PID recycled onto another
    process between detect and reap is never terminated by mistake.
    """
    stuck = find_stuck_maya(port)
    if stuck is None:
        return {"killed": False, "pid": None, "message": "no_stuck_maya"}

    pid = stuck["pid"]
    # Guard: the PID must still be a maya.exe right now (no recycling race).
    if not _is_maya(_proc_name(pid)):
        return {"killed": False, "pid": pid, "message": "pid_no_longer_maya"}

    if os.name == "nt":
        rc, out = _run_rc(["taskkill", "/F", "/PID", str(pid)])
        # rc 128 = "process not found" (already gone) → treat as success below.
        if rc not in (0, 128):
            log.error("Reap: taskkill pid %s failed (rc=%s): %s", pid, rc, out.strip())
            return {"killed": False, "pid": pid, "message": f"taskkill_failed rc={rc}"}
    else:
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass  # already gone → success
        except OSError as exc:
            return {"killed": False, "pid": pid, "message": f"kill_failed: {exc}"}

    # taskkill/kill return before the OS has torn the process down and released the
    # socket, so poll (up to ~4s) for the port to actually free instead of checking
    # once — a premature check sees the dying PID still listed and falsely fails.
    for _ in range(20):
        if pid not in _listener_pids(port):
            log.info("Reaped stuck Maya pid=%s, port %d freed", pid, port)
            return {"killed": True, "pid": pid, "message": "reaped"}
        time.sleep(0.2)

    log.error("Reap: pid %s still holds port %d 4s after kill", pid, port)
    return {"killed": False, "pid": pid, "message": "port_still_held"}
