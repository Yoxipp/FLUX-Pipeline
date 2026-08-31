# prim_builder.py — declare a container prim (assembly / group root): its type,
# USD kind and defaultPrim. Pure: describes one prim contribution, no stage.

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Arc, LayerContribution

if TYPE_CHECKING:
    from ..context import AssemblyContext
    from ..recipe.model import LayerSpec


class PrimBuilder:
    """Build the root container prim of an assembly/group target.

    Reads ``spec.params['asset']`` (the container identity) and
    ``['target_kind']`` (defaults to ``assembly``), and marks the prim as the
    stage's defaultPrim. It carries no composition arc of its own — the composer
    simply *defines* the prim and stamps its kind/defaultPrim.
    """

    kind = "prim"

    def contribute(
        self, ctx: "AssemblyContext", spec: "LayerSpec"
    ) -> list[LayerContribution]:
        asset = spec.params["asset"]
        target_kind = spec.params.get("target_kind", "assembly")

        prim_path = ctx.naming.prim_path(asset)
        return [
            LayerContribution(
                prim_path=prim_path,
                arc=Arc.OVER,
                opinions={
                    "prim_type": "Xform",
                    "kind": ctx.kinds.kind_for(target_kind),
                    "default_prim": True,
                },
            )
        ]
