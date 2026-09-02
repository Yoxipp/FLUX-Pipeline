# model.py — declarative recipe data model (frozen dataclasses, zero pxr).
#
# Two layers of representation live here:
#   * authoring specs (VariantSpec, RefSpec) mirror what a user writes;
#   * the canonical Recipe(target, layers, options) is what the composer iterates,
#     where each LayerSpec.kind maps to a builder registry key.
# The loader validates the authoring JSON and normalises it into this Recipe.

from __future__ import annotations

from dataclasses import dataclass, field

# Builder kinds a normalised LayerSpec may carry (== registry keys).
LAYER_KINDS: frozenset[str] = frozenset(
    {"sublayer", "reference", "payload", "variantset", "prim", "layerfile"}
)

# Recipe target kinds (what we are assembling).
TARGET_KINDS: frozenset[str] = frozenset(
    {"component", "assembly", "shot", "sequence"}
)


@dataclass(frozen=True)
class VariantSpec:
    """A single variant selection: pick *selection* inside variantSet *set_name*."""

    set_name: str
    selection: str


@dataclass(frozen=True)
class RefSpec:
    """A pipeline identity to reference (never a resolved path).

    *version* stays symbolic ("latest" or "v###") until the resolver freezes it.
    """

    asset: str
    version: str = "latest"
    instance: str | None = None
    variants: tuple[VariantSpec, ...] = ()


@dataclass(frozen=True)
class LayerSpec:
    """One normalised unit of composition. *kind* selects the builder; *params*
    carries builder-specific data (asset/version/department/variants…)."""

    kind: str
    name: str
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Recipe:
    """Canonical, composer-facing recipe.

    *target* describes what is assembled (kind + identity), *layers* is the
    deterministically ordered composition plan, *options* holds format/load knobs.
    """

    target: dict
    layers: tuple[LayerSpec, ...] = ()
    options: dict = field(default_factory=dict)

    @property
    def target_kind(self) -> str:
        return str(self.target.get("kind", ""))
