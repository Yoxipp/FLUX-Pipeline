# Resolve layered-USD publishes off a real-shaped on-disk layout. Exercises
# FluxResolver.list_layer_versions + resolve_layer (latest vs locked, missing
# layer/version -> ResolveError). Pure python, zero pxr.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from features.folder_manager import tokens as tok
from features.usd_assembler.resolve.base import ResolveError
from features.usd_assembler.resolve.flux_resolver import FluxResolver

_ASSET = "UTAH"
_TASK = "mod"  # not a TYPE token -> type_sub falls back to "mod"
_NAME_REL = "assets/chara/UTAH"
_BASE = "CHAR_mod_UTAH_null"


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#usda 1.0\n", encoding="utf-8")


def _make_project(root: Path) -> Path:
    """Write tokens.json + a real-shaped layered publish; return the project path."""
    project = root / "PROJ"
    project.mkdir(parents=True, exist_ok=True)
    tokens = tok.build_default_tokens()
    tokens["NAME"][_ASSET] = _NAME_REL
    tok.save_tokens(project, tokens)

    inst = project / _NAME_REL / _TASK / "null"
    # LAST holds model + skel; v002 holds model only (a partial re-publish).
    for kind in ("model", "skel"):
        _touch(inst / f"{_BASE}_LAST" / f"{_BASE}_{kind}.usd")
    _touch(inst / f"{_BASE}_v002" / f"{_BASE}_model.usd")
    return project


class ResolveLayers(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = _make_project(Path(self._tmp.name))
        self.resolver = FluxResolver(self.project)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_list_layer_versions(self) -> None:
        versions = self.resolver.list_layer_versions(_ASSET, _TASK)
        self.assertEqual(set(versions), {"LAST", "v002"})
        self.assertEqual(versions["LAST"]["base"], _BASE)
        self.assertEqual(versions["LAST"]["layers"], ["model", "skel"])
        self.assertEqual(versions["v002"]["layers"], ["model"])

    def test_list_empty_when_nothing_published(self) -> None:
        # A valid NAME token but no publish on disk -> empty map, not an error.
        tokens = tok.load_tokens(self.project)
        tokens["NAME"]["GHOST"] = "assets/chara/GHOST"
        tok.save_tokens(self.project, tokens)
        self.assertEqual(FluxResolver(self.project).list_layer_versions("GHOST", _TASK), {})

    def test_resolve_layer_latest(self) -> None:
        resolved = self.resolver.resolve_layer(_ASSET, _TASK, "model", "latest")
        self.assertEqual(resolved.path.name, f"{_BASE}_model.usd")
        self.assertIn(f"{_BASE}_LAST", resolved.path.parts)
        self.assertEqual(resolved.default_prim, _BASE)
        # LAST freezes to a concrete version label for determinism.
        self.assertRegex(resolved.version, r"^v\d+$")

    def test_resolve_layer_locked_version(self) -> None:
        resolved = self.resolver.resolve_layer(_ASSET, _TASK, "model", "v002")
        self.assertIn(f"{_BASE}_v002", resolved.path.parts)
        self.assertEqual(resolved.version, "v002")

    def test_missing_layer_raises(self) -> None:
        # v002 published no skel layer.
        with self.assertRaises(ResolveError):
            self.resolver.resolve_layer(_ASSET, _TASK, "skel", "v002")

    def test_missing_version_raises(self) -> None:
        with self.assertRaises(ResolveError):
            self.resolver.resolve_layer(_ASSET, _TASK, "model", "v099")

    def test_unknown_asset_raises(self) -> None:
        with self.assertRaises(ResolveError):
            self.resolver.resolve_layer("NOPE", _TASK, "model", "latest")


if __name__ == "__main__":
    unittest.main()
