# kinds.py — map a recipe target kind to a USD Kind token. Pure python, zero pxr.
# Values match pxr.Kind.Tokens but are declared here so structure/ stays USD-free.

from __future__ import annotations

# USD model-hierarchy kinds we assign. Group is a pure organiser (no model kind
# below it becomes a model root by mistake).
KIND_COMPONENT = "component"
KIND_ASSEMBLY = "assembly"
KIND_GROUP = "group"
KIND_SUBCOMPONENT = "subcomponent"

_VALID_KINDS = frozenset(
    {KIND_COMPONENT, KIND_ASSEMBLY, KIND_GROUP, KIND_SUBCOMPONENT}
)

# Default target-kind -> USD kind. A shot/sequence root groups assemblies, so it
# is not itself a model root -> group.
_DEFAULT_MAP: dict[str, str] = {
    "component": KIND_COMPONENT,
    "assembly": KIND_ASSEMBLY,
    "shot": KIND_GROUP,
    "sequence": KIND_GROUP,
}


class KindPolicy:
    """Resolve USD kinds from recipe target kinds, overridable by config.

    *overrides* comes from config (``config["usd_assembler"]["kinds"]``) so the
    mapping is data-driven, never hardcoded at call sites.
    """

    def __init__(self, overrides: dict[str, str] | None = None) -> None:
        table = dict(_DEFAULT_MAP)
        if overrides:
            table.update(overrides)
        self._map = table

    def kind_for(self, target_kind: str) -> str:
        """Return the USD kind for *target_kind* (raises on unknown mapping)."""
        try:
            kind = self._map[target_kind]
        except KeyError:
            raise KeyError(f"no USD kind mapped for target kind '{target_kind}'")
        return kind

    @staticmethod
    def is_valid_kind(kind: str) -> bool:
        return kind in _VALID_KINDS
