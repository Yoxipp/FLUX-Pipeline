# json_manager.py — atomic JSON read/write helpers for all Flux modules.
# Use these everywhere instead of open() + json.load() directly.

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

# ── stat-based validators ───────────────────────────────────────────────────────

def stat_sig(path: Path | str) -> tuple[int, int] | None:
    """Return (mtime_ns, size) from a single ``stat()``, or None if missing."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def sig_token(sig: tuple[int, int] | None) -> str | None:
    """Compact ETag token for a stat signature (see :func:`file_validator`)."""
    if sig is None:
        return None
    return f"{sig[0]:x}-{sig[1]:x}"


def file_validator(path: Path | str) -> str | None:
    """Return a weak validator for *path* from a single ``stat()`` — no file read.

    Combines mtime (ns) and size into a compact token suitable for building an
    HTTP ETag so a poller can be answered with 304 Not Modified without reading
    or serialising the file. Returns ``None`` when the file does not exist yet,
    so callers treat that as "no validator → always fetch".

    Weak by design: on network shares with coarse mtime resolution two writes in
    the same tick *and* of the same size would share a token. Size guards the
    common append case (the file always grows), and Phase 5's append-only JSONL
    makes size strictly monotonic, so this is safe for the activity/chat feeds.
    """
    return sig_token(stat_sig(path))


# ── short-lived in-process read cache (Phase 4) ─────────────────────────────────
# Absorbs bursts — a flux:refresh fan-out, or a /production read and an /activity
# poll both touching activite.json within a second — so the shared network file
# is hit at most once per TTL window. Per-sidecar only: there is no inter-machine
# coherence to maintain; freshness across instances stays bounded by CACHE_TTL_S,
# which is fine for a polling feed.

CACHE_TTL_S: float = 3.0   # seconds an entry may be served without re-reading

# path(str) → (expires_monotonic, sig | None, parsed_data)
_cache: dict[str, tuple[float, tuple[int, int] | None, dict | list]] = {}
_cache_lock = threading.Lock()


def _shallow_copy(data: dict | list) -> dict | list:
    """Copy the top-level container so a caller's in-place ``.sort()``/append does
    not mutate the shared cached object (element dicts are read-only on the query
    paths; writers use the uncached :func:`read_json`)."""
    if isinstance(data, list):
        return list(data)
    if isinstance(data, dict):
        return dict(data)
    return data


def cached_read_json(
    path: Path | str, *, sig: tuple[int, int] | None = None, ttl: float = CACHE_TTL_S,
) -> dict | list:
    """:func:`read_json` with a short-lived per-process cache keyed by path.

    - Within *ttl* seconds a cached entry is returned WITHOUT touching disk
      (burst absorption).
    - Pass *sig* (a (mtime_ns, size) the caller already obtained — e.g. while
      building the ETag) to reuse that stat instead of doing another. A sig that
      differs from the cached one forces a fresh read even inside the TTL, so a
      file that changed since it was cached is never masked on the very request
      that noticed the change.
    - Returns a shallow copy so callers may sort/append freely.

    Writers invalidate through :func:`write_json` (drops the entry on success).
    """
    key = str(path)
    now = time.monotonic()
    with _cache_lock:
        ent = _cache.get(key)

    if sig is None:
        # Burst path: trust the TTL window without a stat.
        if ent is not None and now < ent[0]:
            return _shallow_copy(ent[2])
        sig = stat_sig(path)   # may be None (missing file)

    if ent is not None and ent[1] == sig:
        # Unchanged since cached → no read; slide the TTL window forward.
        with _cache_lock:
            _cache[key] = (now + ttl, sig, ent[2])
        return _shallow_copy(ent[2])

    data = read_json(path)
    with _cache_lock:
        _cache[key] = (now + ttl, sig, data)
    return _shallow_copy(data)


def invalidate_cache(path: Path | str | None = None) -> None:
    """Drop the cache entry for *path* (or clear everything when None)."""
    with _cache_lock:
        if path is None:
            _cache.clear()
        else:
            _cache.pop(str(path), None)


def read_json(path: Path | str) -> dict | list:
    """Read and parse a JSON file. Returns {} on missing file or parse error."""
    path = Path(path)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}
    except OSError:
        return {}


def write_json(path: Path | str, data: dict | list, indent: int = 2) -> bool:
    """Write *data* to *path* atomically (temp file → rename).

    Atomic write prevents corruption when multiple users access the same
    file over OneDrive or a network share simultaneously.
    Returns True on success, False on error.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=path.parent,
            prefix=".flux_tmp_",
            suffix=".json",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=indent)
        except Exception:
            os.unlink(tmp_path)
            return False

        # Atomic replace (works on Windows with os.replace)
        os.replace(tmp_path, path)
        # Drop any stale read-cache entry so the next cached_read_json re-reads.
        # Never let a cache hiccup turn a successful write into a reported failure.
        try:
            invalidate_cache(path)
        except Exception:  # noqa: BLE001
            pass
        return True

    except OSError:
        return False


def update_json(path: Path | str, key: str, value: Any) -> bool:
    """Read JSON dict, set *key* to *value*, write back atomically."""
    data = read_json(path)
    if not isinstance(data, dict):
        data = {}
    data[key] = value
    return write_json(path, data)


def append_to_list(path: Path | str, list_key: str, item: Any) -> bool:
    """Read JSON dict, append *item* to data[list_key], write back atomically."""
    data = read_json(path)
    if not isinstance(data, dict):
        data = {}
    lst = data.get(list_key, [])
    if not isinstance(lst, list):
        lst = []
    lst.append(item)
    data[list_key] = lst
    return write_json(path, data)
