# json_manager.py — atomic JSON read/write helpers for all Flux modules.
# Use these everywhere instead of open() + json.load() directly.

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

# ── cross-process append lock ────────────────────────────────────────────────
# The JSONL append path must be atomic across INSTANCES (different machines on
# the shared drive), not just threads. Plain CRT append mode ("a") is NOT atomic
# across handles on Windows, so we serialise appends with an OS advisory lock on
# a per-file ".lock" companion (msvcrt on Windows, fcntl on POSIX), plus an
# in-process lock so threads of one sidecar never race either.

_INPROC_APPEND_LOCK = threading.Lock()

if sys.platform == "win32":
    import msvcrt

    def _os_lock(fh) -> None:
        # Lock 1 byte at offset 0 (allowed beyond EOF on Windows); retry until held.
        while True:
            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                time.sleep(0.01)

    def _os_unlock(fh) -> None:
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def _os_lock(fh) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)

    def _os_unlock(fh) -> None:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass


@contextmanager
def append_lock(path: Path | str):
    """Serialise appends/rotation for *path* across threads AND instances.

    Held around the actual write so two machines appending to the same shared
    JSONL log can never interleave a line or clobber each other's event.
    """
    lockpath = Path(str(path) + ".lock")
    try:
        lockpath.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    with _INPROC_APPEND_LOCK:
        fh = open(lockpath, "a+")
        try:
            _os_lock(fh)
            yield
        finally:
            _os_unlock(fh)
            fh.close()

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
    reader=None,
) -> dict | list:
    """Cached read with a short-lived per-process cache keyed by path.

    - *reader* is the parse function (defaults to :func:`read_json`); pass
      :func:`read_jsonl` for the append-only activity/mentions logs.
    - Within *ttl* seconds a cached entry is returned WITHOUT touching disk
      (burst absorption).
    - Pass *sig* (a (mtime_ns, size) the caller already obtained — e.g. while
      building the ETag) to reuse that stat instead of doing another. A sig that
      differs from the cached one forces a fresh read even inside the TTL, so a
      file that changed since it was cached is never masked on the very request
      that noticed the change.
    - Returns a shallow copy so callers may sort/append freely.

    Writers invalidate through :func:`write_json` / :func:`append_jsonl` (both
    drop the entry on success).
    """
    read = reader or read_json
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

    data = read(path)
    with _cache_lock:
        _cache[key] = (now + ttl, sig, data)
    return _shallow_copy(data)


def cached_read_jsonl(path: Path | str, *, sig: tuple[int, int] | None = None,
                      ttl: float = CACHE_TTL_S) -> list[dict]:
    """Cached :func:`read_jsonl` — the JSONL counterpart of cached_read_json."""
    data = cached_read_json(path, sig=sig, ttl=ttl, reader=read_jsonl)
    return data if isinstance(data, list) else []


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


# ── JSONL append-only logs (Phase 5) ────────────────────────────────────────────
# The hot activity/mentions feeds are written as JSON Lines: one event per line,
# appended with O_APPEND. A single-line append is atomic at the OS level, so two
# instances logging at the same instant no longer clobber each other's event the
# way the previous read-modify-write of a JSON array did. Reads stay
# back-compatible: a legacy JSON *array* file is detected and parsed whole, and
# the first append converts it to JSONL in place.

def _looks_like_legacy_array(path: Path) -> bool:
    """True if *path* exists and its first non-whitespace byte is '[' (old array)."""
    try:
        with open(path, "rb") as f:
            head = f.read(64)
    except OSError:
        return False
    stripped = head.lstrip()
    return bool(stripped) and stripped[:1] == b"["


def read_jsonl(path: Path | str) -> list[dict]:
    """Read an append-only JSONL log into a list of dicts (file order = oldest→newest).

    Back-compatible: a legacy JSON array is parsed as a whole. Malformed or
    partial lines (e.g. a torn final line from a crash mid-append) are skipped
    rather than crashing the feed. Missing file → [].
    """
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return []
    stripped = raw.lstrip()
    if not stripped:
        return []
    if stripped[0] == "[":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []

    out: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue   # tolerate a torn/partial line
        if isinstance(obj, dict):
            out.append(obj)
    return out


def write_jsonl(path: Path | str, entries: list[dict]) -> bool:
    """Rewrite *path* as JSONL atomically (temp file → rename). Used by rotation
    and by the one-time legacy-array migration, NOT by the per-event hot path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".flux_tmp_", suffix=".jsonl")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries))
        except Exception:
            os.unlink(tmp_path)
            return False
        os.replace(tmp_path, path)
        try:
            invalidate_cache(path)
        except Exception:  # noqa: BLE001
            pass
        return True
    except OSError:
        return False


def append_jsonl(path: Path | str, entries: list[dict]) -> bool:
    """Append *entries* to the JSONL log at *path* as one atomic write.

    The whole batch is serialised and written in a single ``write`` call under
    O_APPEND so concurrent writers never interleave within a line and never
    overwrite each other. If the file is still a legacy JSON array, it is
    converted to JSONL (array + entries) once, atomically, before subsequent
    appends take the pure-append fast path.
    """
    path = Path(path)
    if not entries:
        return True
    path.parent.mkdir(parents=True, exist_ok=True)

    with append_lock(path):
        if _looks_like_legacy_array(path):
            # One-time transparent migration under the lock: fold the existing
            # array and the new entries into a JSONL file. Concurrent instances
            # serialise here, so the migration never loses a racing append.
            legacy = read_json(path)
            merged = (legacy if isinstance(legacy, list) else []) + list(entries)
            return write_jsonl(path, merged)

        try:
            payload = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries)
            with open(path, "a", encoding="utf-8") as f:
                f.write(payload)   # single write under the lock → no interleave/clobber
            try:
                invalidate_cache(path)
            except Exception:  # noqa: BLE001
                pass
            return True
        except OSError:
            return False


