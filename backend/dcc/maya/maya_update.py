# maya_update.py — follow LAST in Maya (X4, ADR 0017, V9-06).
#
# Every import made by FLUX tags its top nodes with where it came from:
#   flux_project  project name          flux_source  project-relative published file
#   flux_stamp    state of that file    flux_mode    "import" (flattened copy) | "proxy"
# The shelf button "MAJ" asks the hub to compare the tags with the published files and
# to replace the imports whose LAST moved on, keeping the artist's transform and parent.
# Runs inside Maya (Python 3.10); the hub drives it through the commandPort, the shelf
# button calls the hub over HTTP from a thread (the hub talks back to this Maya).

from __future__ import annotations

import json

from core.logger import get_logger

log = get_logger(__name__)

try:
    import maya.cmds as cmds  # type: ignore[import]
    _IN_MAYA = True
except ImportError:
    cmds = None
    _IN_MAYA = False

TAG_ATTRS = ("flux_project", "flux_source", "flux_stamp", "flux_mode")


def top_nodes(nodes: list[str]) -> list[str]:
    """The top DAG transforms among *nodes* (what an import added at the scene root)."""
    if not nodes:
        return []
    return [n for n in (cmds.ls(nodes, assemblies=True, long=True) or [])
            if cmds.nodeType(n) == "transform"]


def write_tag(node: str, tag: dict) -> None:
    for attr in TAG_ATTRS:
        value = str(tag.get(attr.replace("flux_", ""), ""))
        if not cmds.attributeQuery(attr, node=node, exists=True):
            cmds.addAttr(node, longName=attr, dataType="string")
        cmds.setAttr(f"{node}.{attr}", value, type="string")


def tag_nodes(nodes: list[str], tag: dict) -> list[str]:
    """Write the FLUX tag on the top nodes of an import. Returns the tagged nodes."""
    tops = top_nodes(nodes)
    for node in tops:
        write_tag(node, tag)
    return tops


def list_tagged() -> list[dict]:
    """[{"node", "project", "source", "stamp", "mode"}] of every tagged node of the scene."""
    out = []
    for node in cmds.ls("*.flux_source", objectsOnly=True, long=True, recursive=True) or []:
        item = {"node": node}
        for attr in TAG_ATTRS:
            try:
                item[attr.replace("flux_", "")] = cmds.getAttr(f"{node}.{attr}") or ""
            except Exception:
                item[attr.replace("flux_", "")] = ""
        out.append(item)
    return out


def replace_import(node: str, file_path: str, tag: dict) -> dict:
    """Re-import *file_path* in place of *node*: same parent, same local matrix, new tag.
    A proxy shape only re-reads its file. Returns {"ok", "nodes"} or {"ok": False, "error"}."""
    if not cmds.objExists(node):
        return {"ok": False, "error": f"{node} n'existe plus"}
    if tag.get("mode") == "proxy":
        shapes = cmds.listRelatives(node, shapes=True, type="mayaUsdProxyShape", fullPath=True) or []
        for shape in shapes:
            path = cmds.getAttr(f"{shape}.filePath")
            cmds.setAttr(f"{shape}.filePath", "", type="string")
            cmds.setAttr(f"{shape}.filePath", path, type="string")
        write_tag(node, tag)
        return {"ok": True, "nodes": [node]}

    from dcc.maya.maya_import import import_file

    short = node.rsplit("|", 1)[-1]
    parent = (cmds.listRelatives(node, parent=True, fullPath=True) or [None])[0]
    matrix = cmds.xform(node, query=True, matrix=True, objectSpace=True)
    visible = cmds.getAttr(f"{node}.visibility")
    new_nodes = import_file(file_path)
    if new_nodes is None:
        return {"ok": False, "error": f"import de {file_path} echoue"}
    tops = top_nodes(new_nodes)
    placed = []
    for top in tops:
        if parent:
            top = cmds.parent(top, parent)[0]
        cmds.xform(top, matrix=matrix, objectSpace=True)
        cmds.setAttr(f"{top}.visibility", visible)
        placed.append(cmds.ls(top, long=True)[0])
    cmds.delete(node)
    if len(placed) == 1:
        # The new import takes the old name back (scripts and constraints look for it).
        placed = [cmds.ls(cmds.rename(placed[0], short), long=True)[0]]
    for top in placed:
        write_tag(top, tag)
    log.info("FLUX import mis a jour : %s -> %s", node, placed)
    return {"ok": True, "nodes": placed}


def run_list(result_path: str) -> None:
    """commandPort entry: write the tagged imports to *result_path* (JSON)."""
    with open(result_path, "w", encoding="utf-8") as fh:
        json.dump({"ok": True, "items": list_tagged()}, fh)


def run_replace(node: str, file_path: str, tag_json: str, result_path: str) -> None:
    """commandPort entry: replace one import, write the outcome to *result_path*."""
    try:
        res = replace_import(node, file_path, json.loads(tag_json))
    except Exception as exc:  # noqa: BLE001 - reported to the hub
        res = {"ok": False, "error": repr(exc)}
    with open(result_path, "w", encoding="utf-8") as fh:
        json.dump(res, fh)


def _own_port() -> int | None:
    for name in cmds.commandPort(query=True, listPorts=True) or []:
        tail = str(name).rsplit(":", 1)[-1]
        if tail.isdigit():
            return int(tail)
    return None


def update_imports() -> None:
    """Shelf button "MAJ": ask the hub to bring every FLUX import of the scene to LAST.

    The HTTP call runs in a thread: the hub drives this Maya through its commandPort,
    which only runs while the main thread is free."""
    import os
    import threading
    import urllib.request

    import maya.utils  # type: ignore[import]

    try:
        hub = int(os.environ.get("FLUX_PORT") or
                  open(os.path.join(os.environ.get("APPDATA", ""), "FLUX", "backend_port")).read())
    except Exception:
        hub = 8765
    payload = json.dumps({"port": _own_port()}).encode()

    def _show(msg: str) -> None:
        cmds.inViewMessage(amg=msg, pos="topCenter", fade=True, fadeStayTime=4000)
        print("FLUX : " + msg)

    def _work() -> None:
        req = urllib.request.Request(f"http://localhost:{hub}/dcc/maya/update-imports", data=payload,
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                res = json.loads(r.read())
            msg = res.get("message") or "Imports FLUX verifies"
        except Exception as exc:
            msg = f"MAJ imports FLUX impossible : {exc}"
        maya.utils.executeDeferred(_show, msg)

    _show("verification des imports...")
    threading.Thread(target=_work, daemon=True).start()
