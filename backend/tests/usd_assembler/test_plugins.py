# Unit tests for plugin auto-discovery (pure python, no pxr, no filesystem).

from __future__ import annotations

import types
import unittest

from features.usd_assembler import plugins
from features.usd_assembler.registry import Registry, default_registry


def _fake_plugin(kind: str):
    """Build a fake plugin module exposing register() + a builder of *kind*."""
    class _Builder:
        pass

    builder = _Builder()
    builder.kind = kind

    mod = types.ModuleType(f"fake_plugin_{kind}")
    mod.register = lambda registry: registry.register_builder(builder)  # type: ignore[attr-defined]
    return mod


class PluginDiscovery(unittest.TestCase):
    def test_injected_plugin_registers_its_builder(self) -> None:
        registry = Registry()
        registered = plugins.discover(registry, modules=[_fake_plugin("crowd")])
        self.assertEqual(len(registered), 1)
        self.assertTrue(registry.has_builder("crowd"))

    def test_module_without_register_is_ignored(self) -> None:
        registry = Registry()
        bare = types.ModuleType("no_hook")
        registered = plugins.discover(registry, modules=[bare])
        self.assertEqual(registered, [])

    def test_plugin_can_override_core_builder(self) -> None:
        # last registration wins — a plugin may replace a core builder by kind.
        registry = Registry()
        marker = object()

        class _Override:
            kind = "reference"
            token = marker

        registry.register_builder(_Override())
        plugins.discover(registry, modules=[_fake_plugin("reference")])
        # the fake plugin's 'reference' builder replaced the override
        self.assertNotEqual(getattr(registry.get_builder("reference"), "token", None), marker)

    def test_default_registry_has_core_builders(self) -> None:
        registry = default_registry()
        for kind in ("payload", "variantset", "prim", "reference", "sublayer"):
            self.assertTrue(registry.has_builder(kind), f"missing core builder: {kind}")


if __name__ == "__main__":
    unittest.main()
