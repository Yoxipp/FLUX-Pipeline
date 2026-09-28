# generate_proxy.py - author lightweight USD proxy geometry (purpose=proxy).
#
# Single responsibility: run the publish-time USD proxy generation and report
# the proxy layer path + triangle counts. Thin wrapper over the feature core
# (features.publisher.usd_proxy); no geometry logic lives here.
#
# Sister of conform_texture: same family of headless, no-token optimisation
# actions (pxr + fast-simplification, never Houdini).

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from flux_core import CommandBase, register

from features.publisher.usd_proxy import (
    DEFAULT_MIN_TRIS,
    DEFAULT_REDUCTION,
    generate_proxy,
)


@register("generate_proxy")
class GenerateProxy(CommandBase):
    """Generate a decimated purpose=proxy sibling for each render mesh in a USD.
    Done by FLUX itself in Python (pxr + fast-simplification): no Houdini, no DCC
    opened, no license token."""

    parameters = {
        "source": {
            "type": "path",
            "label": "Asset USD source",
            "ask_user": True,
        },
        # Proxy layer path; empty means "<source>.proxy.usda" next to the asset.
        "out": {
            "type": "str",
            "label": "Layer proxy de sortie",
            "value": "",
            "hide": True,
        },
        "target_reduction": {
            "type": "float",
            "label": "Reduction (fraction de triangles retires)",
            "value": DEFAULT_REDUCTION,
        },
        "min_tris": {
            "type": "int",
            "label": "Seuil de triangles sous lequel on ne decime pas",
            "value": DEFAULT_MIN_TRIS,
            "hide": True,
        },
        "force": {
            "type": "bool",
            "label": "Forcer la regeneration",
            "value": False,
            "hide": True,
        },
    }

    async def run(
        self, parameters: Dict[str, Any], action_query: Any, logger: logging.Logger
    ) -> Dict[str, Any]:
        source: Path = parameters["source"]
        out_raw: str = parameters.get("out") or ""
        out = Path(out_raw) if out_raw else None

        result = generate_proxy(
            source,
            dst_usd=out,
            target_reduction=float(parameters.get("target_reduction", DEFAULT_REDUCTION)),
            min_tris=int(parameters.get("min_tris", DEFAULT_MIN_TRIS)),
            force=bool(parameters.get("force")),
        )
        if result.status == "failed":
            raise ValueError(f"generation proxy USD echouee: {result.error}")

        logger.info(
            "generate_proxy: %s -> %s (%d meshes, %d -> %d tris, %d grooms, %d -> %d curves)",
            result.src.name, result.dst.name,
            result.meshes, result.tris_in, result.tris_out,
            result.grooms, result.curves_in, result.curves_out,
        )
        return {
            "proxy_path": str(result.dst),
            "status": result.status,
            "meshes": result.meshes,
            "tris_in": result.tris_in,
            "tris_out": result.tris_out,
            "grooms": result.grooms,
            "curves_in": result.curves_in,
            "curves_out": result.curves_out,
        }
