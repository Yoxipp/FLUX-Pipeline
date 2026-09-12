"""
FLUX Substance Painter bridge plugin (V6 B2, SKELETON — finish/verify live).

Place in Painter's Python plugins dir (installed by autostart.py). Painter loads
every plugin module and calls start_plugin() at launch. This starts a small local
TCP server (newline-JSON) so the FLUX backend can ping Painter and trigger an
export via the substance_painter API.

Protocol:
  {"action": "ping"}                       -> {"status": "ok", "version": "..."}
  {"action": "export", "config": {...}}    -> {"status": "ok", "files": [...]}

NOTE: export_project_textures' result shape is version-specific; the flattening
below is defensive and must be verified against the installed Painter version.
"""

from __future__ import annotations

import json
import socket
import threading

try:
    import substance_painter.export as _sp_export
    import substance_painter as _sp
    _SP_AVAILABLE = True
except Exception:  # noqa: BLE001 - importable from the backend for a syntax check
    _sp_export = None
    _sp = None
    _SP_AVAILABLE = False

HOST = "127.0.0.1"
PORT = 9880

_server_sock: "socket.socket | None" = None


def _flatten_export_result(result) -> list[str]:
    """Best-effort: pull every written file path out of an export result."""
    files: list[str] = []
    textures = getattr(result, "textures", None)
    if isinstance(textures, dict):
        for paths in textures.values():
            for p in (paths or []):
                files.append(str(p))
    return files


def _do_export(config: dict) -> dict:
    if not _SP_AVAILABLE:
        return {"status": "error", "msg": "substance_painter module not available"}
    try:
        result = _sp_export.export_project_textures(config)
        return {"status": "ok", "files": _flatten_export_result(result)}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "msg": str(exc)}


def _dispatch(cmd: dict) -> dict:
    action = cmd.get("action", "")
    if action == "ping":
        ver = getattr(_sp, "__version__", "") if _sp else ""
        return {"status": "ok", "version": f"Substance Painter {ver}".strip()}
    if action == "export":
        return _do_export(cmd.get("config", {}))
    return {"status": "error", "msg": f"unknown action: {action}"}


def _handle(conn: socket.socket) -> None:
    try:
        buf = b""
        while b"\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                return
            buf += chunk
        cmd = json.loads(buf.split(b"\n")[0].decode("utf-8"))
        resp = _dispatch(cmd)
        conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
    except Exception:  # noqa: BLE001
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


def start_plugin() -> None:  # Painter entry point
    global _server_sock
    if _server_sock is not None:
        return
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((HOST, PORT))
        sock.listen(5)
        _server_sock = sock
        threading.Thread(target=_serve, args=(sock,), daemon=True).start()
        print(f"[FLUX] Substance Painter bridge listening on {HOST}:{PORT}")
    except OSError as exc:
        print(f"[FLUX] Substance Painter bridge bind failed: {exc}")


def close_plugin() -> None:  # Painter entry point
    global _server_sock
    if _server_sock is not None:
        try:
            _server_sock.close()
        except OSError:
            pass
        _server_sock = None


if __name__ == "__main__":
    start_plugin()
