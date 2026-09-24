# json_bridge.py — one request to an in-app FLUX bridge (Nuke, Mari, Painter, ZBrush).
#
# Protocol shared by the bridges: one JSON object per line over a local TCP socket.
# A new connection per request: send the payload + "\n", read until the first "\n".

from __future__ import annotations

import json
import socket

from core.constants import CONNECT_TIMEOUT_S


def send_json_line(host: str, port: int, payload: dict, timeout: float, *,
                   status_to_ok: bool = True, protocol_error_prefix: str = "") -> dict:
    """Send *payload*, return the bridge's JSON answer, or {"ok": False, "error"}.

    *status_to_ok*: bridges that answer {"status": "ok"} also get {"ok": True}.
    *protocol_error_prefix*: prefix of the message when the answer is not JSON."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(min(timeout, CONNECT_TIMEOUT_S))
            s.connect((host, port))
            s.settimeout(timeout)
            s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    line = buf.split(b"\n")[0].decode("utf-8", "replace").strip()
    if not line:
        return {"ok": False, "error": "empty response"}
    try:
        result = json.loads(line)
    except ValueError as exc:
        return {"ok": False, "error": f"{protocol_error_prefix}{exc}"}
    if not isinstance(result, dict):
        return {"ok": False, "error": f"{protocol_error_prefix}not a JSON object"}
    if status_to_ok and "ok" not in result:
        result["ok"] = result.get("status") == "ok"
    # Bridges report failures as {"status": "error", "msg": ...}: expose it as "error"
    # so callers show the real reason instead of a generic "export failed".
    if not result.get("ok") and "error" not in result and result.get("msg"):
        result["error"] = str(result["msg"])
    return result
