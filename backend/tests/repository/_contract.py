# _contract.py — backend-agnostic MetadataRepository conformance suite (V5).
#
# One set of tests, run against every backend: a concrete TestCase mixes this in
# and implements make_repo() to return a fresh EMPTY backend. This is the "same
# test, N backends" guarantee — the JSON and SQLite backends must be observably
# identical through the surface, so the stores can be routed to either.

from __future__ import annotations

from flux_core import MetadataRepository


class RepositoryContractMixin:
    """Generic conformance for MetadataRepository. Mix into a unittest.TestCase
    and implement make_repo() -> a fresh, empty MetadataRepository."""

    def make_repo(self):  # pragma: no cover - overridden by concrete cases
        raise NotImplementedError

    # ── contract identity ───────────────────────────────────────────────────────

    def test_satisfies_protocol(self):
        self.assertIsInstance(self.make_repo(), MetadataRepository)

    # ── document ops ─────────────────────────────────────────────────────────────

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.make_repo().get("things", "nope"))

    def test_set_then_get_roundtrip_dict(self):
        repo = self.make_repo()
        self.assertTrue(repo.set("things", "a", {"x": 1, "y": "hi"}))
        self.assertEqual(repo.get("things", "a"), {"x": 1, "y": "hi"})

    def test_set_then_get_roundtrip_list(self):
        # A document may be a JSON array (e.g. modif_log / feed_archive), not a dict.
        repo = self.make_repo()
        self.assertTrue(repo.set("logs", "folderA", [{"v": "v001"}, {"v": "v002"}]))
        self.assertEqual(repo.get("logs", "folderA"), [{"v": "v001"}, {"v": "v002"}])

    def test_set_overwrites(self):
        repo = self.make_repo()
        repo.set("things", "a", {"x": 1})
        repo.set("things", "a", {"x": 2, "z": 3})
        self.assertEqual(repo.get("things", "a"), {"x": 2, "z": 3})

    def test_update_merges(self):
        repo = self.make_repo()
        repo.set("things", "a", {"x": 1, "y": 2})
        self.assertTrue(repo.update("things", "a", {"y": 9, "z": 3}))
        self.assertEqual(repo.get("things", "a"), {"x": 1, "y": 9, "z": 3})

    def test_update_creates_when_absent(self):
        repo = self.make_repo()
        self.assertTrue(repo.update("things", "new", {"a": 1}))
        self.assertEqual(repo.get("things", "new"), {"a": 1})

    def test_delete_removes(self):
        repo = self.make_repo()
        repo.set("things", "a", {"x": 1})
        repo.delete("things", "a")
        self.assertIsNone(repo.get("things", "a"))

    def test_delete_missing_is_noop(self):
        self.make_repo().delete("things", "ghost")  # must not raise

    def test_collections_are_isolated(self):
        repo = self.make_repo()
        repo.set("ca", "shared", {"who": "a"})
        repo.set("cb", "shared", {"who": "b"})
        self.assertEqual(repo.get("ca", "shared"), {"who": "a"})
        self.assertEqual(repo.get("cb", "shared"), {"who": "b"})

    # ── log ops ──────────────────────────────────────────────────────────────────

    def test_read_and_append_log(self):
        repo = self.make_repo()
        self.assertEqual(repo.read_log("events", "feed"), [])
        self.assertTrue(repo.append_log("events", "feed", [{"id": "e1"}]))
        self.assertTrue(repo.append_log("events", "feed", [{"id": "e2"}, {"id": "e3"}]))
        ids = [e["id"] for e in repo.read_log("events", "feed")]
        self.assertEqual(ids, ["e1", "e2", "e3"])

    def test_append_empty_is_noop_success(self):
        repo = self.make_repo()
        self.assertTrue(repo.append_log("events", "feed", []))
        self.assertEqual(repo.read_log("events", "feed"), [])

    def test_logs_are_isolated_per_doc(self):
        repo = self.make_repo()
        repo.append_log("events", "a", [{"id": "a1"}])
        repo.append_log("events", "b", [{"id": "b1"}])
        self.assertEqual([e["id"] for e in repo.read_log("events", "a")], ["a1"])
        self.assertEqual([e["id"] for e in repo.read_log("events", "b")], ["b1"])

    def test_replace_log_rewrites(self):
        repo = self.make_repo()
        repo.append_log("events", "feed", [{"id": "e1"}, {"id": "e2"}])
        self.assertTrue(repo.replace_log("events", "feed", [{"id": "e2"}]))  # trim
        self.assertEqual([e["id"] for e in repo.read_log("events", "feed")], ["e2"])

    def test_read_log_fresh_matches_cached(self):
        repo = self.make_repo()
        repo.append_log("events", "feed", [{"id": "e1"}])
        self.assertEqual(
            repo.read_log("events", "feed", fresh=True),
            repo.read_log("events", "feed"),
        )

    def test_log_transaction_read_modify_write(self):
        # The rotation shape: read fresh + replace, atomically, inside the scope.
        repo = self.make_repo()
        repo.append_log("events", "feed", [{"id": "e1"}, {"id": "e2"}, {"id": "e3"}])
        with repo.log_transaction("events", "feed"):
            entries = repo.read_log("events", "feed", fresh=True)
            repo.replace_log("events", "feed", entries[-2:])
        ids = [e["id"] for e in repo.read_log("events", "feed", fresh=True)]
        self.assertEqual(ids, ["e2", "e3"])

    # ── cache validation (version_token / ETags) ─────────────────────────────────
    # These properties must hold on every backend so the conditional-GET routers
    # (activity / chat / mentions) invalidate correctly whatever backend is active.

    def test_version_token_empty_is_stable_sentinel(self):
        repo = self.make_repo()
        self.assertEqual(repo.version_token("things", "nope"), "0")
        self.assertEqual(repo.version_token("things", "nope"), "0")  # stable

    def test_version_token_moves_when_document_written(self):
        # A read_state-shaped doc: writing it (and growing it) must move the token,
        # so a "mark read" invalidates the cached 304. (This was the SQLite bug.)
        repo = self.make_repo()
        before = repo.version_token("read_state", "companion")
        repo.set("read_state", "companion", {"read_ids": ["e1"]})
        after_one = repo.version_token("read_state", "companion")
        self.assertNotEqual(after_one, before)
        repo.set("read_state", "companion", {"read_ids": ["e1", "e2"]})
        after_two = repo.version_token("read_state", "companion")
        self.assertNotEqual(after_two, after_one)

    def test_version_token_moves_when_log_appended(self):
        # Each append grows the log; the token must move so new events surface.
        repo = self.make_repo()
        before = repo.version_token("events", "feed")
        self.assertEqual(before, "0")
        repo.append_log("events", "feed", [{"id": "e1"}])
        after_one = repo.version_token("events", "feed")
        self.assertNotEqual(after_one, before)
        repo.append_log("events", "feed", [{"id": "e2"}])
        self.assertNotEqual(repo.version_token("events", "feed"), after_one)

    def test_version_token_isolated_per_key(self):
        repo = self.make_repo()
        repo.append_log("events", "a", [{"id": "a1"}])
        self.assertNotEqual(
            repo.version_token("events", "a"), repo.version_token("events", "b"),
        )
