# host_lock.py — one holder among the workstations, through a JSON file on the share.
# Used by the shared active flows (flux_flows/hosts.py: CONFIG/extensions/runs/host.lock)
# and by the Discord bot of a project (ADR 0082: _flux_setup/discord_bot_host.lock).
#
# One JSON file (a JSON file, never SQLite on the
# share, ADR 0003): {host, user, pid, nonce, expires, beat}. nonce = uuid of this
# backend process, beat = counter bumped at each renewal.
#
# Election (one call of HostLock.tick every BEAT_S = 20 s):
#   * my nonce in the file: renew {expires: now + TTL_S, beat + 1}, read back;
#     another nonce read back = lost;
#   * free (absent, empty, unreadable, released with expires 0) or stale (expires < now
#     AND beat unchanged for TTL_S of MY monotonic clock: two clocks never have to
#     agree): write my record, wait 1 to 3 s at random, read back, confirm 2 s later;
#   * a valid lock of another backend: follower.
# Two failed reads in a row while holder (FLUX_ROOT unreachable) = lost. A clean stop
# writes expires 0; Electron may kill the sidecar without it: the TTL is the real net.
# Residual double hold window: one beat (schedule slots are noted before the run).

from __future__ import annotations

import asyncio
import json
import os
import random
import socket
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

BEAT_S = 20.0
TTL_S = 60.0
SETTLE_S = (1.0, 3.0)
CONFIRM_S = 2.0
MAX_READ_FAILURES = 2


class HostLock:
    """The lock as seen by one backend. Clocks and sleep are injectable (tests)."""

    def __init__(self, path: Path, *, user: Optional[str] = None, host: Optional[str] = None,
                 nonce: Optional[str] = None, clock: Callable[[], float] = time.time,
                 mono: Callable[[], float] = time.monotonic,
                 sleep: Optional[Callable[[float], Awaitable[None]]] = None,
                 settle: tuple = SETTLE_S, confirm_s: float = CONFIRM_S) -> None:
        self.path = Path(path)
        self.host = host or socket.gethostname()
        self.user = user
        self.pid = os.getpid()
        self.nonce = nonce or uuid.uuid4().hex
        self.clock, self.mono = clock, mono
        self.sleep = sleep or asyncio.sleep
        self.settle, self.confirm_s = settle, confirm_s
        self.holder = False
        self.last: Optional[Dict[str, Any]] = None   # last record read
        self.since: Optional[float] = None           # clock() when this backend became holder
        self._beat: Optional[tuple] = None            # (nonce, beat) last seen of another backend
        self._beat_at = 0.0                           # mono() when it changed
        self._failures = 0

    # -- file -------------------------------------------------------------------
    def read(self) -> Optional[Dict[str, Any]]:
        """The record, or None when free (absent, empty, unreadable). OSError when the
        folder itself cannot be reached."""
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            if not self.path.parent.exists():
                self.path.parent.mkdir(parents=True, exist_ok=True)   # raises when FLUX_ROOT is gone
            return None
        try:
            data = json.loads(text)
        except ValueError:
            return None
        return data if isinstance(data, dict) and data.get("nonce") else None

    def _write(self, record: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        last: Optional[OSError] = None
        for _ in range(3):   # Windows may refuse os.replace while another host reads the file
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".host_", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(record, fh)
                os.replace(tmp, self.path)
                return
            except OSError as exc:
                last = exc
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                time.sleep(0.05)
        raise last  # type: ignore[misc]

    def _mine(self, beat: int) -> Dict[str, Any]:
        return {"host": self.host, "user": self.user, "pid": self.pid, "nonce": self.nonce,
                "expires": self.clock() + TTL_S, "beat": beat}

    # -- election -----------------------------------------------------------------
    def _is_stale(self, data: Dict[str, Any]) -> bool:
        if not data.get("expires"):        # released by a clean stop
            return True
        key = (data.get("nonce"), data.get("beat"))
        now_m = self.mono()
        if key != self._beat:
            self._beat, self._beat_at = key, now_m
            return False
        try:
            expired = float(data.get("expires") or 0) < self.clock()
        except (TypeError, ValueError):
            expired = True
        return expired and now_m - self._beat_at >= TTL_S

    def _lose(self) -> bool:
        changed = self.holder
        self.holder, self.since = False, None
        return changed

    async def tick(self) -> bool:
        """One election step. Returns True when the holder status changed."""
        was = self.holder
        try:
            data = await asyncio.to_thread(self.read)
        except OSError:
            self._failures += 1
            if self.holder and self._failures >= MAX_READ_FAILURES:
                self._lose()
            return was != self.holder
        self._failures = 0
        self.last = data
        if data is not None and data.get("nonce") == self.nonce:
            try:
                await asyncio.to_thread(self._write, self._mine(int(data.get("beat") or 0) + 1))
                back = await asyncio.to_thread(self.read)
            except OSError:
                return was != self.holder
            self.last = back
            if back is None or back.get("nonce") != self.nonce:
                self._lose()
            elif not self.holder:
                self.holder, self.since = True, self.clock()
            return was != self.holder
        if self.holder:     # someone else took the file
            self._lose()
            return True
        if data is not None and not self._is_stale(data):
            return False
        try:
            await asyncio.to_thread(self._write, self._mine(0))
            await self.sleep(random.uniform(*self.settle))
            back = await asyncio.to_thread(self.read)
            if back is None or back.get("nonce") != self.nonce:
                self.last = back
                return False
            await self.sleep(self.confirm_s)
            back = await asyncio.to_thread(self.read)
        except OSError:
            return False
        self.last = back
        if back is not None and back.get("nonce") == self.nonce:
            self.holder, self.since = True, self.clock()
        return was != self.holder

    def release(self) -> None:
        """Clean stop: expires 0 so another backend takes over at its next beat."""
        if not self.holder:
            return
        try:
            data = self.read()
            if data is not None and data.get("nonce") == self.nonce:
                self._write({**data, "expires": 0})
        except OSError:
            pass
        self._lose()

    def info(self) -> Dict[str, Any]:
        """Who holds the lock (GET /flows/host, bot status)."""
        data = self.last or {}
        holder = None
        if data.get("nonce") and data.get("expires"):
            holder = {k: data.get(k) for k in ("host", "user", "pid", "expires")}
        return {"holder": holder, "me": self.host, "is_holder": self.holder, "since": self.since}
