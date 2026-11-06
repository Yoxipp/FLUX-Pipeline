# outbox.py - the local send queue of this PC (%APPDATA%/FluxPipeline/notify_queue.jsonl).
#
# One file per PC, so per author (ADR 0062 R8): never in the shared folder, never
# written by two machines. An item is one event for one recipient:
#   {"id", "created", "due", "next_try", "attempts", "recipient", "project", "event"}
# The relay target (webhook, topic) is NOT stored: it is read at send time, so a
# regenerated topic or a changed channel applies to what is still queued.
# Items older than MAX_AGE_S are dropped (relay down for a day = lost, never blocking).

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)

MAX_AGE_S = 24 * 3600
BACKOFF_BASE_S = 30
BACKOFF_MAX_S = 3600

_lock = threading.RLock()
# Tests point the queue at a temp file.
QUEUE_OVERRIDE: Path | None = None


def queue_path() -> Path:
    if QUEUE_OVERRIDE is not None:
        return QUEUE_OVERRIDE
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "FluxPipeline" / "notify_queue.jsonl"


def new_item(event: dict, recipient: str, *, now: float, delay_s: float = 0.0) -> dict:
    return {"id": uuid.uuid4().hex[:12], "created": now, "due": now + max(0.0, delay_s),
            "next_try": 0.0, "attempts": 0, "recipient": recipient,
            "project": event.get("project", ""), "event": event}


def load() -> list[dict]:
    path = queue_path()
    with _lock:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        except OSError as exc:
            log.warning("notify queue unreadable: %s", exc)
            return []
    items: list[dict] = []
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue    # a torn line is skipped, the rest survives
        if isinstance(item, dict) and item.get("recipient"):
            items.append(item)
    return items


def save(items: list[dict]) -> bool:
    """Rewrite the queue atomically (temp file + replace). False on I/O error."""
    path = queue_path()
    with _lock:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".jsonl.tmp")
            tmp.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items),
                           encoding="utf-8")
            os.replace(tmp, path)
            return True
        except OSError as exc:
            log.warning("notify queue not written: %s", exc)
            return False


def add(new: list[dict]) -> bool:
    if not new:
        return True
    with _lock:
        return save(load() + new)


def expire(items: list[dict], now: float) -> tuple[list[dict], int]:
    """(kept, dropped count): items older than MAX_AGE_S are dropped."""
    kept = [i for i in items if now - float(i.get("created", 0)) < MAX_AGE_S]
    return kept, len(items) - len(kept)


def backoff(item: dict, now: float, retry_after: float = 0.0) -> None:
    """Mark a failed try: exponential wait, at least what the relay asked for."""
    item["attempts"] = int(item.get("attempts", 0)) + 1
    wait = min(BACKOFF_MAX_S, BACKOFF_BASE_S * 2 ** (item["attempts"] - 1))
    item["next_try"] = now + max(wait, retry_after)


def ready(item: dict, now: float) -> bool:
    return float(item.get("due", 0)) <= now and float(item.get("next_try", 0)) <= now


def next_wake(items: list[dict], now: float) -> float | None:
    """Seconds until the earliest item may be sent, None when the queue is empty."""
    if not items:
        return None
    return max(0.0, min(max(float(i.get("due", 0)), float(i.get("next_try", 0))) for i in items) - now)


def now() -> float:
    return time.time()
