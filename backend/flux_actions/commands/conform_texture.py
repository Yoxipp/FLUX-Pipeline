# conform_texture.py - conform a texture (or UDIM set) to mipped/tiled .tx.
#
# Single responsibility: run the publish-time texture conform and report the
# resulting .tx paths. It is a thin wrapper over the feature core
# (features.publisher.texture_conform); no pixel logic lives here.
#
# The "source" may be one file, a folder, or a UDIM pattern ("<UDIM>"): the core
# expands it to the actual tiles and converts each, skipping unchanged ones.
# Output goes next to the source, or into "out_dir" when given. Wiring the .tx
# into the versioned publish layout (build_output_path / copy_publish) is a
# later phase; this command keeps placement explicit so it stays testable.

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from flux_core import CommandBase, register

from features.publisher.texture_conform import (
    DEFAULT_COLOR_IN,
    DEFAULT_COLOR_OUT,
    conform_set,
)


@register("conform_texture")
class ConformTexture(CommandBase):
    """Conform a texture / UDIM set to Karma-friendly mipped, tiled .tx files."""

    parameters = {
        "source": {
            "type": "path",
            "label": "Texture source",
            "ask_user": True,
        },
        # Where to write the .tx; empty means "next to the source file".
        "out_dir": {
            "type": "str",
            "label": "Dossier de sortie",
            "value": "",
            "hide": True,
        },
        "colorconvert": {
            "type": "bool",
            "label": "Convertir l'espace couleur (sRGB vers lineaire)",
            "value": True,
        },
        "color_in": {
            "type": "str",
            "label": "Espace d'entree (maps couleur)",
            "value": DEFAULT_COLOR_IN,
            "hide": True,
        },
        "color_out": {
            "type": "str",
            "label": "Espace de sortie (maps couleur)",
            "value": DEFAULT_COLOR_OUT,
            "hide": True,
        },
        "force": {
            "type": "bool",
            "label": "Forcer la reconversion",
            "value": False,
            "hide": True,
        },
    }

    async def run(
        self, parameters: Dict[str, Any], action_query: Any, logger: logging.Logger
    ) -> Dict[str, Any]:
        source: Path = parameters["source"]
        out_dir_raw: str = parameters.get("out_dir") or ""
        out_dir = Path(out_dir_raw) if out_dir_raw else None

        summary = conform_set(
            [str(source)],
            out_dir=out_dir,
            color_in=parameters.get("color_in") or DEFAULT_COLOR_IN,
            color_out=parameters.get("color_out") or DEFAULT_COLOR_OUT,
            force=bool(parameters.get("force")),
            colorconvert=bool(parameters.get("colorconvert", True)),
        )

        # A failed tile is a hard error: the publish must not silently ship a
        # texture set with a missing .tx.
        if summary.failed:
            failed = ", ".join(
                r.src.name for r in summary.results if r.status == "failed"
            )
            raise ValueError(f"conform .tx echoue pour: {failed}")

        tx_paths = [
            str(r.dst) for r in summary.results
            if r.status in ("converted", "skipped")
        ]
        logger.info(
            "conform_texture: %d converted, %d skipped, %d ignored -> %d .tx",
            summary.converted, summary.skipped, len(summary.ignored), len(tx_paths),
        )
        return {
            "tx_paths": tx_paths,
            "converted": summary.converted,
            "skipped": summary.skipped,
            "ignored": len(summary.ignored),
        }
