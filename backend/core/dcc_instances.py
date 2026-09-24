# dcc_instances.py — discover running instances of each DCC (cluster C).
#
# Multi-instance model: a DCC no longer owns a single fixed port but a RANGE
# (constants.DCC_PORT_RANGES). Each running instance holds one open port in that
# range. Discovery = scan the range and report every reachable port as one
# instance. Instance identity is the port itself (unique on localhost), exposed
# as a stable string id "<dcc>:<port>".
#
# Per-instance identity details (pid, open scene, DCC version) are filled in by
# the DCC-side bridges in a later phase; this module returns the transport-level
# facts (port, reachability) plus a human label, and leaves richer fields None so
# the shape is already stable for the router and the frontend.

from __future__ import annotations

from core.constants import DCC_PORT_RANGES, dcc_port_range
from core.socket_manager import socket_manager

# Short probe: a closed localhost port refuses almost instantly (RST), so a tight
# timeout keeps a full-range scan cheap even across every DCC on each status push.
_SCAN_TIMEOUT_S: float = 0.3


def instance_id(dcc: str, port: int) -> str:
    """Stable identifier for one DCC instance. Port is unique per localhost."""
    return f"{dcc}:{port}"


def make_instance(dcc: str, port: int, connected: bool = True) -> dict:
    """Build the canonical instance record. Rich fields stay None until the
    DCC-side bridge reports them (later phase); the shape is fixed now."""
    return {
        "id":        instance_id(dcc, port),
        "dcc":       dcc,
        "port":      port,
        "connected": connected,
        "pid":       None,    # filled by the DCC-side identity query (phase 5)
        "scene":     None,    # open scene/hip file, when the bridge reports it
        "version":   None,    # DCC version string, when the bridge reports it
        "label":     f"{dcc} :{port}",
    }


def scan_instances(dcc: str, *, probe=None, timeout: float = _SCAN_TIMEOUT_S) -> list[dict]:
    """Probe every port in *dcc*'s range; return one record per reachable port.

    *probe* defaults to socket_manager.probe_port and is injectable for tests.
    Returns instances ordered by port (ascending), so the lowest open port is a
    stable default "active" instance when the caller has no explicit selection.
    """
    if dcc not in DCC_PORT_RANGES:
        return []
    probe_fn = probe if probe is not None else socket_manager.probe_port
    return [
        make_instance(dcc, port)
        for port in dcc_port_range(dcc)
        if probe_fn(port, timeout)
    ]


def scan_all_instances(*, probe=None, timeout: float = _SCAN_TIMEOUT_S) -> dict[str, list[dict]]:
    """Discover instances for every known DCC. Returns {dcc: [instance, ...]}."""
    return {dcc: scan_instances(dcc, probe=probe, timeout=timeout) for dcc in DCC_PORT_RANGES}


# ── Active instance (which one a publish / import talks to) ─────────────────
# Chosen in the UI (sidebar menu, publish picker) and pushed here, so backend
# clients with a single entry point (houdini_client) follow the same choice as the
# routes that take an explicit port (Maya). In memory: a restart falls back to the
# base port, the UI pushes its choice again.
_ACTIVE_PORTS: dict[str, int] = {}


def set_active_port(dcc: str, port: int | None) -> None:
    """Remember the instance port of *dcc* the user works with (None clears it)."""
    if dcc not in DCC_PORT_RANGES:
        raise ValueError(f"unknown DCC: {dcc}")
    if port is None:
        _ACTIVE_PORTS.pop(dcc, None)
        return
    if int(port) not in dcc_port_range(dcc):
        raise ValueError(f"port {port} outside the {dcc} range")
    _ACTIVE_PORTS[dcc] = int(port)


def get_active_port(dcc: str) -> int | None:
    """Instance port chosen for *dcc*, or None (use the base port)."""
    return _ACTIVE_PORTS.get(dcc)

