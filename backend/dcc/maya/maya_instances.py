# maya_instances.py — character instances in a Maya scene (U2, 2026-09-24).
#
# A shot scene often holds the same character twice (DINGO_01, DINGO_02). The
# Publisher lists them so the animator ticks which ones to publish: one shot
# animation per instance, exported from the meshes under that instance's top node.
# A top node is an instance of NAME when its namespace or short name starts with
# NAME, or when it is a FLUX import of NAME (flux_source holds "_NAME_").
# Runs inside Maya (Python 3.10) through the commandPort.

from __future__ import annotations

import json
import re

try:
    import maya.cmds as cmds  # type: ignore[import]
except ImportError:
    cmds = None


def instance_number(label: str, name: str) -> int | None:
    """``DINGO_02`` / ``DINGO02`` / ``dingo2:rig`` -> 2, ``DINGO`` -> None."""
    head = label.split(":")[0] if ":" in label else label
    m = re.match(re.escape(name) + r"[_\-]?(\d+)$", head, re.IGNORECASE)
    return int(m.group(1)) if m else None


def number_instances(found: list[dict], name: str) -> list[dict]:
    """Give every entry an ``instance`` number: its own suffix, else the first free one."""
    taken = {n for f in found if (n := instance_number(f["label"], name)) is not None}
    free = (i for i in range(1, 1000) if i not in taken)
    for f in found:
        n = instance_number(f["label"], name)
        f["instance"] = n if n is not None else next(free)
    return sorted(found, key=lambda f: f["instance"])


def _is_import_of(node: str, name: str) -> bool:
    if not cmds.attributeQuery("flux_source", node=node, exists=True):
        return False
    source = str(cmds.getAttr(node + ".flux_source") or "").upper()
    return f"_{name.upper()}_" in source.replace("/", "_").replace(".", "_")


def list_instances(name: str) -> list[dict]:
    """[{"node", "label", "instance", "meshes"}] for the top nodes holding NAME."""
    found: list[dict] = []
    for node in cmds.ls(assemblies=True, long=True) or []:
        short = node.rsplit("|", 1)[-1]
        namespace = short.rsplit(":", 1)[0] if ":" in short else ""
        label = namespace or short
        named = label.upper().startswith(name.upper())
        if not named and not _is_import_of(node, name):
            continue
        meshes = cmds.listRelatives(node, allDescendents=True, type="mesh", fullPath=True) or []
        if not meshes:
            continue
        found.append({"node": node, "label": label, "meshes": len(meshes)})
    return number_instances(found, name)


def run_list_instances(name: str, result_path: str) -> None:
    """commandPort entry: write list_instances(name) to *result_path* (JSON)."""
    try:
        res = {"ok": True, "items": list_instances(name)}
    except Exception as exc:  # noqa: BLE001 - reported to the hub
        res = {"ok": False, "error": repr(exc)}
    with open(result_path, "w", encoding="utf-8") as fh:
        json.dump(res, fh)
