# dcc_identity.py — who is really behind a DCC port (A1, 2026-09-27).
#
# An instance was identified by its port only. A Houdini closed then reopened takes the
# same port back: FLUX kept targeting "48884" and published from the new scene without a
# word. The identity of an instance is now (port, pid), plus its open scene and version.
#
#   listener_pids()   {port: pid} of every LISTEN socket (one netstat for all ports)
#   process_names()   {pid: exe} (one tasklist)
#   running_pids(dcc) pids of that DCC running (the bridge may not be loaded)
#   details(dcc, port, pid)  {"scene", "version", "state"}: state "connected" or "busy"
#                     (accepts the connection, does not answer in time: an export runs)
#
# Everything is cached a couple of seconds: the status push scans every DCC every 2 s.

from __future__ import annotations

import os
import re
import subprocess
import threading
import time

_LISTEN_TTL = 1.5
_PROC_TTL = 5.0
# Scene / version of a free instance, and the "busy" answer (re-checked sooner).
_DETAIL_TTL = 8.0
_BUSY_TTL = 3.0

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_lock = threading.Lock()
_cache: dict[str, tuple[float, object]] = {}

# Exe name pieces of an interactive session per DCC (headless / helper processes excluded:
# FLUX runs hython and mayapy itself, they are not an artist's session).
SESSION_NAMES: dict[str, tuple[str, ...]] = {
    "Maya":       ("maya.exe",),
    "Houdini":    ("houdini", "hindie", "happrentice", "houdinifx", "houdinicore"),
    "Nuke":       ("nuke",),
    "SubstanceP": ("painter",),
    "SubstanceD": ("substance 3d designer", "substance designer"),
    "Mari":       ("mari",),
    "Unreal":     ("unrealeditor.exe",),
    "ZBrush":     ("zbrush",),
}
_EXCLUDED = ("hython", "hbatch", "hserver", "mayapy", "mayabatch", "mayabatch", "husk", "hescape", "unrealeditor-cmd")


def _run(args: list[str]) -> str:
    try:
        out = subprocess.run(args, capture_output=True, timeout=6, creationflags=_NO_WINDOW)
        return (out.stdout or b"").decode("latin-1", "replace")
    except (OSError, subprocess.SubprocessError):
        return ""


def _cached(key: str, ttl: float, fetch):
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit is not None and now - hit[0] < ttl:
            return hit[1]
    value = fetch()
    with _lock:
        _cache[key] = (time.monotonic(), value)
    return value


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def parse_netstat(text: str) -> dict[int, int]:
    """{port: pid} of the LISTEN lines of ``netstat -ano`` (first pid per port)."""
    out: dict[int, int] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 5 or not parts[3].upper().startswith("LISTEN") or not parts[-1].isdigit():
            continue
        m = re.search(r":(\d+)$", parts[1])
        if m:
            out.setdefault(int(m.group(1)), int(parts[-1]))
    return out


def parse_tasklist(text: str) -> dict[int, str]:
    """{pid: exe} of ``tasklist /FO CSV /NH``."""
    out: dict[int, str] = {}
    for line in text.splitlines():
        m = re.match(r'"([^"]+)","(\d+)"', line.strip())
        if m:
            out[int(m.group(2))] = m.group(1)
    return out


def listener_pids() -> dict[int, int]:
    if os.name != "nt":
        return {}
    return _cached("listen", _LISTEN_TTL, lambda: parse_netstat(_run(["netstat", "-ano", "-p", "TCP"])))


def process_names() -> dict[int, str]:
    if os.name != "nt":
        return {}
    return _cached("procs", _PROC_TTL, lambda: parse_tasklist(_run(["tasklist", "/FO", "CSV", "/NH"])))


def pid_on_port(port: int) -> int | None:
    pid = listener_pids().get(int(port))
    return pid if pid and pid != os.getpid() else None


def is_session(dcc: str, exe: str) -> bool:
    name = exe.lower()
    if any(x in name for x in _EXCLUDED):
        return False
    return any(piece in name for piece in SESSION_NAMES.get(dcc, ()))


def running_pids(dcc: str, procs: dict[int, str] | None = None) -> list[int]:
    """Pids of interactive sessions of *dcc* (with or without the FLUX bridge)."""
    if dcc not in SESSION_NAMES:
        return []
    procs = process_names() if procs is None else procs
    return sorted(pid for pid, exe in procs.items() if is_session(dcc, exe))


def live_instances(dcc: str, instances: list[dict], procs: dict[int, str]) -> list[dict]:
    """Drop ghost instances (B5): the pid on the port is dead, or is not a session of *dcc*.

    Only for DCCs whose session exe is known, and only when the process list was read
    (an empty list = tasklist failed: keep everything rather than hide real instances).
    An instance without pid (netstat failed) is kept.
    """
    if dcc not in ("Maya", "Houdini") or not procs:
        return instances
    return [i for i in instances
            if not i.get("pid") or is_session(dcc, procs.get(i["pid"], ""))]


def unbridged_pids(dcc: str, instances: list[dict], procs: dict[int, str]) -> list[int]:
    """Sessions of *dcc* running without a FLUX bridge (no instance holds their pid)."""
    bridged = {i.get("pid") for i in instances}
    if None in bridged:          # pid unknown: cannot tell which session it is
        return [] if instances else running_pids(dcc, procs)
    return [pid for pid in running_pids(dcc, procs) if pid not in bridged]


# ── scene / version / busy ─────────────────────────────────────────────────────

_MAYA_INFO = ("'\\n'.join([__import__('maya.cmds', fromlist=['cmds']).file(q=True, sceneName=True) or '',"
              " __import__('maya.cmds', fromlist=['cmds']).about(version=True)])")


def _fetch_details(dcc: str, port: int) -> dict:
    """Ask the bridge; a connection that does not answer in time is a busy instance."""
    if dcc == "Maya":
        from dcc.maya.maya_connection import send_command_direct

        res = send_command_direct(_MAYA_INFO, timeout=0.8, port=port)
        if res is None:
            return {"scene": None, "version": None, "state": "busy"}
        lines = [ln.strip() for ln in res.replace("\x00", "").splitlines()]
        return {"scene": (lines[0] if lines else "") or "", "version": lines[1] if len(lines) > 1 else None,
                "state": "connected"}
    if dcc == "Houdini":
        from dcc.houdini.client import HoudiniClient

        client = HoudiniClient(port=port)
        ping = client._get("/ping", timeout=0.6)
        state = client._get("/state", timeout=0.8)        # main thread: slow while it works
        if "error" in state:
            return {"scene": None, "version": ping.get("version"), "state": "busy"}
        return {"scene": str(state.get("hip_file") or ""), "version": ping.get("version"), "state": "connected"}
    return {"scene": None, "version": None, "state": "connected"}


def details(dcc: str, port: int, pid: int | None) -> dict:
    """{"scene", "version", "state"} of the instance (cached per port + pid)."""
    key = f"detail:{dcc}:{port}:{pid}"
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit is not None:
            ttl = _BUSY_TTL if hit[1].get("state") == "busy" else _DETAIL_TTL  # type: ignore[union-attr]
            if now - hit[0] < ttl:
                return dict(hit[1])  # type: ignore[arg-type]
    try:
        value = _fetch_details(dcc, port)
    except Exception:                            # noqa: BLE001 - identity is best effort
        value = {"scene": None, "version": None, "state": "connected"}
    with _lock:
        _cache[key] = (time.monotonic(), value)
    return dict(value)


def scene_label(scene: str | None) -> str:
    """Short name of a scene path ("sans titre" for an unsaved one)."""
    if scene is None:
        return ""
    name = scene.replace("\\", "/").rsplit("/", 1)[-1]
    return name or "sans titre"
