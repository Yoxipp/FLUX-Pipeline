# plugins/ — studio extension point. Drop a module here that exposes a
# ``register(registry)`` function; it is auto-discovered at startup and can add
# custom builders/resolvers WITHOUT touching the core. Pure python (no pxr): a
# plugin registers builder objects, it does not compose stages.
#
# Example plugin (backend/features/usd_assembler/plugins/acme.py):
#
#     class AcmeCrowdBuilder:
#         kind = "crowd"
#         def contribute(self, ctx, spec): ...
#
#     def register(registry):
#         registry.register_builder(AcmeCrowdBuilder())

from __future__ import annotations

import importlib
import pkgutil
from typing import Iterable


def discover(registry, modules: "Iterable | None" = None) -> list[str]:
    """Register every discovered plugin against *registry*.

    Each plugin module exposes ``register(registry)``. *modules* can be injected
    (tests); otherwise the sibling modules of this package are imported. Returns
    the names of the modules whose ``register`` hook ran, for logging.
    """
    mods = list(modules) if modules is not None else list(_iter_package_modules())
    registered: list[str] = []
    for mod in mods:
        hook = getattr(mod, "register", None)
        if callable(hook):
            hook(registry)
            registered.append(getattr(mod, "__name__", repr(mod)))
    return registered


def _iter_package_modules():
    """Import and yield each non-underscore module inside this package."""
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        yield importlib.import_module(f"{__name__}.{info.name}")
