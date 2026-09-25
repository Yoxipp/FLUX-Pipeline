# test_build_output_path_storage.py — the publish resolve step honours the
# StorageLocator (V5 Phase 1b, Unite 4).
#
# Two guarantees:
#   default   : no storage_root -> the existing token resolution, under the
#               context's project_path, byte-for-byte unchanged.
#   redirect  : a configured storage_root sends the destination under that root
#               instead, without touching the feature code.

from __future__ import annotations

import asyncio
import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from flux_actions import PUBLISH_ACTION
from flux_actions.commands.build_output_path import BuildOutputPath
from flux_core import ActionQuery
from features.folder_manager.tokens import build_default_tokens, save_tokens
from core import repository_factory

_FILE = "CHAR_RIG_HERO_ALL_LAST.ma"
_REL = ("assets", "chara", "HERO", "rig", "all")
_LOG = logging.getLogger("test")


def _resolve(context: dict) -> Path:
    query = ActionQuery.from_file(PUBLISH_ACTION, context=context)
    out = asyncio.run(BuildOutputPath().run({"filename": _FILE}, query, _LOG))
    return Path(out["output_path"])


class BuildOutputPathStorageTests(unittest.TestCase):
    def tearDown(self):
        repository_factory.reset_storage()

    def test_default_resolves_under_context_project_path(self):
        proj = Path(tempfile.mkdtemp()) / "PROD"
        proj.mkdir(parents=True)
        save_tokens(proj, build_default_tokens())
        with mock.patch("core.paths.get_storage_root", return_value=None):
            repository_factory.reset_storage()
            dest = _resolve({"project_path": str(proj), "project_name": "PROD"})
        self.assertEqual(dest, proj.joinpath(*_REL))

    def test_storage_root_redirects_the_publish(self):
        # The context points at one place, but the configured storage_root sends
        # the publish somewhere else entirely.
        ctx_proj = "/somewhere/else/PROD"
        storage_root = Path(tempfile.mkdtemp())
        (storage_root / "PROD").mkdir(parents=True)
        save_tokens(storage_root / "PROD", build_default_tokens())

        with mock.patch("core.paths.get_storage_root", return_value=storage_root):
            repository_factory.reset_storage()
            dest = _resolve({"project_path": ctx_proj, "project_name": "PROD"})

        # Landed under the storage_root, not under the context's project_path.
        self.assertEqual(dest, (storage_root / "PROD").joinpath(*_REL))
        self.assertFalse(str(dest).startswith(ctx_proj))


if __name__ == "__main__":
    unittest.main()
