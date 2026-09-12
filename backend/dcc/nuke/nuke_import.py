# nuke_import.py — build a Nuke Read node for a FLUX-published file (V6 B1).
#
# Level 2 import: FLUX resolves a published path (same token logic as the importer)
# and asks the in-Nuke bridge to create a Read node for it, with the project default
# read colorspace. FLUX never renders; it only wires the Read to a published file.
#
# The code builder is pure (no Nuke), so it is unit-testable; only import_into_nuke
# talks to the running Nuke through the generic run(code) bridge.

from __future__ import annotations

import json

from core.logger import get_logger
from dcc.nuke.client import nuke_client

log = get_logger(__name__)

# Project default read colorspace (see .nuke/init.py: Read nodes = "rendering").
DEFAULT_READ_COLORSPACE = "rendering"


def build_read_node_code(
    file_path: str,
    first: int | None = None,
    last: int | None = None,
    colorspace: str = DEFAULT_READ_COLORSPACE,
) -> str:
    """Return Nuke Python that creates a Read node for *file_path* and sets
    ``result`` to its node name.

    Pure string builder: no Nuke needed, so it is unit-testable. Paths use forward
    slashes (Nuke's convention) and every value goes through json.dumps so quotes
    and backslashes are escaped safely. When *first*/*last* are given (EXR sequence)
    the frame range is set on the node.
    """
    fp = json.dumps(str(file_path).replace("\\", "/"))
    cs = json.dumps(colorspace)
    lines = [
        f"_r = nuke.nodes.Read(file={fp})",
        f"_r['colorspace'].setValue({cs})",
    ]
    if first is not None and last is not None:
        lines.append(f"_r['first'].setValue({int(first)})")
        lines.append(f"_r['origfirst'].setValue({int(first)})")
        lines.append(f"_r['last'].setValue({int(last)})")
        lines.append(f"_r['origlast'].setValue({int(last)})")
    lines.append("result = _r.name()")
    return "\n".join(lines)


def import_into_nuke(
    project: str,
    class_tok: str,
    type_tok: str,
    name_tok: str,
    instance: str,
    iter_val: str = "LAST",
    first: int | None = None,
    last: int | None = None,
    colorspace: str = DEFAULT_READ_COLORSPACE,
) -> dict:
    """Resolve a published file from tokens and create a Read node in Nuke.

    Returns {ok, node, path} on success, or {ok: False, error}.
    """
    from core.paths import get_project_path
    from features.importer.importer_resolve import resolve_import_path

    project_path = get_project_path(project)
    resolved = resolve_import_path(project_path, class_tok, type_tok, name_tok, instance, iter_val)
    if not resolved.get("ok"):
        return {"ok": False, "error": resolved.get("error", "path not resolved")}

    code = build_read_node_code(resolved["path"], first, last, colorspace)
    res = nuke_client.run(code)
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error", "Nuke run failed")}
    return {"ok": True, "node": res.get("result"), "path": resolved["path"]}
