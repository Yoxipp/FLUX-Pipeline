# channels - outgoing push relay (Discord webhook) and the bot's REST calls. Stdlib HTTP only.
#
# Every send returns a SendResult and never raises: the dispatcher decides from it
# whether the item leaves the queue, is retried later or is dropped.

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import NamedTuple

TIMEOUT_S = 10.0


class SendResult(NamedTuple):
    ok: bool
    status: int = 0             # HTTP status, 0 = no answer (network down, timeout)
    retry_after: float = 0.0    # seconds to wait before the next send on this relay
    permanent: bool = False     # True = retrying will never work (bad webhook, bad topic)


def post_json(url: str, payload: dict, timeout: float = TIMEOUT_S) -> tuple[int, dict, bytes]:
    """POST *payload* as JSON. Returns (status, headers, body); status 0 on network error.

    The URL (it holds the secret) never appears in an exception text raised from here.
    """
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "FLUX-notify/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - relay URL set by the team
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as exc:
        headers = {k.lower(): v for k, v in (exc.headers or {}).items()}
        try:
            body = exc.read()
        except Exception:  # noqa: BLE001
            body = b""
        return exc.code, headers, body
    except Exception:  # noqa: BLE001 - URLError, timeout, ssl: all "no answer"
        return 0, {}, b""


def request_json(method: str, url: str, payload: dict | list | None = None, *,
                 headers: dict | None = None, timeout: float = TIMEOUT_S) -> tuple[int, dict, bytes]:
    """Any method, optional JSON body and extra headers (Discord bot REST, ADR 0073).
    Same contract as post_json: never raises, status 0 = no answer, no secret in errors."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    all_headers = {"User-Agent": "DiscordBot (https://flux.local, 1)", **(headers or {})}
    if data is not None:
        all_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=all_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - Discord API
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as exc:
        hdrs = {k.lower(): v for k, v in (exc.headers or {}).items()}
        try:
            body = exc.read()
        except Exception:  # noqa: BLE001
            body = b""
        return exc.code, hdrs, body
    except Exception:  # noqa: BLE001
        return 0, {}, b""


def retry_after_s(headers: dict, body: bytes) -> float:
    """Seconds from a Retry-After header or a JSON ``retry_after`` field, else 0."""
    for key in ("retry-after", "x-ratelimit-reset-after"):
        try:
            if headers.get(key):
                return max(0.0, float(headers[key]))
        except ValueError:
            pass
    try:
        return max(0.0, float(json.loads(body or b"{}").get("retry_after", 0)))
    except (ValueError, AttributeError):
        return 0.0


def classify(status: int, headers: dict, body: bytes) -> SendResult:
    """Common mapping: 2xx ok, 429 / 5xx / no answer retried, other 4xx permanent."""
    if 200 <= status < 300:
        wait = 0.0
        if headers.get("x-ratelimit-remaining") == "0":
            wait = retry_after_s(headers, b"")
        return SendResult(True, status, wait)
    if status == 0 or status == 429 or status >= 500:
        return SendResult(False, status, retry_after_s(headers, body))
    return SendResult(False, status, 0.0, permanent=True)


def truncate_utf8(text: str, max_bytes: int) -> str:
    """*text* cut so its UTF-8 form fits *max_bytes*, ending with an ellipsis when cut."""
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    cut = raw[: max(0, max_bytes - 3)].decode("utf-8", errors="ignore")
    return cut + "..."
