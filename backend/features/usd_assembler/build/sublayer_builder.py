# sublayer_builder.py — declare one department layer of a shot's sublayer stack.
# Pure: describes a SUBLAYER contribution (dept + deterministic file name); the
# composer creates the layer and orders the stack.

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Arc, LayerContribution

if TYPE_CHECKING:
    from ..context import AssemblyContext
    from ..recipe.model import LayerSpec


class SublayerBuilder:
    """Describe one department sublayer of a shot.

    Reads ``spec.params['department']`` and ``['entity']`` (the shot identity) and
    resolves the layer file name through ``ctx.layout``. It carries no prim; the
    composer materialises the layer and finalises the strong→weak stack order.
    """

    kind = "sublayer"

    def contribute(
        self, ctx: "AssemblyContext", spec: "LayerSpec"
    ) -> list[LayerContribution]:
        dept = spec.params["department"]
        entity = spec.params["entity"]
        filename = ctx.layout.filename(entity, dept)
        return [
            LayerContribution(
                prim_path="/",
                arc=Arc.SUBLAYER,
                opinions={"department": dept, "filename": filename},
            )
        ]
