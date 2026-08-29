# registry.py — plugin registry for builders and resolvers. Pure python, zero pxr.
# The composer only ever talks to this registry, never to concrete builders.

from __future__ import annotations

from typing import Any


class Registry:
    """Hold builders (keyed by their ``kind``) and named resolvers.

    Builders are duck-typed: any object exposing a ``kind: str`` attribute and a
    ``contribute(ctx, spec)`` method qualifies. Kept loose so structure/recipe
    stay importable without pxr.
    """

    def __init__(self) -> None:
        self._builders: dict[str, Any] = {}
        self._resolvers: dict[str, Any] = {}

    # ── builders ──────────────────────────────────────────────────────────────
    def register_builder(self, builder: Any) -> None:
        """Register *builder* under its ``kind`` (last registration wins)."""
        kind = getattr(builder, "kind", None)
        if not kind:
            raise ValueError("builder must expose a non-empty 'kind' attribute")
        self._builders[kind] = builder

    def get_builder(self, kind: str) -> Any:
        """Return the builder registered for *kind* (raises if missing)."""
        try:
            return self._builders[kind]
        except KeyError:
            raise KeyError(f"no builder registered for kind '{kind}'")

    def has_builder(self, kind: str) -> bool:
        return kind in self._builders

    # ── resolvers ─────────────────────────────────────────────────────────────
    def register_resolver(self, name: str, resolver: Any) -> None:
        if not name:
            raise ValueError("resolver name must be non-empty")
        self._resolvers[name] = resolver

    def get_resolver(self, name: str) -> Any:
        try:
            return self._resolvers[name]
        except KeyError:
            raise KeyError(f"no resolver registered under '{name}'")

    # ── plugins ───────────────────────────────────────────────────────────────
    def discover_plugins(self) -> None:
        """Auto-discover studio plugins under ``plugins/`` (Phase 6).

        Stubbed in Phase 0: no-op so the import graph stays pure and the call
        site (façade) can already be wired.
        """
        return None


# Module-level singleton wired at startup / by the façade.
REGISTRY = Registry()
