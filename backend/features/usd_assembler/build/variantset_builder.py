# variantset_builder.py — define a component's variantSets (lod / purpose / look).
# The set/variant *structure* is the component's own; selections happen later at
# assembly time. Config-driven (config['component_variants']), pure, zero pxr.

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Arc, LayerContribution

if TYPE_CHECKING:
    from ..context import AssemblyContext
    from ..recipe.model import LayerSpec

# Documented default variantSet templates; overridden by
# config['component_variants']. First variant of each set is the default.
DEFAULT_COMPONENT_VARIANTS: dict[str, tuple[str, ...]] = {
    "lod": ("hi", "mid", "lo"),
    "purpose": ("render", "proxy"),
    "look": ("default",),
}


class VariantSetBuilder:
    """Declare variantSets on the component prim from config templates."""

    kind = "variantset"

    def contribute(
        self, ctx: "AssemblyContext", spec: "LayerSpec"
    ) -> list[LayerContribution]:
        asset = spec.params["asset"]
        templates = ctx.config.get("component_variants") or DEFAULT_COMPONENT_VARIANTS

        prim_path = ctx.naming.prim_path(asset)
        contributions: list[LayerContribution] = []
        # Stable order for deterministic golden output.
        for set_name in sorted(templates):
            variants = tuple(templates[set_name])
            if not variants:
                continue
            contributions.append(
                LayerContribution(
                    prim_path=prim_path,
                    arc=Arc.VARIANT,
                    opinions={
                        "variant_set": ctx.naming.variant_name(set_name),
                        "variants": [ctx.naming.variant_name(v) for v in variants],
                        "default": ctx.naming.variant_name(variants[0]),
                    },
                )
            )
        return contributions
