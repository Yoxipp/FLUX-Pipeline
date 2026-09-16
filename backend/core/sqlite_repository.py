# sqlite_repository.py — MetadataRepository backed by ONE local SQLite base (V5).
#
# Same surface as JsonFileRepository, swapped in behind the factory. The whole
# point of the difference: (collection, doc_id) is a KEY in the base, not a file
# on disk, so there is no `locate` resolver here and no file-per-document sprawl.
# One base holds every document and every log as rows.
#
# Two generic tables, zero domain schema (the domain lives in the stores):
#   documents(collection, doc_id, data)  — data = the JSON value (dict or list)
#   logs(collection, doc_id, seq, entry) — one row per append-only log entry
#
# Reliability: opened WAL + busy_timeout so readers never block the writer and a
# competing writer waits instead of failing instantly. Log rotation uses a real
# SQL transaction (BEGIN IMMEDIATE) in place of the JSON backend's file lock.
#
# NAS caveat (agreed with the maintainer, restated on purpose): SQLite is one local disk,
# one writer. On a shared NAS several machines WRITING at once risk "database is
# locked" / corruption. WAL + busy_timeout soften this, they do not remove it.
# True multi-machine concurrency = the future RemoteRepository (a server), not
# this backend. One base per team/prod, bases never connected (non-negotiable).

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# How long a writer waits for a competing write lock before "database is locked".
# Generous on purpose: a NAS round-trip is slow, and a rotation holds the lock
# for a read-modify-write.
_DEFAULT_BUSY_TIMEOUT_MS = 5000


class SqliteRepository:
    """MetadataRepository over a single local SQLite base.

    Swappable with JsonFileRepository behind the exact same surface: the stores
    never know which one is active. Unlike the JSON backend it takes the path of
    THE BASE (not a per-document locator) — a document has no path here, only a
    (collection, doc_id) key.
    """

    def __init__(self, db_path: Path, *, busy_timeout_ms: int = _DEFAULT_BUSY_TIMEOUT_MS) -> None:
        self._db_path = Path(db_path)
        self._busy_timeout_ms = busy_timeout_ms
        # The connection of an in-progress log_transaction, per thread. Ops nested
        # inside the `with` block reuse it so they share the one SQL transaction;
        # a second connection would deadlock on the write lock BEGIN IMMEDIATE holds.
        self._txn = threading.local()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ── connection plumbing ────────────────────────────────────────────────────

    def _new_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self._db_path, timeout=self._busy_timeout_ms / 1000.0
        )
        # WAL: concurrent readers do not block the single writer (persisted on the
        # base once set). busy_timeout: wait, do not fail instantly, on contention.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
        return conn

    def _init_schema(self) -> None:
        conn = self._new_connection()
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS documents ("
                "collection TEXT NOT NULL, doc_id TEXT NOT NULL, data TEXT NOT NULL, "
                "PRIMARY KEY (collection, doc_id))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS logs ("
                "collection TEXT NOT NULL, doc_id TEXT NOT NULL, "
                "seq INTEGER NOT NULL, entry TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS logs_by_doc "
                "ON logs (collection, doc_id, seq)"
            )
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        """Connection for one write op. Reuse the active log_transaction's
        connection when inside one (its COMMIT ends the scope); else open a
        short-lived connection and commit it here."""
        txn = getattr(self._txn, "conn", None)
        if txn is not None:
            yield txn
            return
        conn = self._new_connection()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        """Connection for one read op. Reuse the transaction's connection when
        inside one (so a read sees the uncommitted writes of its own scope)."""
        txn = getattr(self._txn, "conn", None)
        if txn is not None:
            yield txn
            return
        conn = self._new_connection()
        try:
            yield conn
        finally:
            conn.close()

    # ── document ops (one JSON value per doc_id: a dict or a list) ──────────────

    def get(self, collection: str, doc_id: str) -> dict | list | None:
        with self._read() as conn:
            row = conn.execute(
                "SELECT data FROM documents WHERE collection=? AND doc_id=?",
                (collection, str(doc_id)),
            ).fetchone()
        if row is None:
            return None
        try:
            data = json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return None
        return data if isinstance(data, (dict, list)) else None

    def set(self, collection: str, doc_id: str, data: dict | list) -> bool:
        try:
            payload = json.dumps(data, ensure_ascii=False)
        except (TypeError, ValueError):
            return False
        try:
            with self._write() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO documents (collection, doc_id, data) "
                    "VALUES (?, ?, ?)",
                    (collection, str(doc_id), payload),
                )
            return True
        except sqlite3.Error:
            return False

    def update(self, collection: str, doc_id: str, patch: dict) -> bool:
        # Shallow merge, identical to the JSON backend (create when absent).
        current = self.get(collection, doc_id) or {}
        current.update(patch)
        return self.set(collection, doc_id, current)

    def delete(self, collection: str, doc_id: str) -> None:
        try:
            with self._write() as conn:
                conn.execute(
                    "DELETE FROM documents WHERE collection=? AND doc_id=?",
                    (collection, str(doc_id)),
                )
        except sqlite3.Error:
            pass  # a no-op when it does not exist, and never crash a delete

    # ── log ops (append-only feeds: chat, mentions, activity, archives) ─────────
    # No file cache and no stat here, so `fresh` has no effect (a SELECT is always
    # live) and `sig` (an ETag stat hint for the file backend) is ignored — the
    # contract explicitly lets a cache-less backend ignore it.

    def read_log(
        self,
        collection: str,
        doc_id: str,
        *,
        fresh: bool = False,
        sig: tuple[int, int] | None = None,
    ) -> list[dict]:
        with self._read() as conn:
            rows = conn.execute(
                "SELECT entry FROM logs WHERE collection=? AND doc_id=? ORDER BY seq",
                (collection, str(doc_id)),
            ).fetchall()
        out: list[dict] = []
        for (raw,) in rows:
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue  # tolerate a malformed row like the JSONL reader does
            if isinstance(obj, dict):
                out.append(obj)
        return out

    def append_log(self, collection: str, doc_id: str, entries: list[dict]) -> bool:
        rows = list(entries)
        if not rows:
            return True  # empty append is a success, like the JSONL backend
        try:
            with self._write() as conn:
                start = self._next_seq(conn, collection, str(doc_id))
                conn.executemany(
                    "INSERT INTO logs (collection, doc_id, seq, entry) "
                    "VALUES (?, ?, ?, ?)",
                    [
                        (collection, str(doc_id), start + i,
                         json.dumps(e, ensure_ascii=False))
                        for i, e in enumerate(rows)
                    ],
                )
            return True
        except (sqlite3.Error, TypeError, ValueError):
            return False

    def replace_log(self, collection: str, doc_id: str, entries: list[dict]) -> bool:
        rows = list(entries)
        try:
            with self._write() as conn:
                # DELETE + re-INSERT in one transaction (the surrounding _write /
                # log_transaction commit scope), so the log is never seen empty.
                conn.execute(
                    "DELETE FROM logs WHERE collection=? AND doc_id=?",
                    (collection, str(doc_id)),
                )
                if rows:
                    conn.executemany(
                        "INSERT INTO logs (collection, doc_id, seq, entry) "
                        "VALUES (?, ?, ?, ?)",
                        [
                            (collection, str(doc_id), i,
                             json.dumps(e, ensure_ascii=False))
                            for i, e in enumerate(rows)
                        ],
                    )
            return True
        except (sqlite3.Error, TypeError, ValueError):
            return False

    @contextmanager
    def log_transaction(self, collection: str, doc_id: str) -> Iterator[None]:
        # A real SQL transaction replaces the JSON backend's advisory file lock.
        # BEGIN IMMEDIATE takes the write lock now, so a read_log(fresh) +
        # replace_log pair inside the block is serialised against other writers of
        # the base (rotation never loses a racing append). BEGIN IMMEDIATE is
        # base-wide, coarser than the file backend's per-file lock but correct.
        # (collection/doc_id are part of the surface; the base-wide lock ignores them.)
        if getattr(self._txn, "conn", None) is not None:
            yield  # already inside a transaction on this thread: just nest
            return
        conn = self._new_connection()
        conn.isolation_level = None  # drive BEGIN / COMMIT / ROLLBACK by hand
        self._txn.conn = conn
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield
            conn.execute("COMMIT")
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            self._txn.conn = None
            conn.close()

    # ── cache validation (HTTP ETags) ───────────────────────────────────────────

    def version_token(self, collection: str, doc_id: str) -> str:
        """Weak token that moves whenever this (collection, doc_id) changes.

        There is no file stat to lean on here — the data is a row, not a file —
        so the token is derived from the row state itself:
          • a document → a short hash of its stored JSON text (changes iff the
            value changes: a mark-read rewrites the read_state row, so the hash
            moves and the ETag invalidates);
          • a log → COUNT(*) + MAX(seq)+1 (an append raises both; a rotation
            rewrites the rows and moves the count). Weak like the JSON validator:
            a rotation that happened to keep the same count and top seq could
            repeat a token — harmless for a 30s poll, and re-marked on the next.
        A key that holds neither yet → the stable sentinel "0".
        """
        did = str(doc_id)
        with self._read() as conn:
            row = conn.execute(
                "SELECT data FROM documents WHERE collection=? AND doc_id=?",
                (collection, did),
            ).fetchone()
            if row is not None:
                digest = hashlib.sha1(str(row[0]).encode("utf-8")).hexdigest()
                return f"d{digest[:16]}"
            count, max_seq = conn.execute(
                "SELECT COUNT(*), COALESCE(MAX(seq), -1) FROM logs "
                "WHERE collection=? AND doc_id=?",
                (collection, did),
            ).fetchone()
        if count == 0:
            return "0"
        return f"l{count:x}-{(int(max_seq) + 1):x}"

    # ── key migration (ADR 0004, V8 U2) ─────────────────────────────────────────

    def rekey(self, key_fn) -> dict[str, list]:
        """Rename every (collection, doc_id) to key_fn(collection, doc_id), in place.

        One transaction. Idempotent: a key already logical maps to itself. Never
        overwrites: when the target key already holds data, the old row is left
        as is and reported in "conflicts". Returns {"moved": [...], "conflicts": [...]}.
        """
        moved: list[tuple[str, str, str]] = []
        conflicts: list[tuple[str, str, str]] = []
        with self.log_transaction("*", "*"):
            with self._write() as conn:
                doc_rows = conn.execute("SELECT collection, doc_id FROM documents").fetchall()
                for collection, old in doc_rows:
                    new = key_fn(collection, old)
                    if new == old:
                        continue
                    exists = conn.execute(
                        "SELECT 1 FROM documents WHERE collection=? AND doc_id=?",
                        (collection, new),
                    ).fetchone()
                    if exists:
                        conflicts.append((collection, old, new))
                        continue
                    conn.execute(
                        "UPDATE documents SET doc_id=? WHERE collection=? AND doc_id=?",
                        (new, collection, old),
                    )
                    moved.append((collection, old, new))
                log_rows = conn.execute("SELECT DISTINCT collection, doc_id FROM logs").fetchall()
                for collection, old in log_rows:
                    new = key_fn(collection, old)
                    if new == old:
                        continue
                    exists = conn.execute(
                        "SELECT 1 FROM logs WHERE collection=? AND doc_id=? LIMIT 1",
                        (collection, new),
                    ).fetchone()
                    if exists:
                        conflicts.append((collection, old, new))
                        continue
                    conn.execute(
                        "UPDATE logs SET doc_id=? WHERE collection=? AND doc_id=?",
                        (new, collection, old),
                    )
                    moved.append((collection, old, new))
        return {"moved": moved, "conflicts": conflicts}

    # ── internals ──────────────────────────────────────────────────────────────

    @staticmethod
    def _next_seq(conn: sqlite3.Connection, collection: str, doc_id: str) -> int:
        row = conn.execute(
            "SELECT MAX(seq) FROM logs WHERE collection=? AND doc_id=?",
            (collection, doc_id),
        ).fetchone()
        return 0 if row[0] is None else int(row[0]) + 1
