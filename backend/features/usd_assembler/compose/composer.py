# composer.py — StageComposer runs a recipe's builders and applies their
# contributions to a stage. This is the ONLY place Arc -> pxr mapping lives;
# everything upstream (recipe, structure, build) stays pure.

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from pxr import Gf, Usd, UsdGeom

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
            Arc.REFERENCE: self._apply_reference,
            Arc.OVER: self._apply_prim,
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

    def _apply_prim(self, stage: "Usd.Stage", contrib: LayerContribution) -> None:
        """Define a container prim (assembly/group root) with kind + defaultPrim."""
        prim = stage.DefinePrim(contrib.prim_path, contrib.opinions.get("prim_type", "Xform"))
        kind = contrib.opinions.get("kind")
        if kind:
            Usd.ModelAPI(prim).SetKind(kind)
        if contrib.opinions.get("default_prim"):
            stage.SetDefaultPrim(prim)

    def _apply_reference(self, stage: "Usd.Stage", contrib: LayerContribution) -> None:
        """Reference a component onto an instance prim, then place + select it."""
        prim = stage.DefinePrim(contrib.prim_path, contrib.opinions.get("prim_type", "Xform"))

        if contrib.asset is not None:
            prim.GetReferences().AddReference(_as_asset_path(contrib.asset.path))

        self._apply_xform(prim, contrib.opinions.get("xform"))

        # Variant selections only (the sets live in the referenced component).
        for set_name, selection in sorted(contrib.opinions.get("variant_selections", {}).items()):
            prim.GetVariantSet(set_name).SetVariantSelection(selection)

    @staticmethod
    def _apply_xform(prim: "Usd.Prim", xform: dict | None) -> None:
        """Author translate/rotate/scale ops in a fixed order (deterministic)."""
        if not xform:
            return
        xformable = UsdGeom.Xformable(prim)
        if "translate" in xform:
            xformable.AddTranslateOp().Set(Gf.Vec3d(*xform["translate"]))
        if "rotate" in xform:
            xformable.AddRotateXYZOp().Set(Gf.Vec3f(*xform["rotate"]))
        if "scale" in xform:
            xformable.AddScaleOp().Set(Gf.Vec3f(*xform["scale"]))
