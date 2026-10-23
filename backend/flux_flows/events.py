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

from __future__ import annotations

import asyncio
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
