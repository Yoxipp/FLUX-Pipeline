# composer.py — StageComposer runs a recipe's builders and applies their
# contributions to a stage. This is the ONLY place Arc -> pxr mapping lives;
# everything upstream (recipe, structure, build) stays pure.

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from pxr import Gf, Usd, UsdGeom

from ..build.base import Arc, LayerContribution
from ..io import stage_factory
from .edit_target import EditTargetRouter

if TYPE_CHECKING:
    from ..context import AssemblyContext
    from ..recipe.model import Recipe
    from ..registry import Registry


class StageComposer:
    """Compose a recipe into an in-memory Usd.Stage.

    The composer asks the registry for a builder per LayerSpec, collects the
    contributions, and applies each arc. It never imports a concrete builder.
    """

    def __init__(self, ctx: "AssemblyContext", registry: "Registry") -> None:
        self._ctx = ctx
        self._registry = registry
        self._router: EditTargetRouter | None = None
        # Component layer-file contributions, collected then flushed to the root's
        # subLayerPaths at finalize (a component's slots compose as sublayers).
        self._layerfiles: list[LayerContribution] = []

    def compose(self, recipe: "Recipe") -> "Usd.Stage":
        stage = stage_factory.in_memory()
        self._router = EditTargetRouter(stage)
        self._layerfiles = []
        for spec in recipe.layers:
            builder = self._registry.get_builder(spec.kind)
            for contrib in builder.contribute(self._ctx, spec):
                self._apply(stage, contrib)
        # Publish the shot sublayer stack strongest-first (no-op without depts).
        self._router.finalize(list(reversed(self._ctx.layout.department_order())))
        # Then flush any component layer-file stack onto the (now empty) root.
        self._finalize_layerfiles(stage)
        return stage

    def department_layers(self) -> dict:
        """Return {dept: (filename, Sdf.Layer)} produced by the last compose()."""
        return self._router.department_layers() if self._router else {}

    # ── Arc -> pxr ──────────────────────────────────────────────────────────────
    def _apply(self, stage: "Usd.Stage", contrib: LayerContribution) -> None:
        if contrib.arc is Arc.LAYERFILE:
            # Deferred: applied as a batch on the root layer at finalize.
            self._layerfiles.append(contrib)
            return

        if contrib.arc is Arc.SUBLAYER:
            self._apply_sublayer(contrib)
            return

        handler = {
            Arc.PAYLOAD: self._apply_payload,
            Arc.VARIANT: self._apply_variant,
            Arc.REFERENCE: self._apply_reference,
            Arc.OVER: self._apply_prim,
        }.get(contrib.arc)
        if handler is None:
            self._ctx.log.warning("arc %s not handled yet (later phase)", contrib.arc)
            return

        # Route the contribution into its department layer, if any.
        dept = contrib.opinions.get("dept")
        routed = dept is not None and self._router is not None
        if routed:
            stage.SetEditTarget(self._router.target_for(dept))
        try:
            handler(stage, contrib)
        finally:
            if routed:
                stage.SetEditTarget(self._router.root_target())

    def _apply_sublayer(self, contrib: LayerContribution) -> None:
        """Materialise a department layer under the root (order fixed on finalize)."""
        assert self._router is not None
        self._router.add_department(
            contrib.opinions["department"], contrib.opinions["filename"]
        )

    # ── component layer-file stack ──────────────────────────────────────────────
    def _finalize_layerfiles(self, stage: "Usd.Stage") -> None:
        """Publish the component slot stack as the root's subLayerPaths + root prim.

        Each resolved slot becomes a sublayer, ordered strong→weak (lowest
        ``order`` first). All slots of a v2 layered publish share one base, so the
        composed prims land on ``/<base>``; the root then gets an *over* there that
        stamps kind=component and becomes the stage defaultPrim — no typeName, so
        the model sublayer's SkelRoot/Mesh types survive untouched.
        """
        if not self._layerfiles:
            return

        root = stage.GetRootLayer()
        ordered = sorted(self._layerfiles, key=lambda c: c.opinions.get("order", 0))
        out_dir = getattr(self._ctx, "output_dir", None)
        for contrib in ordered:
            if contrib.asset is None:
                continue
            root.subLayerPaths.append(self._layer_ref(contrib.asset.path, out_dir))

        # The weakest slot (highest order, typically the model) carries the
        # geometry base — the defaultPrim every slot composes onto.
        base_prim = ordered[-1].asset.default_prim if ordered[-1].asset else None
        if not base_prim:
            return
        over = stage.OverridePrim(f"/{base_prim}")
        Usd.ModelAPI(over).SetKind(self._ctx.kinds.kind_for("component"))
        stage.SetDefaultPrim(over)

    @staticmethod
    def _layer_ref(path, out_dir) -> str:
        """Express a published layer path relative to *out_dir* (forward slashes).

        Falls back to an absolute posix path when the layer lives on another drive
        (Windows ``relpath`` raises across drives), keeping the root reopenable.
        A relative input path is kept as-is (already anchored by the caller).
        """
        if not Path(path).is_absolute():
            return Path(path).as_posix()
        if out_dir is not None:
            try:
                return os.path.relpath(str(path), str(out_dir)).replace(os.sep, "/")
            except ValueError:
                pass
        return Path(path).as_posix()

    def _apply_payload(self, stage: "Usd.Stage", contrib: LayerContribution) -> None:
        prim_type = contrib.opinions.get("prim_type", "Xform")
        prim = stage.DefinePrim(contrib.prim_path, prim_type)

        kind = contrib.opinions.get("kind")
        if kind:
            Usd.ModelAPI(prim).SetKind(kind)

        if contrib.asset is not None:
            prim.GetPayloads().AddPayload(self._layer_ref(contrib.asset.path, self._ctx.output_dir))

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
            prim.GetReferences().AddReference(self._layer_ref(contrib.asset.path, self._ctx.output_dir))

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
