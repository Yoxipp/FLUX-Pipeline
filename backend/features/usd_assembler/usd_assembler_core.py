# usd_assembler_core.py — the feature façade: the one entry point that turns a
# declarative recipe into published USD on disk. Wires loader -> composer ->
# validator -> writer; everything else in the feature stays a replaceable part.

from __future__ import annotations

from dataclasses import dataclass, field
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
    return AssemblyResult(root=written[0], layers=tuple(written), issues=tuple(issues))
