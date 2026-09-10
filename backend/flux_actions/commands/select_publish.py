# select_publish.py — pick the source file and derive its logical FLUX name.
#
# Single responsibility: turn "what the user handed us" into a validated set of
# publish inputs. No side effect, no disk write. It mirrors Silex's "select"
# command: it only selects and validates, it never copies.
#
# Outputs feed the later steps by named reference:
#   source_path -> the file whose bytes will be published
#   filename    -> the logical FLUX filename (used to resolve the destination)
#   target_name -> the composed token name when the source isn't token-named

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from flux_core import CommandBase, register

from features.folder_manager.naming_validator import parse_filename


@register("select_publish")
class SelectPublish(CommandBase):
    """Validate the publish source and compute its logical FLUX filename."""

    parameters = {
        # The concrete file to publish (a DCC export, or a plain local file).
        "source_path": {
            "type": "path",
            "label": "Fichier a publier",
            "ask_user": True,
        },
        # Composed FLUX name when the source filename isn't token-named
        # (e.g. a local "Capture.png"). Optional; hidden from the basic form.
        "target_name": {
            "type": "str",
            "label": "Nom FLUX cible",
            "hide": True,
        },
    }

    async def run(
        self, parameters: Dict[str, Any], action_query: Any, logger: logging.Logger
    ) -> Dict[str, Any]:
        source_path: Path = parameters["source_path"]
        target_name = parameters.get("target_name")

        # Same rule as publish_file: a target_name wins and keeps/gets an
        # extension; otherwise the source filename must already be a FLUX name.
        if target_name:
            filename = (
                target_name
                if Path(target_name).suffix
                else f"{target_name}{source_path.suffix}"
            )
        else:
            filename = source_path.name

        if parse_filename(filename) is None:
            raise ValueError(f"nom de fichier non valide pour FLUX: {filename!r}")

        return {
            "source_path": source_path,
            "filename": filename,
            "target_name": target_name,
        }
