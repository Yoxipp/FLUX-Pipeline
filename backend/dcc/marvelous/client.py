# client.py — backend-side client for the FLUX Marvelous Designer bridge.
#
# Marvelous' Python API (export_api...) runs ONLY inside Marvelous, and Marvelous 2024
# embeds a Python without _socket: no network. FLUX and the bridge script talk through
# files in a mailbox folder (%TEMP%/flux_marvelous_bridge, see marvelous_bridge.py):
#   alive.json   heartbeat the bridge rewrites every second (ping = its age)
#   <id>.req     request written here, claimed by the bridge (renamed .work)
#   <id>.resp    the bridge's answer
# Answers keep the shape of the socket bridges ({ok, ...} or {ok: False, error}).

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

ALIVE_MAX_AGE_S = 3.0   # the bridge beats every second; older = blocked or gone
# A stale heartbeat whose Marvelous process is still alive: the bridge loop is stuck in
# a modal window / a simulation (it only beats between two Windows messages), not gone.
# The bridge deletes alive.json when it stops, so a stale file = blocked or crashed.
BUSY_MAX_AGE_S = 2 * 3600.0
CLAIM_TIMEOUT_S = 10.0  # a request nobody picks up in that time: the bridge is not serving
POLL_S = 0.05
NOT_RUNNING = "bridge Marvelous non lance"
BLOCKED = ("Marvelous est occupe (une fenetre ouverte ou une simulation bloque le bridge) : "
           "ferme-la, le bridge reprend tout seul")


def mailbox_dir() -> Path:
    """Same folder as the bridge: FLUX_MD_MAILBOX_ROOT or the user's TEMP."""
    return Path(os.environ.get("FLUX_MD_MAILBOX_ROOT") or tempfile.gettempdir()) / "flux_marvelous_bridge"


def _read_alive() -> dict | None:
    try:
        data = json.loads((mailbox_dir() / "alive.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def heartbeat() -> dict | None:
    """The bridge's last heartbeat when it is fresh, else None."""
    data = _read_alive()
    if data is None or time.time() - float(data.get("time", 0)) > ALIVE_MAX_AGE_S:
        return None
    return data


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
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def blocked() -> bool:
    """The bridge stopped beating but its Marvelous still runs: busy, not gone."""
    data = _read_alive()
    if data is None:
        return False
    age = time.time() - float(data.get("time", 0))
    if age <= ALIVE_MAX_AGE_S or age > BUSY_MAX_AGE_S:
        return False
    try:
        return pid_alive(int(data.get("pid") or 0))
    except (TypeError, ValueError):
        return False


def _answer(resp: Any) -> dict:
    if not isinstance(resp, dict):
        return {"ok": False, "error": "reponse du bridge illisible"}
    resp.setdefault("ok", resp.get("status") == "ok")
    if not resp["ok"] and "error" not in resp:
        resp["error"] = str(resp.get("msg") or "erreur Marvelous")
    return resp


def call(payload: dict, timeout: float) -> dict:
    """Send one request through the mailbox and wait for the answer."""
    if heartbeat() is None:
        if blocked():
            return {"ok": False, "error": BLOCKED}
        return {"ok": False, "error": f"{NOT_RUNNING} (aucun battement dans {mailbox_dir()})"}
    box = mailbox_dir()
    rid = uuid.uuid4().hex
    req, resp = box / f"{rid}.req", box / f"{rid}.resp"
    tmp = box / f"{rid}.req.tmp"
    try:
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, req)
    except OSError as exc:
        return {"ok": False, "error": f"mailbox Marvelous inutilisable : {exc}"}
    start = time.monotonic()
    while True:
        if resp.exists():
            try:
                data = json.loads(resp.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                time.sleep(POLL_S)          # still being replaced: read again
                if time.monotonic() - start > timeout:
                    return {"ok": False, "error": "reponse du bridge illisible"}
                continue
            try:
                resp.unlink()
            except OSError:
                pass
            return _answer(data)
        waited = time.monotonic() - start
        if req.exists() and waited > CLAIM_TIMEOUT_S:
            try:
                req.unlink()                # nobody picked it up: do not leave it
            except OSError:
                pass
            return {"ok": False, "error": f"{NOT_RUNNING} (requete jamais prise, Marvelous occupe ?)"}
        if waited > timeout:
            return {"ok": False, "error": f"timeout : Marvelous n'a pas repondu en {int(timeout)} s"}
        time.sleep(POLL_S)


class MarvelousClient:
    def ping(self) -> dict:
        beat = heartbeat()
        if beat is None:
            # An export holds the bridge's loop, so it stops beating: a request being
            # served (.work) means busy, not gone.
            if any(mailbox_dir().glob("*.work")):
                return {"ok": True, "busy": True, "version": "Marvelous Designer (export en cours)"}
            if blocked():
                return {"ok": True, "busy": True, "version": "Marvelous Designer (occupe)"}
            return {"ok": False, "error": NOT_RUNNING}
        return {"ok": True, "version": beat.get("version"), "mode": beat.get("mode")}

    def info(self) -> dict:
        """Open project + formats this Marvelous can export: {ok, project, formats}."""
        return call({"action": "info"}, timeout=20.0)

    def export(self, config: dict[str, Any]) -> dict:
        """Ask Marvelous to export with *config*; returns {ok, files, warnings}."""
        return call({"action": "export", "config": config}, timeout=900.0)


marvelous_client = MarvelousClient()
