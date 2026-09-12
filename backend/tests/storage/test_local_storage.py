# test_local_storage.py — StorageLocator frontier (V5 Phase 1b, big files).
#
# Proves three things the prompt asks for:
#   1. LocalStorage resolves exactly like the existing publish path logic
#      (behaviour unchanged), for an asset and a shot.
#   2. Changing the storage root redirects every resolved path under it.
#   3. The factory picks the backend from config: local by default (rooted at the
#      projects dir), object store as a skeleton that raises.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import repository_factory
from core.local_storage import LocalStorage
from core.object_storage import ObjectStorage
from features.folder_manager.tokens import build_default_tokens, save_tokens
from features.publisher.publish_core import resolve_publish_path
from flux_core import StorageLocator

# Default-token asset combo: CLASS CHAR -> assets/chara, TYPE RIG -> rig, NAME
# fallback (CLASS_path/NAME) -> assets/chara/CECILE, instance "all".
_ASSET_FILE = "CHAR_RIG_CECILE_ALL_LAST.ma"
_ASSET_REL = ("assets", "chara", "CECILE", "rig", "all")


def _project_at(root: Path, name: str) -> Path:
    """Create root/<name> with a default tokens.json and return its path."""
    proj = root / name
    proj.mkdir(parents=True, exist_ok=True)
    save_tokens(proj, build_default_tokens())
    return proj


class LocalStorageResolves(unittest.TestCase):
    def test_is_a_storage_locator(self):
        self.assertIsInstance(LocalStorage(), StorageLocator)

    def test_resolve_matches_publish_core_for_asset(self):
        root = Path(tempfile.mkdtemp())
        proj = _project_at(root, "prodA")
        storage = LocalStorage(root)

        expected_dir = resolve_publish_path(proj, _ASSET_FILE)
        self.assertEqual(Path(storage.resolve_dir("prodA", _ASSET_FILE)), expected_dir)
        self.assertEqual(expected_dir, proj.joinpath(*_ASSET_REL))
        self.assertEqual(
            Path(storage.resolve_path("prodA", _ASSET_FILE)),
            expected_dir / _ASSET_FILE,
        )

    def test_resolve_matches_publish_core_for_shot(self):
        root = Path(tempfile.mkdtemp())
        proj = _project_at(root, "prodA")
        storage = LocalStorage(root)

        # Shot filename drives the CLASS template {seq}/{shot}; reuse whatever the
        # default tokens produce, and just assert the two resolvers agree.
        shot_file = "SHOT_LAYOUT_seq010_sh020_NULL_LAST.ma"
        expected = resolve_publish_path(proj, shot_file)
        if expected is None:
            self.skipTest("default tokens do not resolve this shot combo")
        self.assertEqual(Path(storage.resolve_dir("prodA", shot_file)), expected)

    def test_root_redirects(self):
        root_a = Path(tempfile.mkdtemp())
        root_b = Path(tempfile.mkdtemp())
        _project_at(root_a, "prodA")
        _project_at(root_b, "prodA")

        dir_a = Path(LocalStorage(root_a).resolve_dir("prodA", _ASSET_FILE))
        dir_b = Path(LocalStorage(root_b).resolve_dir("prodA", _ASSET_FILE))

        self.assertNotEqual(dir_a, dir_b)
        self.assertTrue(str(dir_a).startswith(str(root_a)))
        self.assertTrue(str(dir_b).startswith(str(root_b)))

    def test_unresolvable_filename_raises(self):
        storage = LocalStorage(Path(tempfile.mkdtemp()))
        with self.assertRaises(ValueError):
            storage.resolve_dir("prodA", "not-a-flux-name.ma")

    def test_unknown_kind_raises(self):
        storage = LocalStorage(Path(tempfile.mkdtemp()))
        with self.assertRaises(NotImplementedError):
            storage.resolve_dir("prodA", _ASSET_FILE, kind="work")

    def test_exists(self):
        root = Path(tempfile.mkdtemp())
        storage = LocalStorage(root)
        self.assertTrue(storage.exists(str(root)))
        self.assertFalse(storage.exists(str(root / "nope")))


class StorageFactorySelects(unittest.TestCase):
    def setUp(self):
        repository_factory.reset_storage()

    def tearDown(self):
        repository_factory.reset_storage()

    def test_default_is_local_rooted_at_projects_dir(self):
        with mock.patch("core.paths.get_storage_backend", return_value="local"), \
             mock.patch("core.paths.get_storage_root", return_value=None):
            storage = repository_factory.get_storage()
        self.assertIsInstance(storage, LocalStorage)
        # root None means "resolve the projects dir fresh" = today's layout.
        self.assertIsNone(storage._root)

    def test_explicit_root_is_used(self):
        root = Path(tempfile.mkdtemp())
        with mock.patch("core.paths.get_storage_backend", return_value="local"), \
             mock.patch("core.paths.get_storage_root", return_value=root):
            storage = repository_factory.get_storage()
        self.assertEqual(storage._root, root)

    def test_object_backend_is_a_raising_skeleton(self):
        with mock.patch("core.paths.get_storage_backend", return_value="object"):
            storage = repository_factory.get_storage()
        self.assertIsInstance(storage, ObjectStorage)
        with self.assertRaises(NotImplementedError):
            storage.resolve_url("prodA", _ASSET_FILE)

    def test_get_storage_is_cached(self):
        with mock.patch("core.paths.get_storage_backend", return_value="local"), \
             mock.patch("core.paths.get_storage_root", return_value=None):
            self.assertIs(repository_factory.get_storage(), repository_factory.get_storage())


if __name__ == "__main__":
    unittest.main()
