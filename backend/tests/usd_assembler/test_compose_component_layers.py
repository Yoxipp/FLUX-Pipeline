# Compose a component from explicit layer slots (v2 "USD Layers"): the root's
# subLayerPaths stack the resolved layer files strong->weak, relative to the
# output dir, with a component defaultPrim on the shared base. Fake resolver, so
# no on-disk publish is needed.
#
# Note: USD prints "Could not load sublayer" warnings during these tests. That is
# expected — the root is composed in memory (an anonymous layer), so its relative
# subLayerPaths have no on-disk directory to resolve against until the façade
# writes the root to output_dir. We assert the authored subLayerPath strings, not
# loaded sublayer content, so the warnings are cosmetic.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from features.usd_assembler.build.layerfile_builder import LayerFileBuilder
from features.usd_assembler.compose.composer import StageComposer
from features.usd_assembler.context import build_context
from features.usd_assembler.recipe import loader
from features.usd_assembler.registry import Registry
from features.usd_assembler.resolve.base import ResolveError, ResolvedAsset

_BASE = "CHAR_mod_UTAH_null"
_LATEST = "v009"


class _FakeResolver:
    """Freeze each slot to a stable path under *publish_root* (no disk access).

    ``follow last`` arrives as version ``latest``/``LAST`` and maps to _LATEST; a
    locked slot keeps its concrete label. *missing* names slots that raise, to
    exercise permissive skipping.
    """

    def __init__(self, publish_root: Path, missing: set[str] | None = None) -> None:
        self._root = publish_root
        self._missing = missing or set()

    def resolve_layer(self, asset, task, layer, version="latest", instance="", variante="") -> ResolvedAsset:
        if layer in self._missing:
            raise ResolveError(f"layer '{layer}' missing (fake)")
        ver = _LATEST if version in ("latest", "LAST") else version
        path = self._root / f"{_BASE}_{ver}" / f"{_BASE}_{layer}.usd"
        return ResolvedAsset(path=path, default_prim=_BASE, version=ver)


def _recipe() -> dict:
    return {
        "target": {
            "kind": "component",
            "name": "UTAH_layers",
            "slots": [
                # follow-last (default): model, the weakest/base slot.
                {"slot": "model", "asset": "UTAH", "task": "mod"},
                # locked to v003, strongest slot (anim, order 0).
                {"slot": "anim", "asset": "UTAH", "task": "mod",
                 "follow_last": False, "version": "v003"},
            ],
        },
        "options": {"format": "usda"},
    }


def _compose(out_dir: Path, publish_root: Path, *, strict=True, missing=None):
    ctx = build_context(strict=strict, config={})
    ctx.resolver = _FakeResolver(publish_root, missing)
    ctx.output_dir = out_dir
    registry = Registry()
    registry.register_builder(LayerFileBuilder())
    return StageComposer(ctx, registry).compose(loader.load(_recipe()))


class ComposeComponentLayers(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.out_dir = root / "assembly" / "out"
        self.publish_root = root / "assets" / "UTAH" / "mod" / "null"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _sublayers(self):
        stage = _compose(self.out_dir, self.publish_root)
        return list(stage.GetRootLayer().subLayerPaths), stage

    def test_stack_order_strong_to_weak(self) -> None:
        subs, _ = self._sublayers()
        self.assertEqual(len(subs), 2)
        # anim (order 0) is strongest -> first; model (order 5) weakest -> last.
        self.assertTrue(subs[0].endswith(f"{_BASE}_anim.usd"), subs[0])
        self.assertTrue(subs[-1].endswith(f"{_BASE}_model.usd"), subs[-1])

    def test_paths_relative_and_posix(self) -> None:
        subs, _ = self._sublayers()
        for ref in subs:
            self.assertNotIn("\\", ref)
            self.assertFalse(Path(ref).is_absolute(), ref)
            self.assertTrue(ref.startswith(".."), ref)

    def test_follow_last_vs_locked(self) -> None:
        subs, _ = self._sublayers()
        anim = next(s for s in subs if s.endswith("_anim.usd"))
        model = next(s for s in subs if s.endswith("_model.usd"))
        self.assertIn("v003", anim)        # locked slot
        self.assertIn(_LATEST, model)      # follow-last slot

    def test_component_default_prim(self) -> None:
        _, stage = self._sublayers()
        default = stage.GetDefaultPrim()
        self.assertTrue(default and default.IsValid())
        self.assertEqual(default.GetName(), _BASE)
        from pxr import Usd

        self.assertEqual(Usd.ModelAPI(default).GetKind(), "component")

    def test_permissive_skips_missing_layer(self) -> None:
        stage = _compose(
            self.out_dir, self.publish_root, strict=False, missing={"anim"}
        )
        subs = list(stage.GetRootLayer().subLayerPaths)
        self.assertEqual(len(subs), 1)
        self.assertTrue(subs[0].endswith("_model.usd"))

    def test_strict_propagates_missing_layer(self) -> None:
        with self.assertRaises(ResolveError):
            _compose(self.out_dir, self.publish_root, strict=True, missing={"anim"})

    def test_determinism(self) -> None:
        a = _compose(self.out_dir, self.publish_root).GetRootLayer().ExportToString()
        b = _compose(self.out_dir, self.publish_root).GetRootLayer().ExportToString()
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
