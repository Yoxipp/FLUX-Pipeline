# usd_assembler_core.py — the feature façade: the one entry point that turns a
# declarative recipe into published USD on disk. Wires loader -> composer ->
# validator -> writer; everything else in the feature stays a replaceable part.

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .compose.composer import StageComposer
from .context import build_context
from .io.writer import StageWriter
from .recipe import loader
from .registry import default_registry
from .validate.validator import AssemblyValidator, Issue

if TYPE_CHECKING:  # pragma: no cover
    from .resolve.base import AssetResolver

log = logging.getLogger(__name__)


def _maybe_author_proxy(root: Path) -> Path | None:
    """Author purpose=proxy geometry for the assembled root, ON by default.

    Reuses the publish-time proxy generator and its opt-out switch
    (FLUX_PROXY_USD / FLUX_PROXY_REDUCTION). Proxy generation must never break an
    assembly, so every failure is swallowed and reported as None. Returns the
    written proxy layer path when one was produced.
    """
    try:
        from flux_actions.switch import proxy_usd_enabled, proxy_usd_reduction
        from features.publisher.usd_proxy import generate_proxy, is_usd_asset
    except Exception:  # noqa: BLE001 - optional deps (pxr / fast-simplification)
        return None

    if not proxy_usd_enabled() or not is_usd_asset(root):
        return None
    try:
        result = generate_proxy(root, target_reduction=proxy_usd_reduction())
    except Exception:  # noqa: BLE001 - proxy must never break an assembly
        log.exception("USD proxy a échoué pour %s", root)
        return None
    if result.status != "converted":
        return None
    log.info("USD proxy (assemblage): %s -> %s (%s tris -> %s)",
             root.name, result.dst, result.tris_in, result.tris_out)
    return result.dst


@dataclass(frozen=True)
class AssemblyResult:
    """Outcome of one assemble pass: the published root, every written layer, and
    any validation issues (always present; only errors block a strict run)."""

    root: Path
    layers: tuple[Path, ...] = ()
    issues: tuple[Issue, ...] = ()


class AssemblyError(RuntimeError):
    """Raised when a strict assemble hits validation errors. Carries the issues."""

    def __init__(self, issues: list[Issue]) -> None:
        self.issues = tuple(issues)
        detail = "; ".join(f"{i.level}: {i.msg}" for i in issues if i.level == "error")
        super().__init__(f"assembly validation failed: {detail}")


def assemble(
    recipe: dict,
    *,
    resolver: "AssetResolver",
    dest_dir: str | Path,
    config: dict | None = None,
    strict: bool = True,
) -> AssemblyResult:
    """Assemble *recipe* and publish the result under *dest_dir*.

    *resolver* freezes asset identities to published paths; *dest_dir* is where
    the root layer (and any department sublayers) are written. With *strict*,
    validation errors raise AssemblyError before anything is written.
    """
    ctx = build_context(strict=strict, config=config)
    ctx.resolver = resolver
    # Where the root layer lands — lets the composer write component subLayerPaths
    # relative to it (portable, no absolute paths baked into the published root).
    ctx.output_dir = Path(dest_dir)

    parsed = loader.load(recipe)
    composer = StageComposer(ctx, default_registry())
    stage = composer.compose(parsed)

    issues = AssemblyValidator().check(stage)
    if strict and AssemblyValidator.has_errors(issues):
        raise AssemblyError(issues)

    default = stage.GetDefaultPrim()
    root_name = default.GetName() if default and default.IsValid() else (parsed.target_kind or "stage")
    written = StageWriter().write_all(
        stage, composer.department_layers(), dest_dir, root_name
    )
    # Auto-generate proxy geometry for the assembled root (opt-out). A produced
    # proxy layer is appended to the written layers so callers can see it.
    layers = list(written)
    proxy_layer = _maybe_author_proxy(written[0])
    if proxy_layer is not None and proxy_layer not in layers:
        layers.append(proxy_layer)
    return AssemblyResult(root=written[0], layers=tuple(layers), issues=tuple(issues))
