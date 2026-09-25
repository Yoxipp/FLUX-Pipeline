# _backend.py - pin the JSON metadata backend for the store round-trip suites.
#
# The "*_via_repository" suites assert the JSON store behaviour of a store routed
# through get_repository() (on-disk format, missing-file defaults, parent-dir
# creation). get_repository() picks the backend from the live config.json, which a
# dev workspace may have flipped to sqlite; that makes the on-disk-JSON assertions
# fail for a reason unrelated to the store. These module-level fixtures pin the JSON
# backend for the whole module and drop the cached singleton so the choice takes
# effect and never leaks to the next module (unittest runs modules sequentially).
#
# Usage in a suite file (no class or setUp change needed - unittest looks these
# names up on the test module):
#     from tests.repository._backend import setUpModule, tearDownModule  # noqa: F401

from __future__ import annotations

from unittest import mock

from core import repository_factory

_patcher = None


def setUpModule() -> None:
    global _patcher
    _patcher = mock.patch("core.paths.get_metadata_backend", return_value="json")
    _patcher.start()
    repository_factory.reset_repository()


def tearDownModule() -> None:
    global _patcher
    if _patcher is not None:
        _patcher.stop()
        _patcher = None
    repository_factory.reset_repository()
