# events.py — the internal message bus of the Flows (01_ARCHITECTURE §1, §10).
#
# A leaf module: stdlib only, importable from anywhere (features/ will emit
# on_publish through it in P5). The engine emits run messages (run_started,
# node_state, link_value, log, run_finished, notify); each WS client of
# /flows/ws holds one Subscription.
#
# Thread safe: emit() may be called from a worker thread; the message is handed
# to the subscriber's event loop with call_soon_threadsafe. No subscriber = no-op.
# A subscription keeps at most MAX_QUEUE messages: link_value and log are dropped
# first, then the oldest message, never run_finished.
#
# P5: local listeners (``listen`` / ``signal``) carry the events born in a backend
# (publish_done for event.on_publish) to the scheduler, never to the WS. publish_done
# is the only entry point features/ uses: it is cut by FLUX_FLOWS_HOOKS=0 (read at each
# call, like flux_actions/switch.py), a no-op without listener, and never raises.

from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections import deque
from typing import Any, Deque, Dict, List, Optional

MAX_QUEUE = 500
DROP_FIRST = ("link_value", "log")
NEVER_DROP = ("run_finished",)


class Subscription:
    """Messages for one listener, filtered by run_id / flow (None = everything)."""

    def __init__(self, loop: asyncio.AbstractEventLoop, max_queue: int = MAX_QUEUE) -> None:
        self.loop = loop
        self.max_queue = max_queue
        self.run_id: Optional[str] = None
        self.flow: Optional[str] = None
        self.dropped = 0
        self._queue: Deque[Dict[str, Any]] = deque()
        self._ready = asyncio.Event()
        self._closed = False

    def set_filter(self, run_id: Optional[str] = None, flow: Optional[str] = None) -> None:
        self.run_id, self.flow = run_id or None, flow or None

    def wants(self, message: Dict[str, Any]) -> bool:
        if self.run_id and message.get("run_id") not in (None, self.run_id):
            return False
        if self.flow and message.get("flow") not in (None, self.flow):
            return False
        return True

    def _drop_one(self) -> bool:
        for kinds in (DROP_FIRST, None):
            for i, msg in enumerate(self._queue):
                kind = msg.get("type")
                if (kinds is None and kind not in NEVER_DROP) or (kinds is not None and kind in kinds):
                    del self._queue[i]
                    self.dropped += 1
                    return True
        return False

    def push(self, message: Dict[str, Any]) -> None:
        """Called on the subscriber's loop."""
        if self._closed or not self.wants(message):
            return
        while len(self._queue) >= self.max_queue:
            if not self._drop_one():
                break
        self._queue.append(message)
        self._ready.set()

    async def get(self) -> Dict[str, Any]:
        while not self._queue:
            self._ready.clear()
            await self._ready.wait()
        return self._queue.popleft()

    def pending(self) -> List[Dict[str, Any]]:
        return list(self._queue)

    def close(self) -> None:
        self._closed = True


_SUBS: List[Subscription] = []
_LOCK = threading.Lock()


def subscribe(loop: Optional[asyncio.AbstractEventLoop] = None,
              max_queue: int = MAX_QUEUE) -> Subscription:
    sub = Subscription(loop or asyncio.get_running_loop(), max_queue)
    with _LOCK:
        _SUBS.append(sub)
    return sub


def unsubscribe(sub: Subscription) -> None:
    sub.close()
    with _LOCK:
        if sub in _SUBS:
            _SUBS.remove(sub)


def has_subscribers() -> bool:
    with _LOCK:
        return bool(_SUBS)


def emit(message: Dict[str, Any]) -> None:
    """Hand *message* to every subscriber, from any thread. Never raises."""
    with _LOCK:
        subs = list(_SUBS)
    if not subs:
        return
    try:
        current = asyncio.get_running_loop()
    except RuntimeError:
        current = None
    for sub in subs:
        try:
            if sub.loop is current:
                sub.push(message)
            elif not sub.loop.is_closed():
                sub.loop.call_soon_threadsafe(sub.push, message)
        except RuntimeError:  # loop closed between the check and the call
            continue


# -- local listeners (P5) ---------------------------------------------------------------

HOOKS_ENV = "FLUX_FLOWS_HOOKS"
_FALSE = {"0", "false", "no", "off"}
_LISTENERS: Dict[str, List[tuple]] = {}
_log = logging.getLogger("flux.flows.events")


def hooks_enabled() -> bool:
    """False when FLUX_FLOWS_HOOKS is falsey (rollback switch, read at each call)."""
    return os.environ.get(HOOKS_ENV, "1").strip().lower() not in _FALSE


def listen(kind: str, callback, loop: Optional[asyncio.AbstractEventLoop] = None) -> tuple:
    """Call ``callback(payload)`` on *loop* for each ``signal(kind, ...)``. Returns a handle."""
    handle = (loop or asyncio.get_running_loop(), callback)
    with _LOCK:
        _LISTENERS.setdefault(kind, []).append(handle)
    return handle


def unlisten(kind: str, handle: tuple) -> None:
    with _LOCK:
        if handle in _LISTENERS.get(kind, []):
            _LISTENERS[kind].remove(handle)


def has_listeners(kind: str) -> bool:
    with _LOCK:
        return bool(_LISTENERS.get(kind))


def signal(kind: str, payload: Dict[str, Any]) -> None:
    """Hand *payload* to the listeners of *kind*, from any thread. Never raises."""
    with _LOCK:
        handles = list(_LISTENERS.get(kind, []))
    for loop, callback in handles:
        try:
            if not loop.is_closed():
                loop.call_soon_threadsafe(callback, payload)
        except RuntimeError:
            continue


def publish_done(user: Any, filename: Any, project: Any, dest_folder: Any = None, soft: Any = "") -> None:
    """A publish succeeded (features.activity.activity_writer.log_publish). Non blocking:
    switch off or no listener = nothing at all; any problem is logged, never raised."""
    try:
        if not hooks_enabled() or not has_listeners("publish_done"):
            return
        signal("publish_done", {"user": str(user or ""), "filename": str(filename or ""),
                                "project": str(project or ""),
                                "dest_folder": str(dest_folder) if dest_folder else "",
                                "soft": str(soft or "").strip().lower()})
    except Exception:  # noqa: BLE001 - a publish never fails because of a flow hook
        _log.warning("publish_done hook skipped", exc_info=True)
