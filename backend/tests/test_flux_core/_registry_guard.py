# _registry_guard.py — keep the global command registry intact across test modules.
#
# Some flux_core tests call _clear_registry() to work on an empty registry. The real
# commands (generate_proxy, conform_texture, ...) register once at import time, so a
# later suite in the same process (tests/run_tests.py) would find them gone. Import
# setUpModule/tearDownModule from here to snapshot the registry and restore it.

from __future__ import annotations

from flux_core import registry

_snapshot: dict = {}


def setUpModule() -> None:  # noqa: N802 (unittest API)
    _snapshot.clear()
    _snapshot.update(registry._REGISTRY)


def tearDownModule() -> None:  # noqa: N802 (unittest API)
    registry._REGISTRY.clear()
    registry._REGISTRY.update(_snapshot)
