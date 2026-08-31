# payload_builder.py — a component's heavy geometry, attached as a deferred
# payload on the component prim. Pure: describes one PAYLOAD contribution.

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Arc, LayerContribution

if TYPE_CHECKING:
    from ..context import AssemblyContext
    from ..recipe.model import LayerSpec


class PayloadBuilder:
    """Build the payload arc that loads a component's geometry on demand.

    Reads ``spec.params['asset']`` / ``['version']``, resolves the published USD
    through ``ctx.resolver``, and marks the target prim as the component root
    (kind + defaultPrim). Selecting deferred vs eager load stays a compose/stage
    concern; the builder only points at the geometry.
    """

    kind = "payload"

    def contribute(
        self, ctx: "AssemblyContext", spec: "LayerSpec"
    ) -> list[LayerContribution]:
        asset = spec.params["asset"]
        version = spec.params.get("version", "latest")
        resolved = ctx.resolver.resolve(asset, version)

        prim_path = ctx.naming.prim_path(asset)
        opinions = {
            "prim_type": "Xform",
            "kind": ctx.kinds.kind_for("component"),
            "default_prim": True,
        }
        return [
            LayerContribution(
                prim_path=prim_path,
                arc=Arc.PAYLOAD,
                asset=resolved,
                opinions=opinions,
            )
        ]
