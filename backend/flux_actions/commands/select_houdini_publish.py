# select_houdini_publish.py — pick what a Houdini publish will produce.
#
# Single responsibility: turn the scene identity (a FLUX base name + a target
# format) into a validated base name, and carry the cook intent (which ROP,
# single file or sequence) forward. No side effect, no disk write, no DCC call.
#
# Unlike select_dcc_publish (Maya), the cook step here writes DIRECTLY to the
# resolved destination, so there is no copy step and no temp file. publish_houdini_rop
# takes the base name WITHOUT extension (it appends the format itself), so this
# emits the stem, not the full filename.
#
# Outputs feed the cook step by named reference:
#   base_name     -> the FLUX stem (resolves the destination, names the output)
#   extension     -> the target format, selects the ROP output parameter
#   rop_node_path -> the node to cook; None means "use the selected node"
#   is_sequence   -> single vNNN file (LAST derived) vs a per-version frame sequence folder

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from flux_core import CommandBase, register

from features.folder_manager.naming_validator import parse_filename


@register("select_houdini_publish")
class SelectHoudiniPublish(CommandBase):
    """Validate a Houdini publish target and carry the cook intent forward."""
    doc_fr = "Verifie la cible d'un publish Houdini et transmet ce qu'il faut cuire."

    parameters = {
        # The FLUX base name of the scene, e.g. "CHAR_RIG_HERO_null" (no extension).
        "base_name": {
            "type": "str",
            "label": "Nom de la scene",
            "ask_user": True,
        },
        # Target format as a dotted extension: ".abc", ".bgeo.sc", ".hip", ...
        "extension": {
            "type": "str",
            "label": "Format",
            "value": ".abc",
            "ask_user": True,
        },
        # The ROP (or any node) to cook. Empty means "use the selected node".
        "rop_node_path": {
            "type": "str",
            "label": "Noeud ROP",
            "value": None,
            "ask_user": True,
        },
        # A frame sequence writes a per-version folder; a single file is a flat vNNN.
        "is_sequence": {
            "type": "bool",
            "label": "Sequence",
            "value": False,
            "ask_user": True,
        },
    }

    async def run(
        self, parameters: Dict[str, Any], action_query: Any, logger: logging.Logger
    ) -> Dict[str, Any]:
        base_name: str = str(parameters["base_name"]).strip()
        extension: str = str(parameters.get("extension") or ".abc").strip()
        rop_node_path = parameters.get("rop_node_path")
        is_sequence: bool = bool(parameters.get("is_sequence"))

        ext = extension if extension.startswith(".") else f".{extension}"
        # A base name must not already carry an extension; the format owns it.
        stem = Path(base_name).stem
        # Validate against the FLUX naming rule by checking the full logical name.
        if parse_filename(f"{stem}{ext}") is None:
            raise ValueError(f"nom de scene non valide pour FLUX: {stem}{ext!r}")

        # An empty string from the UI means "no explicit node" — normalise to None.
        rop = str(rop_node_path).strip() if rop_node_path else None

        return {
            "base_name": stem,
            "extension": ext,
            "rop_node_path": rop or None,
            "is_sequence": is_sequence,
        }
