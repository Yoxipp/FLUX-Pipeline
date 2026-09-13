"""
FLUX Mari bridge plugin (V6 B7, SKELETON — finish/verify live).

Runs inside Mari (the `mari` module). Starts a local TCP server (newline-JSON) so
the FLUX backend can ping Mari and trigger a channel export.

Protocol:
  {"action": "ping"}                                    -> {"status": "ok", "version": "..."}
  {"action": "export", "export_path": "...", "file_format": "tif"} -> {"status": "ok", "files": [...]}

NOTE: Mari's export API is version-specific; the export below (current geo channels
-> exportImages) is defensive and must be verified against the installed Mari.
"""

from __future__ import annotations

import json
import os
import socket
import threading

try:
    import mari
    _MARI_AVAILABLE = True
except Exception:  # noqa: BLE001 - importable from the backend for a syntax check
    mari = None
    _MARI_AVAILABLE = False

HOST = "127.0.0.1"
# Base of Mari's assigned range (DCC_PORT_RANGES["Mari"]); env override for
# multi-instance. Must match the backend client / status scan port.
PORT = int(os.environ.get("FLUX_MARI_PORT", "7070"))

_server_sock: "socket.socket | None" = None


def _do_export(export_path: str, file_format: str) -> dict:
    if not _MARI_AVAILABLE:
        return {"status": "error", "msg": "mari module not available"}
    try:
        geo = mari.geo.current()
        files: list[str] = []
        os.makedirs(export_path, exist_ok=True)
        for channel in geo.channelList():
            # Template with the channel name; Mari fills UDIM/token itself.
            out = os.path.join(export_path, f"{geo.name()}_{channel.name()}.$UDIM.{file_format}")
            try:
                channel.exportImages(out)
                files.append(out)
            except Exception as exc:  # noqa: BLE001 - one bad channel never aborts all
                print(f"[FLUX] Mari channel export failed ({channel.name()}): {exc}")
        return {"status": "ok", "files": files}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "msg": str(exc)}


def _dispatch(cmd: dict) -> dict:
    action = cmd.get("action", "")
    if action == "ping":
        ver = getattr(mari.app, "version", lambda: "")() if _MARI_AVAILABLE and mari else ""
        return {"status": "ok", "version": f"Mari {ver}".strip()}
    if action == "export":
        return _do_export(cmd.get("export_path", ""), cmd.get("file_format", "tif"))
    return {"status": "error", "msg": f"unknown action: {action}"}


def _handle(conn: socket.socket) -> None:
    try:
        buf = b""
        while b"\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                return
            buf += chunk
        resp = _dispatch(json.loads(buf.split(b"\n")[0].decode("utf-8")))
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


def start() -> None:
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
        print(f"[FLUX] Mari bridge listening on {HOST}:{PORT}")
    except OSError as exc:
        print(f"[FLUX] Mari bridge bind failed: {exc}")


if __name__ == "__main__":
    start()
