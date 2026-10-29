"""
FLUX — Houdini HTTP client.
Called from the FLUX backend to communicate with a running Houdini instance.
No Houdini install required on the caller side — pure stdlib.

Usage:
    from dcc.houdini.client import HoudiniClient
    client = HoudiniClient()
    if client.ping().get("ok"):
        print(client.state())
        print(client.run("result = hou.frame()"))
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Any, Callable

HOUDINI_HTTP_PORT = 48884


class HoudiniClient:
    """Sync HTTP client for flux_houdini_server running inside Houdini."""

    def __init__(self, host: str = "127.0.0.1", port: int | None = None) -> None:
        # port None = follow the Houdini instance chosen in FLUX (several Houdini can
        # run, each on its own port 48884..48891), else the base port.
        self._host = host
        self._port = port

    @property
    def port(self) -> int:
        if self._port is not None:
            return self._port
        # The chosen instance while it is the same process; never a Houdini that took
        # its port back (A1). Raises InstanceLostError: reported as an error dict.
        from core.dcc_instances import resolve_port

        return resolve_port("Houdini")

    @property
    def base(self) -> str:
        return f"http://{self._host}:{self.port}"

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def ping(self) -> dict:
        """Alive check. Returns {"ok": True, "version": "...", "flux": True} or {"error": ...}."""
        return self._get("/ping")

    def is_connected(self) -> bool:
        return self.ping().get("ok", False) is True

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def state(self) -> dict:
        """
        Return current Houdini state.
        Falls back to /run for selected_node_types when the deployed server
        pre-dates that field — /run has always existed in all server versions.
        """
        result = self._get("/state")
        if "error" in result:
            return result
        if "selected_node_types" not in result and result.get("selected_nodes"):
            r = self.run(
                "result = {n.path(): n.type().name() for n in hou.selectedNodes()}"
            )
            if r.get("ok") and isinstance(r.get("result"), dict):
                result["selected_node_types"] = r["result"]
        return result

    def run(self, code: str, timeout: float = 600.0) -> dict:
        """
        Execute Python code on Houdini's main thread.
        Assign to `result` to return a value:
            client.run("result = hou.frame()")
        Returns {"ok": True, "result": ...} or {"ok": False, "error": "..."}.

        *timeout* is generous by default so ROP cooks / heavy exports are not
        reported as failures while Houdini is still working.
        """
        return self._post("/run", {"code": code}, timeout=timeout)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def selected_nodes(self) -> list:
        return self.state().get("selected_nodes", [])

    def get_parm(self, node_path: str, parm_name: str) -> Any:
        r = self.run(f"result = hou.node({node_path!r}).parm({parm_name!r}).eval()")
        return r.get("result")

    def set_parm(self, node_path: str, parm_name: str, value: Any) -> dict:
        return self.run(f"hou.node({node_path!r}).parm({parm_name!r}).set({value!r})")

    # ------------------------------------------------------------------
    # SSE push subscription
    # ------------------------------------------------------------------

    def subscribe(
        self,
        callback: Callable[[dict], None],
        *,
        daemon: bool = True,
    ) -> threading.Thread:
        """
        Subscribe to Houdini state changes without polling.
        Houdini pushes an event whenever selection, frame, or network path changes.
        Returns the background thread (daemon by default).
        """
        def _listen() -> None:
            req = urllib.request.Request(f"{self.base}/events")
            try:
                with urllib.request.urlopen(req) as resp:
                    for raw_line in resp:
                        line = raw_line.decode().rstrip("\r\n")
                        if line.startswith("data: "):
                            try:
                                callback(json.loads(line[6:]))
                            except (json.JSONDecodeError, Exception):
                                pass
            except urllib.error.URLError:
                pass

        t = threading.Thread(target=_listen, daemon=daemon, name="flux-hou-sse")
        t.start()
        return t

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    # Public names of the transport (Flows bridge.http_call, 02 §9): same calls,
    # never raise, {"ok": False, "error"} on failure.
    def get(self, path: str, timeout: float = 3.0) -> dict:
        return self._get(path, timeout=timeout)

    def post(self, path: str, data: dict, timeout: float = 10.0) -> dict:
        return self._post(path, data, timeout=timeout)

    def _get(self, path: str, timeout: float = 3.0) -> dict:
        try:
            with urllib.request.urlopen(f"{self.base}{path}", timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.URLError as exc:
            return {"error": str(exc), "ok": False}
        except Exception as exc:
            return {"error": str(exc), "ok": False}

    def _post(self, path: str, data: dict, timeout: float = 10.0) -> dict:
        body = json.dumps(data).encode()
        try:
            req = urllib.request.Request(
                f"{self.base}{path}",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.URLError as exc:
            return {"error": str(exc), "ok": False}
        except Exception as exc:
            return {"error": str(exc), "ok": False}


# Module-level singleton — import and use directly
houdini_client = HoudiniClient()
