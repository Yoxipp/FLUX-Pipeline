# composer.py — StageComposer runs a recipe's builders and applies their
# contributions to a stage. This is the ONLY place Arc -> pxr mapping lives;
# everything upstream (recipe, structure, build) stays pure.

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from pxr import Usd

from ..build.base import Arc, LayerContribution
from ..io import stage_factory

if TYPE_CHECKING:
    from ..context import AssemblyContext
    from ..recipe.model import Recipe
    from ..registry import Registry


def _as_asset_path(path) -> str:
    """Return a forward-slashed asset path string (USD convention)."""
    return str(path).replace(os.sep, "/")


class StageComposer:
    """Compose a recipe into an in-memory Usd.Stage.

    The composer asks the registry for a builder per LayerSpec, collects the
    contributions, and applies each arc. It never imports a concrete builder.
    """

    def __init__(self, ctx: "AssemblyContext", registry: "Registry") -> None:
        self._ctx = ctx
        self._registry = registry

    def compose(self, recipe: "Recipe") -> "Usd.Stage":
        stage = stage_factory.in_memory()
        for spec in recipe.layers:
            builder = self._registry.get_builder(spec.kind)
            for contrib in builder.contribute(self._ctx, spec):
                self._apply(stage, contrib)
        return stage

    # ── Arc -> pxr ──────────────────────────────────────────────────────────────
    def _apply(self, stage: "Usd.Stage", contrib: LayerContribution) -> None:
        handler = {
            Arc.PAYLOAD: self._apply_payload,
            Arc.VARIANT: self._apply_variant,
        }.get(contrib.arc)
        if handler is None:
            self._ctx.log.warning("arc %s not handled yet (later phase)", contrib.arc)
            return
        handler(stage, contrib)

    def _apply_payload(self, stage: "Usd.Stage", contrib: LayerContribution) -> None:
        prim_type = contrib.opinions.get("prim_type", "Xform")
        prim = stage.DefinePrim(contrib.prim_path, prim_type)

        kind = contrib.opinions.get("kind")
        if kind:
            Usd.ModelAPI(prim).SetKind(kind)

        if contrib.asset is not None:
            prim.GetPayloads().AddPayload(_as_asset_path(contrib.asset.path))

        if contrib.opinions.get("default_prim"):
            stage.SetDefaultPrim(prim)

    def _apply_variant(self, stage: "Usd.Stage", contrib: LayerContribution) -> None:
        prim = stage.GetPrimAtPath(contrib.prim_path)
        if not prim or not prim.IsValid():
            prim = stage.DefinePrim(contrib.prim_path, "Xform")

        vset = prim.GetVariantSets().AddVariantSet(contrib.opinions["variant_set"])
        for variant in contrib.opinions.get("variants", []):
            vset.AddVariant(variant)
        default = contrib.opinions.get("default")
        if default:
            vset.SetVariantSelection(default)
