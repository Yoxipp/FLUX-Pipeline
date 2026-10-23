# tcp_json_server.py - FLUX extension bridge, TCP JSON (template, Flows P6c).
#
# Copy into CONFIG/extensions/bridges/<soft>/dcc_side/, adapt the bottom of the file to
# the soft (how it starts the script, which thread runs the code), list it in bridge.yml
# (install.files). FLUX writes flux_bridge.json next to it at install time:
#   {"soft": "max", "label": "3ds Max", "port_base": 7100, "port_count": 8}
#
# Protocol (one JSON object per line, one request per connection, 127.0.0.1 only):
#   {"cmd": "ping"}                -> {"ok": true, "version": "...", "soft": "..."}
#   {"cmd": "run", "code": "..."}  -> {"ok": true, "result": <value of `result`>}
#                                     | {"ok": false, "error": "...", "trace": "..."}
# SECURITY: this script runs the Python code FLUX sends. It has the same trust as the
# team's Python nodes; it only listens on 127.0.0.1 (never on the network).
# Stdlib only, Python 3.7+ (the oldest Python of the softs this template targets).

import json
import os
import socket
import threading
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = "flux-extension-bridge 1"


def load_config():
    cfg = {"soft": "extension", "label": "Extension", "port_base": 7100, "port_count": 8}
    try:
        with open(os.path.join(HERE, "flux_bridge.json"), encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    except (OSError, ValueError):
        pass
    return cfg


def _dumps(data):
    try:
        return json.dumps(data)
    except (TypeError, ValueError):
        data = dict(data)
        data["result"] = repr(data.get("result"))
        return json.dumps(data)


class Bridge(object):
    """``executor(fn)`` runs fn() where the soft allows its API (default: right here);
    ``extra_globals`` are given to the code (e.g. {"rt": pymxs.runtime})."""

    def __init__(self, executor=None, extra_globals=None, soft_version=""):
        self.cfg = load_config()
        self.executor = executor or (lambda fn: fn())
        self.extra_globals = dict(extra_globals or {})
        self.soft_version = soft_version
        self.port = None
        self._sock = None
        self._stop = threading.Event()

    def _run(self, code):
        box = {}

        def job():
            ns = {"__name__": "__flux_flows__"}
            ns.update(self.extra_globals)
            try:
                exec(compile(code, "<flux flow>", "exec"), ns)
                box["out"] = {"ok": True, "result": ns.get("result")}
            except Exception as exc:  # reported to FLUX
                box["out"] = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc),
                              "trace": traceback.format_exc()}

        self.executor(job)
        return box.get("out") or {"ok": False, "error": "le code n'a pas ete execute"}

    def handle(self, request):
        cmd = request.get("cmd")
        if cmd == "ping":
            return {"ok": True, "version": self.soft_version or VERSION, "soft": self.cfg.get("soft")}
        if cmd == "run":
            return self._run(str(request.get("code") or ""))
        return {"ok": False, "error": "commande inconnue: %r" % (cmd,)}

    def _serve(self, conn):
        try:
            conn.settimeout(600)
            buf = b""
            while b"\n" not in buf:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
            try:
                request = json.loads(buf.split(b"\n")[0].decode("utf-8"))
                response = self.handle(request if isinstance(request, dict) else {})
            except ValueError as exc:
                response = {"ok": False, "error": "requete illisible: %s" % exc}
            conn.sendall((_dumps(response) + "\n").encode("utf-8"))
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def start(self):
        """Listen on the first free port of the range (127.0.0.1). Returns the port."""
        base, count = int(self.cfg["port_base"]), int(self.cfg["port_count"])
        for port in range(base, base + count):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                sock.close()
                continue
            sock.listen(4)
            sock.settimeout(0.5)
            self._sock, self.port = sock, port
            thread = threading.Thread(target=self._loop, name="flux-extension-bridge")
            thread.daemon = True
            thread.start()
            return port
        raise RuntimeError("aucun port libre dans %d..%d" % (base, base + count - 1))

    def _loop(self):
        while not self._stop.is_set():
            try:
                conn, _addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._serve, args=(conn,)).start()

    def stop(self):
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass


def start(executor=None, extra_globals=None, soft_version=""):
    bridge = Bridge(executor, extra_globals, soft_version)
    bridge.start()
    return bridge


if __name__ == "__main__":
    # A fake soft from a terminal (P6c live check without the soft): python tcp_json_server.py
    import time

    b = start()
    print("FLUX extension bridge on 127.0.0.1:%d (Ctrl+C to stop)" % b.port)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        b.stop()
