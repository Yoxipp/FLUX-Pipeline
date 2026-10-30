# dispatch.py - queue events for their recipients, then group and send them.
#
# enqueue(event): one queue item per recipient (aliases resolved, author dropped).
# mention / task / retake are due now, publish / calendar after the project's digest delay.
# flush(): every ready item of one person goes out as ONE message on that person's
# channel. A worker thread (started on demand, ends when the queue is empty) calls it.
# Nothing here ever raises into the action of the artist (ADR 0062).
#
# ntfy.sh quota (250 / day per IP, shared by the school): a local daily counter. From
# WARN_AT the person's messages wait the digest delay even when immediate; at the limit
# they wait for the next day (and expire after 24 h like any item).

from __future__ import annotations

import json
import os
import threading
import time
from datetime import date

from core.logger import get_logger
from features.accounts.aliases import load_aliases, resolve_user, same_user
from features.notify import outbox, store
from features.notify.channels import discord, ntfy
from features.notify.events import IMMEDIATE, format_digest

log = get_logger(__name__)

ENV = "FLUX_NOTIFY"
_FALSE = {"0", "false", "no", "off"}
WARN_AT = 200
IDLE_POLL_S = 60.0

_worker: threading.Thread | None = None
_worker_lock = threading.Lock()
_discord_cooldown: dict[str, float] = {}     # webhook -> time before which nothing is sent


def enabled() -> bool:
    """False when FLUX_NOTIFY is falsey (rollback switch, read at each call)."""
    return os.environ.get(ENV, "1").strip().lower() not in _FALSE


# ── enqueue ───────────────────────────────────────────────────────────────────

def recipients_of(event: dict, aliases: dict[str, str] | None = None) -> list[str]:
    table = load_aliases() if aliases is None else aliases
    out: list[str] = []
    for name in event.get("recipients") or []:
        who = str(resolve_user(str(name).strip(), table) or "").upper()
        if who and not same_user(who, event.get("author", ""), table) and who not in out:
            out.append(who)
    return out


def enqueue(event: dict, *, now: float | None = None, start_worker: bool = True) -> int:
    """Queue *event* for each recipient. Returns the number of items queued; 0 on any error."""
    if not enabled():
        return 0
    try:
        t = outbox.now() if now is None else now
        delay = 0.0
        if event.get("type") not in IMMEDIATE:
            delay = store.read_project(event.get("project", "")).get("digest_minutes", 5) * 60.0
        items = [outbox.new_item(event, who, now=t, delay_s=delay) for who in recipients_of(event)]
        if items and outbox.add(items):
            if start_worker:
                kick()
            return len(items)
    except Exception as exc:  # noqa: BLE001 - never fails the action that emitted the event
        log.warning("notify %s not queued: %s", event.get("type"), exc)
    return 0


# ── ntfy daily counter (local, per PC) ────────────────────────────────────────

def _counter_path():
    return outbox.queue_path().with_name("notify_counter.json")


def ntfy_count(today: str | None = None) -> int:
    today = today or date.today().isoformat()
    try:
        data = json.loads(_counter_path().read_text(encoding="utf-8"))
        return int(data.get("count", 0)) if data.get("date") == today else 0
    except (OSError, ValueError, AttributeError):
        return 0


def _ntfy_bump(today: str | None = None) -> None:
    today = today or date.today().isoformat()
    try:
        path = _counter_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"date": today, "count": ntfy_count(today) + 1}), encoding="utf-8")
    except OSError:
        pass


def quota_status() -> dict:
    count = ntfy_count()
    return {"ntfy_sent_today": count, "ntfy_limit": ntfy.DAILY_LIMIT, "warn": count >= WARN_AT}


def _seconds_to_midnight(now: float) -> float:
    lt = time.localtime(now)
    return 86400 - (lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec) + 1


# ── flush ─────────────────────────────────────────────────────────────────────

def _send_group(project: str, who: str, items: list[dict], now: float) -> str:
    """Send one person's ready items. Returns sent | held | retry | dropped | no_channel."""
    cfg = store.read_project(project)
    prefs = store.read_user(who)
    if not store.has_channel(prefs, cfg):
        return "no_channel"
    events = sorted((i["event"] for i in items), key=lambda e: e.get("at", 0))
    text = format_digest(events, cfg.get("include_project", False))
    channel = prefs["channel"]
    if channel == "ntfy":
        count = ntfy_count()
        if count >= ntfy.DAILY_LIMIT:
            wait = _seconds_to_midnight(now)
            for i in items:
                i["next_try"] = now + wait
            return "held"
        if count >= WARN_AT:
            oldest = min(float(i.get("created", now)) for i in items)
            if oldest + cfg.get("digest_minutes", 5) * 60.0 > now:
                for i in items:
                    i["due"] = oldest + cfg.get("digest_minutes", 5) * 60.0
                return "held"
        result = ntfy.send(cfg["ntfy_server"], prefs["ntfy_topic"], text)
        if result.ok:
            _ntfy_bump()
    else:
        hook = cfg["discord_webhook"]
        if _discord_cooldown.get(hook, 0.0) > now:
            for i in items:
                i["next_try"] = _discord_cooldown[hook]
            return "held"
        result = discord.send(hook, text, [prefs["discord_id"]])
        if result.retry_after:
            _discord_cooldown[hook] = now + result.retry_after
    types = ",".join(sorted({e.get("type", "?") for e in events}))
    if result.ok:
        log.info("notify %s via %s: sent (%d)", types, channel, len(items))
        return "sent"
    if result.permanent:
        log.warning("notify %s via %s: dropped, HTTP %s", types, channel, result.status)
        return "dropped"
    for i in items:
        outbox.backoff(i, now, result.retry_after)
    log.info("notify %s via %s: retry later, HTTP %s", types, channel, result.status)
    return "retry"


def flush(now: float | None = None) -> dict:
    """Send what is ready. Returns counts per outcome (for tests and the status route)."""
    t = outbox.now() if now is None else now
    stats = {"sent": 0, "held": 0, "retry": 0, "dropped": 0, "no_channel": 0, "expired": 0, "waiting": 0}
    with outbox._lock:
        items, stats["expired"] = outbox.expire(outbox.load(), t)
        groups: dict[tuple[str, str], list[dict]] = {}
        for item in items:
            if outbox.ready(item, t):
                groups.setdefault((item.get("project", ""), item["recipient"]), []).append(item)
            else:
                stats["waiting"] += 1
        done: set[str] = set()
        for (project, who), group in groups.items():
            try:
                outcome = _send_group(project, who, group, t)
            except Exception as exc:  # noqa: BLE001
                log.warning("notify flush error: %s", exc)
                for i in group:
                    outbox.backoff(i, t)
                outcome = "retry"
            stats[outcome] += len(group)
            if outcome in ("sent", "dropped", "no_channel"):
                done.update(i["id"] for i in group)
        outbox.save([i for i in items if i["id"] not in done])
    return stats


def send_test(project: str, who: str) -> dict:
    """Send a test message to *who* now (Parametres > User). Bypasses the queue."""
    cfg = store.read_project(project) if project else dict(store.PROJECT_DEFAULTS)
    prefs = store.read_user(who)
    if not store.has_channel(prefs, cfg):
        return {"ok": False, "reason": "no_channel"}
    text = "Test FLUX : les notifications arrivent sur ce telephone."
    if prefs["channel"] == "ntfy":
        result = ntfy.send(cfg["ntfy_server"], prefs["ntfy_topic"], text)
        if result.ok:
            _ntfy_bump()
    else:
        result = discord.send(cfg["discord_webhook"], text, [prefs["discord_id"]])
    log.info("notify test via %s: %s", prefs["channel"], "sent" if result.ok else f"HTTP {result.status}")
    return {"ok": result.ok, "status": result.status, "channel": prefs["channel"]}


# ── worker ────────────────────────────────────────────────────────────────────

def _run() -> None:
    global _worker
    while True:
        try:
            flush()
            wake = outbox.next_wake(outbox.load(), outbox.now())
        except Exception as exc:  # noqa: BLE001
            log.warning("notify worker: %s", exc)
            wake = IDLE_POLL_S
        if wake is None:
            with _worker_lock:
                if not outbox.load():
                    _worker = None
                    return
            continue
        time.sleep(min(max(wake, 1.0), IDLE_POLL_S))


def kick() -> None:
    """Start the worker if it is not running (no-op when FLUX_NOTIFY=0)."""
    global _worker
    if not enabled():
        return
    with _worker_lock:
        if _worker is not None and _worker.is_alive():
            return
        _worker = threading.Thread(target=_run, name="flux-notify", daemon=True)
        _worker.start()
