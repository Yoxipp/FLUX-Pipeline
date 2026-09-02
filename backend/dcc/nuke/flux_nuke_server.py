# flux_nuke_server.py — runs INSIDE Nuke.
#
# Nuke has no native command port, so this is a tiny line-delimited JSON socket
# server. The FLUX autostart block (dcc/nuke/autostart.py) adds the backend to
# sys.path and calls start() once, deferred, on Nuke startup.
#
# Protocol (one JSON object per line, UTF-8):
#   → {"cmd": "ping"}              ← {"ok": true, "version": "15.0v1"}
#   → {"cmd": "run", "code": "…"}  ← {"ok": true, "result": <value of `result`>}
# Code runs on Nuke's main thread; assign to a local `result` to return a value.

from __future__ import annotations

import json
import socket
import threading

try:
    import nuke  # only present inside Nuke
except ImportError:  # pragma: no cover — importable from the backend for tests
    nuke = None  # type: ignore[assignment]

_DEFAULT_PORT = 7003
_server_sock: socket.socket | None = None


def _run_code(code: str):
    g = {"nuke": nuke}
    loc: dict = {}
    exec(code, g, loc)  # noqa: S102 — trusted local hub only (127.0.0.1)
    return loc.get("result")


def _handle(conn: socket.socket) -> None:
    try:
        buf = b""
        while b"\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buf += chunk
        line = buf.split(b"\n")[0].decode("utf-8", "replace").strip()
        if not line:
            return
        req = json.loads(line)
        cmd = req.get("cmd")
        if cmd == "ping":
            ver = getattr(nuke, "NUKE_VERSION_STRING", None) if nuke else None
            resp = {"ok": True, "version": ver}
        elif cmd == "run":
            code = req.get("code", "")
            if nuke is not None:
                res = nuke.executeInMainThreadWithResult(_run_code, (code,))
            else:
                res = _run_code(code)
            resp = {"ok": True, "result": res}
        else:
            resp = {"ok": False, "error": f"unknown cmd: {cmd!r}"}
    except Exception as exc:  # never let a bad request kill the server
        resp = {"ok": False, "error": str(exc)}
    try:
        conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
    except OSError:
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


def _serve(sock: socket.socket) -> None:
    while True:
        try:
            conn, _ = sock.accept()
        except OSError:
            break
        threading.Thread(target=_handle, args=(conn,), daemon=True).start()


def start(port: int = _DEFAULT_PORT) -> None:
    """Start the FLUX bridge server (idempotent)."""
    global _server_sock
    if _server_sock is not None:
        return
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    sock.listen(5)
    _server_sock = sock
    threading.Thread(target=_serve, args=(sock,), daemon=True).start()
    print(f"[FLUX] Nuke bridge listening on 127.0.0.1:{port}")
