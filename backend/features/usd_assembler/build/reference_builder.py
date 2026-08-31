# reference_builder.py — reference a published component into an assembly as an
# instance prim (with its placement xform and any variant selections). Pure:
# resolves the asset path and describes one REFERENCE contribution, no stage.

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Arc, LayerContribution

if TYPE_CHECKING:
    from ..context import AssemblyContext
    from ..recipe.model import LayerSpec

# Xform channels supported on an instance, applied in this fixed order for
# deterministic output. Each is an optional sequence of 3 numbers.
_XFORM_CHANNELS: tuple[str, ...] = ("translate", "rotate", "scale")


def _normalise_xform(raw: dict | None) -> dict | None:
    """Coerce a raw xform dict into ordered float triples (pure, deterministic).

    Unknown channels are ignored; each kept channel becomes a 3-tuple of floats
    so the composer can map it straight onto a Gf vector without re-validating.
    """
    if not raw:
        return None
    out: dict[str, tuple[float, float, float]] = {}
    for channel in _XFORM_CHANNELS:
        value = raw.get(channel)
        if value is None:
            continue
        if len(value) != 3:
            raise ValueError(f"xform.{channel} must have 3 components, got {value!r}")
        out[channel] = (float(value[0]), float(value[1]), float(value[2]))
    return out or None


class ReferenceBuilder:
    """Reference a component asset into an assembly as one instance prim.

    Places the instance under the assembly root (``spec.params['parent_entity']``,
    falling back to the stage root), authors its placement xform, and records any
    variant *selections* the recipe asked for — the variantSets themselves belong
    to the referenced component, the assembly only selects among them.
    """

    kind = "reference"

    def contribute(
        self, ctx: "AssemblyContext", spec: "LayerSpec"
    ) -> list[LayerContribution]:
        ref = spec.params["ref"]
        resolved = ctx.resolver.resolve(ref.asset, ref.version)

        parent_entity = spec.params.get("parent_entity")
        parent = ctx.naming.prim_path(parent_entity) if parent_entity else "/"
        leaf = ref.instance or ref.asset
        prim_path = ctx.naming.prim_path(leaf, parent=parent)

        opinions: dict = {"prim_type": "Xform"}
        dept = spec.params.get("dept")
        if dept is not None:
            opinions["dept"] = dept
        xform = _normalise_xform(spec.params.get("xform"))
        if xform:
            opinions["xform"] = xform
        if ref.variants:
            # RefSpec.variants is already deterministically ordered by the loader.
            opinions["variant_selections"] = {
                v.set_name: v.selection for v in ref.variants
            }

        return [
            LayerContribution(
                prim_path=prim_path,
                arc=Arc.REFERENCE,
                asset=resolved,
                opinions=opinions,
            )
        ]
