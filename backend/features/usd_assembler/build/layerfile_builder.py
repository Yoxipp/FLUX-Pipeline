# layerfile_builder.py — declare one published layer file (model/skel/anim/cam/
# light) of a component's slot stack. Pure python, zero pxr: it freezes the slot
# to a concrete published path via ``ctx.resolver.resolve_layer`` and emits a
# LAYERFILE contribution. The composer turns the collected stack into the root
# layer's ``subLayerPaths`` (strong→weak) and authors the component root.

from __future__ import annotations

from typing import TYPE_CHECKING

from ..resolve.base import ResolveError
from .base import Arc, LayerContribution

if TYPE_CHECKING:
    from ..context import AssemblyContext
    from ..recipe.model import LayerSpec


class LayerFileBuilder:
    """Resolve one slot of a component to a published layer file.

    Reads ``spec.params`` (asset / task / layer / version / order) and freezes the
    layer through ``ctx.resolver.resolve_layer``. In strict mode a missing layer
    propagates the ResolveError (the assemble fails loudly); in permissive mode
    the slot is dropped with a warning so the rest still composes.
    """

    kind = "layerfile"

    def contribute(
        self, ctx: "AssemblyContext", spec: "LayerSpec"
    ) -> list[LayerContribution]:
        params = spec.params
        asset = params["asset"]
        task = params["task"]
        layer = params["layer"]
        version = params.get("version", "latest")
        order = params.get("order", 0)

        try:
            resolved = ctx.resolver.resolve_layer(asset, task, layer, version)
        except ResolveError:
            if ctx.strict:
                raise
            ctx.log.warning(
                "layer '%s' of '%s' (task '%s', version '%s') unresolved; "
                "skipped (permissive)",
                layer,
                asset,
                task,
                version,
            )
            return []

        return [
            LayerContribution(
                prim_path=f"/{resolved.default_prim}",
                arc=Arc.LAYERFILE,
                asset=resolved,
                opinions={"order": order, "slot": spec.name},
            )
        ]
