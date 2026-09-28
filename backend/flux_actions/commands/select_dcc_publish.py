# select_dcc_publish.py — pick what a DCC scene publish will produce.
#
# Single responsibility: turn the scene identity (a FLUX base name + a target
# format) into a validated logical filename, and carry the export intent (scope)
# forward. No side effect, no disk write, no DCC call. This mirrors select_publish
# but for a DCC where the source file does not exist yet: it will be produced by
# the export step, so there is no source_path here.
#
# Outputs feed the later steps by named reference:
#   filename   -> the logical FLUX filename (resolves the destination, names the copy)
#   extension  -> the target format, consumed by the export step
#   scope      -> "scene" or "selection", consumed by the export step

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from flux_core import CommandBase, register

from features.folder_manager.naming_validator import parse_filename


@register("select_dcc_publish")
class SelectDccPublish(CommandBase):
    """Validate a DCC scene publish target and compute its logical FLUX filename."""
    doc_fr = "Verifie la cible d'un publish depuis un logiciel et calcule son nom FLUX."

    parameters = {
        # The FLUX base name of the scene, e.g. "CHAR_RIG_HERO_null" (no extension).
        "base_name": {
            "type": "str",
            "label": "Nom de la scene",
            "ask_user": True,
        },
        # Target format as a dotted extension: ".mb", ".ma", ".abc", ".fbx", ...
        "extension": {
            "type": "str",
            "label": "Format",
            "value": ".mb",
            "ask_user": True,
        },
        # "scene" exports everything, anything else exports the current selection.
        "scope": {
            "type": "str",
            "label": "Portee",
            "value": "scene",
            "ask_user": True,
        },
    }

    async def run(
        self, parameters: Dict[str, Any], action_query: Any, logger: logging.Logger
    ) -> Dict[str, Any]:
        base_name: str = str(parameters["base_name"]).strip()
        extension: str = str(parameters.get("extension") or ".mb").strip()
        scope: str = str(parameters.get("scope") or "scene").strip()

        ext = extension if extension.startswith(".") else f".{extension}"
        # A base name must not already carry an extension; the format owns it.
        filename = f"{Path(base_name).stem}{ext}"

        if parse_filename(filename) is None:
            raise ValueError(f"nom de scene non valide pour FLUX: {filename!r}")

        return {
            "filename": filename,
            "extension": ext,
            "scope": "scene" if scope == "scene" else "selection",
        }
