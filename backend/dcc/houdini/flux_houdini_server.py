"""
FLUX — Houdini local HTTP server.
Runs inside Houdini. Deployed to %APPDATA%/FLUX/dcc/houdini/ and auto-started
via 123.py when FLUX autostart is installed.

Endpoints:
    GET  /ping    → version info
    GET  /state   → selected nodes, current path, frame, fps, hip file
    POST /run     → execute Python code on Houdini main thread
                    assign to `result` to return data back
    GET  /events  → SSE stream — pushes state changes without polling

Stop:   flux_houdini_server.stop()
"""

import json
import queue
import socketserver
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

import hou

FLUX_PORT = 48884

# Benign client-side disconnects (FLUX cancels / closes the socket before we
# finish writing). WinError 10053 surfaces as ConnectionAbortedError. Swallow
# these with a single line — they are not server faults, so never a stack trace.
_CLIENT_ABORT = (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)

_request_queue: "queue.Queue[tuple]" = queue.Queue()
_response_store: dict = {}
_response_lock = threading.Lock()
_httpd: HTTPServer | None = None

_event_clients: "list[queue.Queue]" = []
_event_clients_lock = threading.Lock()
_last_pushed_state: dict = {}


class _ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    """One thread per connection so SSE doesn't block /run or /state."""
    daemon_threads = True


class _Handler(BaseHTTPRequestHandler):

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, default=str).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except _CLIENT_ABORT as exc:
            # FLUX hung up before the response was flushed — expected on cancel.
            print(f"[FLUX] client disconnected during response ({type(exc).__name__})")

    def _dispatch(self, kind: str, payload=None, timeout: float = 8.0) -> dict:
        req_id = str(uuid.uuid4())
        evt = threading.Event()
        _request_queue.put((kind, req_id, payload, evt))
        if evt.wait(timeout=timeout):
            with _response_lock:
                return _response_store.pop(req_id, {"error": "missing result"})
        # Timed out waiting: drop any late result so it doesn't leak in the store.
        with _response_lock:
            _response_store.pop(req_id, None)
        return {"ok": False, "error": "timeout: main thread may be busy"}

    def _from_browser(self) -> bool:
        """True when the request comes from a web browser (security, S2).

        Browsers always attach Origin and/or Sec-Fetch-Site; the FLUX backend client
        (urllib) sends neither. Refusing browser requests stops any web page, even
        through DNS rebinding, from reaching /run and executing code in Houdini.
        """
        return bool(self.headers.get("Origin") or self.headers.get("Sec-Fetch-Site"))

    def do_GET(self) -> None:
        if self._from_browser():
            self._send_json({"error": "forbidden"}, 403)
            return
        if self.path == "/ping":
            self._send_json({"ok": True, "version": hou.applicationVersionString(), "flux": True})
        elif self.path == "/state":
            self._send_json(self._dispatch("state"))
        elif self.path == "/events":
            self._handle_sse()
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        # Always consume the body first: answering before reading it makes Windows
        # reset the connection and the client never sees the status.
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        if self._from_browser():
            self._send_json({"error": "forbidden"}, 403)
            return
        if self.path == "/run":
            # A JSON content type cannot be sent cross-site without a CORS preflight,
            # which this server never approves.
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                self._send_json({"error": "Content-Type must be application/json"}, 415)
                return
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                self._send_json({"error": "invalid JSON"}, 400)
                return
            # ROP cooks / heavy exports can run long; allow the main thread time.
            self._send_json(self._dispatch("run", data.get("code", ""), timeout=600.0))
        else:
            self._send_json({"error": "not found"}, 404)

    def _handle_sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        client_q: "queue.Queue[dict]" = queue.Queue(maxsize=100)
        with _event_clients_lock:
            _event_clients.append(client_q)

        try:
            while True:
                try:
                    event = client_q.get(timeout=15)
                    msg = f"data: {json.dumps(event, default=str)}\n\n"
                    self.wfile.write(msg.encode())
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with _event_clients_lock:
                if client_q in _event_clients:
                    _event_clients.remove(client_q)

    def log_message(self, *args) -> None:
        pass  # silence HTTP access log in Houdini console


def _process_queue() -> None:
    """Called by Houdini event loop — processes RPC requests and pushes SSE."""
    global _last_pushed_state

    while not _request_queue.empty():
        try:
            kind, req_id, payload, evt = _request_queue.get_nowait()
        except queue.Empty:
            break

        try:
            if kind == "state":
                result = _snapshot()
            elif kind == "run":
                ns = {"hou": hou}
                exec(compile(payload, "<flux_run>", "exec"), ns)  # noqa: S102
                result = {"ok": True, "result": ns.get("result", None)}
            else:
                result = {"error": f"unknown request kind: {kind}"}
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}

        with _response_lock:
            _response_store[req_id] = result
        evt.set()

    if not _event_clients:
        return
    try:
        current = _snapshot_compact()
        if current != _last_pushed_state:
            _last_pushed_state = current.copy()
            _push_event({"type": "state_change", **current})
    except Exception:
        pass


def _snapshot() -> dict:
    nodes = hou.selectedNodes()
    return {
        "selected_nodes":      [n.path() for n in nodes],
        "selected_node_types": {n.path(): n.type().name() for n in nodes},
        "current_path":        hou.pwd().path(),
        "frame":               hou.frame(),
        "fps":                 hou.fps(),
        "hip_file":            hou.hipFile.path(),
    }


def _snapshot_compact() -> dict:
    return {
        "selected_nodes": [n.path() for n in hou.selectedNodes()],
        "frame":          hou.frame(),
        "current_path":   hou.pwd().path(),
    }


def _push_event(event: dict) -> None:
    with _event_clients_lock:
        dead = []
        for q in _event_clients:
            try:
                q.put_nowait(event)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _event_clients.remove(q)


def _safe_status(msg: str, severity: str = "Message") -> None:
    """Set a Houdini status message, falling back to print when the UI isn't ready.

    123.py runs very early in startup — hou.ui (and its event loop) may not exist
    yet, so every hou.ui call here must be best-effort and never abort start().
    """
    try:
        hou.ui.setStatusMessage(msg, severity=getattr(hou.severityType, severity))
    except Exception:
        print(f"[FLUX] {msg}")


def _register_queue_processor(attempt: int = 0) -> None:
    """Register the main-thread queue drainer, retrying until the UI loop is ready.

    /run dispatches Python onto Houdini's main thread via this callback. If the UI
    event loop isn't up yet (early startup), retry a few times with a deferred wait
    so commands work once Houdini finishes launching — instead of silently never
    processing the queue.
    """
    try:
        hou.ui.addEventLoopCallback(_process_queue)
        return
    except Exception:
        pass
    if attempt >= 100:
        print("[FLUX] Could not register event-loop callback; /run will not work.")
        return
    # Defer on the MAIN thread (hou.ui must never be touched from a worker thread).
    try:
        import hdefereval
        hdefereval.executeDeferredAfterWaiting(lambda: _register_queue_processor(attempt + 1), 5)
    except Exception:
        print("[FLUX] hdefereval unavailable; event-loop callback not registered yet.")


def start(port: int = FLUX_PORT) -> None:
    global _httpd
    if _httpd is not None:
        _safe_status(f"[FLUX] Serveur Houdini déjà actif sur le port {_httpd.server_address[1]}")
        return

    # 1. Critical path: bind the HTTP server. This alone makes FLUX see Houdini as
    #    connected (the backend probes port 48884). If it fails, we are not connected.
    try:
        _httpd = _ThreadedHTTPServer(("127.0.0.1", port), _Handler)
        threading.Thread(target=_httpd.serve_forever, daemon=True, name="flux-houdini-http").start()
    except Exception as exc:
        _httpd = None
        _safe_status(f"[FLUX] Erreur démarrage serveur : {exc}", "Error")
        return

    # 2. Best-effort: hook the main-thread queue drainer. A failure here must NOT
    #    tear down the already-bound server (that would drop the connection handle
    #    while the port stays open — "connected but dead").
    _register_queue_processor()
    _safe_status(f"[FLUX] Bien connecté au port local {port}", "ImportantMessage")


def stop() -> None:
    global _httpd
    if _httpd is None:
        print("[FLUX] Houdini server not running.")
        return
    try:
        hou.ui.removeEventLoopCallback(_process_queue)
    except Exception:
        pass
    _httpd.shutdown()
    _httpd = None
    print("[FLUX] Houdini server stopped.")


# Auto-start when exec()'d or imported
start()
