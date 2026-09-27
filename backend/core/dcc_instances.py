# dcc_instances.py — discover running instances of each DCC (cluster C).
#
# Multi-instance model: a DCC no longer owns a single fixed port but a RANGE
# (constants.DCC_PORT_RANGES). Each running instance holds one open port in that
# range. Discovery = scan the range and report every reachable port as one
# instance. Instance identity is the port itself (unique on localhost), exposed
# as a stable string id "<dcc>:<port>".
#
# A1 (2026-09-27): an instance is (port, pid). The pid comes from the listening
# socket (core/dcc_identity.py); scene / version / busy are added by the status route.
# The active instance is remembered WITH its pid: when another process takes the port
# back (the chosen Houdini closed, a new one opened), it is not the chosen one anymore
# and nothing is sent to it silently.

from __future__ import annotations

import time

from core.constants import DCC_PORT_RANGES, dcc_port_range
from core.socket_manager import socket_manager

# Short probe: a closed localhost port refuses almost instantly (RST), so a tight
# timeout keeps a full-range scan cheap even across every DCC on each status push.
_SCAN_TIMEOUT_S: float = 0.3


def instance_id(dcc: str, port: int) -> str:
    """Stable identifier for one DCC instance. Port is unique per localhost."""
    return f"{dcc}:{port}"


def make_instance(dcc: str, port: int, connected: bool = True, pid: int | None = None) -> dict:
    """Build the canonical instance record. scene / version / state are filled by the
    status route (bridge query, cached)."""
    return {
        "id":        instance_id(dcc, port),
        "dcc":       dcc,
        "port":      port,
        "connected": connected,
        "pid":       pid,     # process listening on the port
        "scene":     None,    # open scene/hip file, when the bridge reports it
        "version":   None,    # DCC version string, when the bridge reports it
        "state":     "connected",   # or "busy" (accepts, does not answer: export running)
        "label":     f"{dcc} :{port}",
    }


def scan_instances(dcc: str, *, probe=None, timeout: float = _SCAN_TIMEOUT_S, pid_of=None) -> list[dict]:
    """Probe every port in *dcc*'s range; return one record per reachable port.

    *probe* defaults to socket_manager.probe_port and is injectable for tests.
    Returns instances ordered by port (ascending), so the lowest open port is a
    stable default "active" instance when the caller has no explicit selection.
    """
    if dcc not in DCC_PORT_RANGES:
        return []
    probe_fn = probe if probe is not None else socket_manager.probe_port
    ports = list(dcc_port_range(dcc))
    if probe is None:
        # Windows makes a connect to a CLOSED localhost port wait the whole timeout
        # (8 ports = 2.4 s per DCC, every status push). The LISTEN table (one netstat,
        # cached) says which ports are open: only those are probed (a listener that
        # never accepts, a stuck Maya, still fails the probe).
        from core.dcc_identity import listener_pids
        listening = listener_pids()
        if listening:
            ports = [port for port in ports if port in listening]
    if pid_of is None:
        # A faked probe (tests) has no real listener: no pid lookup then.
        from core.dcc_identity import pid_on_port
        pid_of = pid_on_port if probe is None else (lambda _port: None)
    return [
        make_instance(dcc, port, pid=pid_of(port))
        for port in ports
        if probe_fn(port, timeout)
    ]


def scan_all_instances(*, probe=None, timeout: float = _SCAN_TIMEOUT_S) -> dict[str, list[dict]]:
    """Discover instances for every known DCC. Returns {dcc: [instance, ...]}."""
    return {dcc: scan_instances(dcc, probe=probe, timeout=timeout) for dcc in DCC_PORT_RANGES}


# ── Active instance (which one a publish / import talks to) ─────────────────
# Chosen in the UI (sidebar menu, publish picker) and pushed here, so backend
# clients with a single entry point (houdini_client) follow the same choice as the
# routes that take an explicit port (Maya). Remembered as (port, pid): a port now held
# by another process is a closed instance (reported in _LOST, never targeted).
# In memory: a restart forgets it, the UI pushes its choice again.
_ACTIVE: dict[str, tuple[int, int | None]] = {}
_LOST: dict[str, dict] = {}


class InstanceLostError(RuntimeError):
    """The chosen instance was closed and several others run: FLUX will not guess."""


def _current_pid(port: int) -> int | None:
    from core.dcc_identity import pid_on_port
    return pid_on_port(port)


def set_active_port(dcc: str, port: int | None, pid: int | None = None) -> None:
    """Remember the instance of *dcc* the user works with (None clears it). *pid*
    defaults to the process now listening on the port."""
    if dcc not in DCC_PORT_RANGES:
        raise ValueError(f"unknown DCC: {dcc}")
    _LOST.pop(dcc, None)
    if port is None:
        _ACTIVE.pop(dcc, None)
        return
    if int(port) not in dcc_port_range(dcc):
        raise ValueError(f"port {port} outside the {dcc} range")
    _ACTIVE[dcc] = (int(port), pid if pid is not None else _current_pid(int(port)))


def check_active(dcc: str, *, pid_of=None) -> int | None:
    """The chosen port when its process is still the chosen one, else None (and the
    loss is kept in lost_active())."""
    entry = _ACTIVE.get(dcc)
    if entry is None:
        return None
    port, pid = entry
    now = (pid_of or _current_pid)(port)
    if pid is not None and now != pid:
        _LOST[dcc] = {"port": port, "pid": pid, "now_pid": now, "at": time.time()}
        _ACTIVE.pop(dcc, None)
        return None
    return port


def get_active_port(dcc: str) -> int | None:
    """Instance port chosen for *dcc* (still the same process), or None."""
    return check_active(dcc)


def active_info(dcc: str) -> dict | None:
    entry = _ACTIVE.get(dcc)
    return {"port": entry[0], "pid": entry[1]} if entry else None


def lost_active(dcc: str) -> dict | None:
    """{"port", "pid", "now_pid", "at"} when the chosen instance went away."""
    return _LOST.get(dcc)


def resolve_port(dcc: str, *, instances: list[dict] | None = None, pid_of=None) -> int:
    """Port to talk to when the caller gives none (Houdini client).

    The chosen instance when it still runs; else, when the choice was lost, the only
    running instance (it cannot be confused) or InstanceLostError when several run;
    with no choice at all: the lowest running instance, else the base port."""
    port = check_active(dcc, pid_of=pid_of)
    if port is not None:
        return port
    live = instances if instances is not None else scan_instances(dcc)
    if dcc in _LOST and len(live) > 1:
        raise InstanceLostError(
            f"L'instance {dcc} choisie (port {_LOST[dcc]['port']}) a ete fermee et {len(live)} autres tournent : "
            "choisis celle qui travaille dans la barre laterale de FLUX.")
    if live:
        return int(live[0]["port"])
    base, _count = DCC_PORT_RANGES[dcc]
    return base
