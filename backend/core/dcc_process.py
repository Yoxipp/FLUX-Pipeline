# dcc_process.py — close a running DCC instance from the hub (2026-09-19).
#
# The instance is found by the port it listens on (DCC_PORT_RANGES). Two steps:
#   * close: the same as the window's X button (taskkill without /F = WM_CLOSE), so the
#     DCC can ask to save; a session with no window (ghost) or an open save dialog stays;
#   * force: kill the process (unsaved work is lost), only when the user asks for it.
# Never touches a process whose name is not the DCC's, nor the backend itself.

from __future__ import annotations

import os
import time

from core.constants import DCC_PORT_RANGES
from core.logger import get_logger

log = get_logger(__name__)

# Lowercase pieces of the executable names of each DCC.
PROCESS_NAMES: dict[str, tuple[str, ...]] = {
    "Maya":       ("maya",),
    "Houdini":    ("houdini", "hindie", "happrentice", "hescape", "hython"),
    "Nuke":       ("nuke",),
    "SubstanceP": ("painter",),
    # Not bare "designer": Marvelous Designer would count as Substance Designer.
    "SubstanceD": ("substance 3d designer", "substance designer"),
    "Marvelous":  ("marvelous",),
    "Photoshop":  ("photoshop",),
    "Mari":       ("mari",),
    "ZBrush":     ("zbrush",),
}


def _port_in_range(dcc: str, port: int) -> bool:
    base, count = DCC_PORT_RANGES[dcc]
    return base <= port < base + count


def _dcc_pid(dcc: str, port: int) -> tuple[int | None, str]:
    """(pid, exe name) of the DCC process listening on *port*, else (None, reason)."""
    from dcc.maya.port_guard import _listener_pids, _proc_name

    pids = [p for p in _listener_pids(port) if p != os.getpid()]
    if not pids:
        return None, "free"
    for pid in pids:
        name = _proc_name(pid)
        if any(piece in name.lower() for piece in PROCESS_NAMES.get(dcc, ())):
            return pid, name
    return None, "other"


def _wait_port_free(port: int, pid: int, seconds: float) -> bool:
    from dcc.maya.port_guard import _listener_pids

    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if pid not in _listener_pids(port):
            return True
        time.sleep(0.25)
    return pid not in _listener_pids(port)


def close_instance(dcc: str, port: int, force: bool = False) -> dict:
    """{"closed", "pid", "needs_force", "message"} for the instance of *dcc* on *port*."""
    from dcc.maya.port_guard import _run_rc

    if dcc not in DCC_PORT_RANGES:
        raise ValueError(f"DCC inconnu : {dcc}")
    if not _port_in_range(dcc, port):
        raise ValueError(f"le port {port} n'est pas un port {dcc}")
    pid, name = _dcc_pid(dcc, port)
    if pid is None:
        if name == "free":
            return {"closed": True, "pid": None, "needs_force": False, "message": "instance deja fermee"}
        return {"closed": False, "pid": None, "needs_force": False,
                "message": f"le port {port} n'est pas tenu par {dcc} : rien n'est ferme"}
    args = ["taskkill", "/PID", str(pid)] if os.name == "nt" else ["kill", str(pid)]
    if force:
        args = ["taskkill", "/F", "/PID", str(pid)] if os.name == "nt" else ["kill", "-9", str(pid)]
    rc, out = _run_rc(args)
    log.info("close %s :%d pid %s (%s, force=%s): rc=%s %s", dcc, port, pid, name, force, rc, out.strip())
    if _wait_port_free(port, pid, 4.0 if force else 3.0):
        return {"closed": True, "pid": pid, "needs_force": False,
                "message": f"{dcc} :{port} ferme" + (" (force)" if force else "")}
    return {"closed": False, "pid": pid, "needs_force": not force,
            "message": (f"{dcc} :{port} n'a pas quitte : une fenetre d'enregistrement est peut-etre ouverte, "
                        "ou la session n'a pas de fenetre" if not force
                        else f"{dcc} :{port} tourne encore apres la fermeture forcee")}
