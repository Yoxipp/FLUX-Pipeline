# maya_layout.py — read assembly placements from the open Maya scene for
# features.usd_assembler.layout_publish (USD_ASSEMBLER_V2 section 10 point 3).
#
# Two halves: run_collect() executes INSIDE Maya (maya.cmds) and writes a JSON
# envelope; collect_layout() runs in the hub and drives it over the commandPort.
# The assembly is expected as imported by FLUX: transforms |<ASM>|<CLASS>|<INSTANCE>.

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)

_BACKEND_ROOT = str(Path(__file__).resolve().parent.parent.parent)


def _short(node: str) -> str:
    return node.rsplit("|", 1)[-1].rsplit(":", 1)[-1]


def collect_in_maya(name: str) -> dict:
    """{"placements": {"CLASS/INSTANCE": [16 floats]}, "root"} (inside Maya)."""
    import maya.cmds as cmds

    roots = cmds.ls(name, f"*:{name}", type="transform", long=True) or []
    if not roots:
        raise RuntimeError(f"Assembly {name} absente de la scene Maya : importe l'assembly avant de publier le layout.")
    root = min(roots, key=lambda n: n.count("|"))
    placements: dict[str, list[float]] = {}
    for group in cmds.listRelatives(root, children=True, fullPath=True, type="transform") or []:
        for inst in cmds.listRelatives(group, children=True, fullPath=True, type="transform") or []:
            matrix = cmds.xform(inst, query=True, matrix=True, objectSpace=True)
            placements[f"{_short(group)}/{_short(inst)}"] = [float(v) for v in matrix]
    return {"placements": placements, "root": root}


def run_collect(name: str, result_path: str) -> None:
    """Inside Maya: collect and write {ok, result | error} to *result_path*."""
    try:
        envelope = {"ok": True, "result": collect_in_maya(name)}
    except Exception as exc:
        envelope = {"ok": False, "error": str(exc)}
    with open(result_path, "w", encoding="utf-8") as fh:
        json.dump(envelope, fh)


def collect_layout(name: str, *, port: int | None = None, timeout: float = 30.0) -> dict:
    """Hub side: {"ok", "result": {"placements", "root"}} or {"ok": False, "error"}."""
    from core.constants import DCC_PORTS
    from dcc.maya.maya_connection import send_command_direct

    result_path = Path(tempfile.gettempdir()) / f"flux_maya_layout_{uuid.uuid4().hex}.json"
    res_fwd = str(result_path).replace("\\", "/")
    cmd = (
        f"import sys; sys.path.insert(0, r'{_BACKEND_ROOT}'); "
        f"sys.modules.pop('dcc.maya.maya_layout', None); "
        f"from dcc.maya.maya_layout import run_collect; run_collect({name!r}, r'{res_fwd}')"
    )
    try:
        if send_command_direct(cmd, timeout=timeout, port=port or DCC_PORTS["Maya"]) is None:
            return {"ok": False, "error": "Maya ne repond pas sur le commandPort"}
        if not result_path.is_file():
            return {"ok": False, "error": "Maya n'a pas renvoye de placements"}
        resp = json.loads(result_path.read_text(encoding="utf-8"))
    finally:
        result_path.unlink(missing_ok=True)
    if resp.get("ok"):
        log.info("Maya layout %s: %d placements from %s", name,
                 len(resp["result"].get("placements") or {}), resp["result"].get("root"))
    else:
        log.error("collect_layout (Maya) failed: %s", resp.get("error"))
    return resp
