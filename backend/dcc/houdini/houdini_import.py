"""
FLUX — Houdini import helpers.
Builds hou.* code strings and dispatches them to a running Houdini instance
via HoudiniClient.run().  No hou import required on this side.

Token path resolution stays in features/folder_manager/tokens.py — callers
are responsible for passing an already-resolved absolute file path.

Supported import extensions:
    .abc                    → Alembic SOP
    .usd / .usda / .usdc    → USD Import SOP
    .bgeo / .bgeo.sc / .geo / .obj  → File SOP
    .fbx                    → FBX Character Import (OBJ-level — network_path must be /obj)
"""

from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

from core.logger import get_logger
from dcc.houdini.client import houdini_client

log = get_logger(__name__)

# (node_type, path_parm_name)
_EXT_MAP: dict[str, tuple[str, str]] = {
    ".abc":     ("alembic",                  "fileName"),
    ".usd":     ("usdimport",                "filepath"),
    ".usda":    ("usdimport",                "filepath"),
    ".usdc":    ("usdimport",                "filepath"),
    ".usdz":    ("usdimport",                "filepath"),
    ".bgeo":    ("file",                     "file"),
    ".bgeo.sc": ("file",                     "file"),
    ".geo":     ("file",                     "file"),
    ".obj":     ("file",                     "file"),
    ".fbx":     ("filmboxcharacterimport",   ""),
}


def _get_ext(file_path: str | Path) -> str:
    s = str(file_path)
    if s.endswith(".bgeo.sc"):
        return ".bgeo.sc"
    return Path(s).suffix.lower()


def create_import_node(network_path: str, file_path: str | Path) -> dict:
    """Create a Houdini import node in *network_path* for *file_path*.

    The node type is selected automatically from the file extension.
    *network_path* example: "/obj/geo1" for SOP context, "/obj" for FBX.

    Returns {"ok": True, "node_path": "...", "node_type": "..."} or {"ok": False, "error": "..."}.
    """
    ext = _get_ext(file_path)
    entry = _EXT_MAP.get(ext)
    if entry is None:
        return {"ok": False, "error": f"Unsupported import extension: {ext}"}

    node_type, parm_name = entry
    file_str = str(file_path).replace("\\", "/")

    if parm_name:
        code = textwrap.dedent(f"""\
            _net = hou.node({network_path!r})
            if _net is None:
                raise RuntimeError("Network not found: {network_path}")
            _node = _net.createNode({node_type!r}, node_name="flux_import")
            _node.parm({parm_name!r}).set({file_str!r})
            _node.setSelected(True, clear_all_selected=True)
            result = {{"ok": True, "node_path": _node.path(), "node_type": {node_type!r}}}
        """)
    else:
        # FBX: no single path parm — set fileName after creation
        code = textwrap.dedent(f"""\
            _net = hou.node({network_path!r})
            if _net is None:
                raise RuntimeError("Network not found: {network_path}")
            _node = _net.createNode({node_type!r}, node_name="flux_import")
            try:
                _node.parm("fileName").set({file_str!r})
            except AttributeError:
                pass
            _node.setSelected(True, clear_all_selected=True)
            result = {{"ok": True, "node_path": _node.path(), "node_type": {node_type!r}}}
        """)

    resp = houdini_client.run(code)
    if resp.get("ok"):
        log.info("Created Houdini import node (%s) for %s", node_type, Path(file_path).name)
    else:
        log.error("create_import_node failed: %s", resp.get("error"))
    return resp


def create_flux_importer_node(
    project: str = "",
    flux_class: str = "",
    flux_type: str = "",
    flux_name: str = "",
    flux_instance: str = "",
    flux_iter: str = "LAST",
) -> dict:
    """Create a flux_importer HDA node in the active Houdini network pane.

    Uses the current NetworkEditor pwd(). If that's an OBJ context, wraps inside
    a new Geometry node. Returns {"ok": True, "node_path": "..."}.
    """
    code = textwrap.dedent(f"""\
        import hou
        try:
            _pane = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
            _pwd  = _pane.pwd() if _pane else hou.node("/obj")
        except Exception:
            _pwd = hou.node("/obj")
        if _pwd is None:
            _pwd = hou.node("/obj")
        _cat = _pwd.childTypeCategory()
        if _cat == hou.objNodeTypeCategory():
            _geo = _pwd.createNode("geo", node_name="flux_geo")
            _target = _geo
        elif _cat == hou.sopNodeTypeCategory():
            _target = _pwd
        else:
            _geo = hou.node("/obj").createNode("geo", node_name="flux_geo")
            _target = _geo
        _node = _target.createNode("flux_importer", node_name="flux_import")
        if {project!r}:       _node.parm("project").set({project!r})
        if {flux_class!r}:    _node.parm("flux_class").set({flux_class!r})
        if {flux_type!r}:     _node.parm("flux_type").set({flux_type!r})
        if {flux_name!r}:     _node.parm("flux_name").set({flux_name!r})
        if {flux_instance!r}: _node.parm("flux_instance").set({flux_instance!r})
        _node.parm("flux_iter").set({flux_iter!r})
        _node.setSelected(True, clear_all_selected=True)
        result = {{"ok": True, "node_path": _node.path()}}
    """)
    resp = houdini_client.run(code)
    if resp.get("ok"):
        log.info("Created flux_importer node at %s", resp.get("result", {}).get("node_path"))
    else:
        log.error("create_flux_importer_node failed: %s", resp.get("error"))
    return resp


def set_import_path(node_path: str, file_path: str | Path) -> dict:
    """Update the file path parameter on an existing Houdini import node.

    The correct parameter name is inferred from the file extension.
    Returns {"ok": True} or {"ok": False, "error": "..."}.
    """
    ext = _get_ext(file_path)
    entry = _EXT_MAP.get(ext)
    if entry is None:
        return {"ok": False, "error": f"Unsupported import extension: {ext}"}

    _, parm_name = entry
    if not parm_name:
        parm_name = "fileName"  # FBX fallback

    file_str = str(file_path).replace("\\", "/")
    code = textwrap.dedent(f"""\
        _node = hou.node({node_path!r})
        if _node is None:
            raise RuntimeError("Node not found: {node_path}")
        _node.parm({parm_name!r}).set({file_str!r})
        result = {{"ok": True, "node_path": {node_path!r}}}
    """)

    resp = houdini_client.run(code)
    if resp.get("ok"):
        log.info("Updated import path on %s → %s", node_path, Path(file_path).name)
    else:
        log.error("set_import_path failed: %s", resp.get("error"))
    return resp


def move_to_local(file_path: str | Path) -> dict:
    """Copy *file_path* into the current Houdini project directory ($HIP).

    The copy lands at $HIP/sourceimages/<filename> (created if needed).
    Returns {"ok": True, "local_path": "$HIP/sourceimages/...", "abs_path": "..."} or {"ok": False, ...}.
    """
    hip_resp = houdini_client.run("result = hou.hipFile.path()")
    if not hip_resp.get("ok"):
        return {"ok": False, "error": "Could not get $HIP: " + hip_resp.get("error", "unknown")}

    hip_path = Path(hip_resp["result"]).parent
    src = Path(file_path)

    dest_dir = hip_path / "sourceimages"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name

    try:
        shutil.copy2(src, dest)
    except OSError as exc:
        log.error("move_to_local copy failed: %s", exc)
        return {"ok": False, "error": str(exc)}

    rel = f"$HIP/sourceimages/{src.name}"
    log.info("Copied %s → %s", src.name, rel)
    return {"ok": True, "local_path": rel, "abs_path": str(dest)}
