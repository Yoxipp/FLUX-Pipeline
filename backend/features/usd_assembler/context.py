# context.py — AssemblyContext bundles the injected dependencies a build/compose
# pass needs. Pure python (no pxr); the resolver is attached later (Phase 1).

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.logger import get_logger

from .structure.kinds import KindPolicy
from .structure.layout import LayerNaming
from .structure.naming import PrimNamer

_CONFIG_NAMESPACE = "usd_assembler"


@dataclass
class AssemblyContext:
    """Dependencies injected into builders and the composer.

    *resolver* stays ``None`` in Phase 0 (no pxr / no pipeline resolution yet);
    it is filled by build_context once the FluxResolver lands.
    """

    config: dict = field(default_factory=dict)
    resolver: Any | None = None
    naming: PrimNamer = field(default_factory=PrimNamer)
    kinds: KindPolicy = field(default_factory=KindPolicy)
    layout: LayerNaming = field(default_factory=LayerNaming)
    log: Any = field(default_factory=lambda: get_logger("usd_assembler"))
    strict: bool = True


def build_context(*, strict: bool = True, config: dict | None = None) -> AssemblyContext:
    """Assemble an AssemblyContext from the ``usd_assembler`` config namespace.

    *config* lets tests inject a namespace directly; otherwise it is read from
    core.config, degrading to defaults when the pipeline config is absent.
    """
    ns: dict
    if config is not None:
        ns = config
    else:
        try:
            from core import config as flux_config

            ns = flux_config.get(_CONFIG_NAMESPACE, {}) or {}
        except Exception:
            ns = {}

    return AssemblyContext(
        config=ns,
        resolver=None,
        naming=PrimNamer(),
        kinds=KindPolicy(ns.get("kinds")),
        layout=LayerNaming(ns),
        log=get_logger("usd_assembler"),
        strict=strict,
    )
