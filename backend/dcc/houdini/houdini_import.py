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
    .fbx                    → KineFX FBX Character Import (SOP; carries boneCapture)

Skinned assets (Maya UsdSkel light export or FBX with skin) can be imported as a
KineFX character via create_character_import_node(): the imported mesh carries the
`boneCapture` point attribute (skin weights), joints matched by name 1:1.
"""

from __future__ import annotations

import re
import shutil
import textwrap
from pathlib import Path


def _node_name_from(file_path: str | Path) -> str:
    """A Houdini-safe node name derived from the imported file's stem."""
    stem = Path(str(file_path)).name
    stem = stem.split(".")[0]  # drop all extensions (e.g. .bgeo.sc)
    safe = re.sub(r"[^A-Za-z0-9_]", "_", stem).strip("_")
    return safe or "import"

from core.logger import get_logger
from dcc.houdini.client import houdini_client

log = get_logger(__name__)

# (node_type, path_parm_name)
_EXT_MAP: dict[str, tuple[str, str]] = {
    ".abc":     ("alembic",                  "fileName"),
    ".usd":     ("usdimport",                "filepath1"),
    ".usda":    ("usdimport",                "filepath1"),
    ".usdc":    ("usdimport",                "filepath1"),
    ".usdz":    ("usdimport",                "filepath1"),
    ".bgeo":    ("file",                     "file"),
    ".bgeo.sc": ("file",                     "file"),
    ".geo":     ("file",                     "file"),
    ".obj":     ("file",                     "file"),
    ".fbx":     ("kinefx::fbxcharacterimport", ""),   # handled via create_character_import_node
}

# Common file-path parm names, tried when the mapped one is absent (version drift).
_FALLBACK_FILE_PARMS = ("filepath1", "filepath", "file", "fileName", "filename", "sopoutput")


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
    if ext == ".fbx":
        # FBX is a KineFX character import (SOP) — routes through the dedicated path,
        # which also yields boneCapture. Fixes the old "not supported" gap.
        return create_character_import_node(network_path, file_path)

    node_type, parm_name = entry
    file_str = str(file_path).replace("\\", "/")
    candidates = repr([parm_name] + list(_FALLBACK_FILE_PARMS))
    node_name = f"flux_import_{_node_name_from(file_path)}"

    # Create the node, then set the file on the first parm that actually exists
    # (parm names drift across Houdini versions, e.g. usdimport -> filepath1).
    code = textwrap.dedent(f"""\
        _net = hou.node({network_path!r})
        if _net is None:
            raise RuntimeError("Network not found: {network_path}")
        _node = _net.createNode({node_type!r}, node_name={node_name!r})
        _set = False
        for _pn in {candidates}:
            if _pn and _node.parm(_pn) is not None:
                _node.parm(_pn).set({file_str!r}); _set = True; break
        _node.setSelected(True, clear_all_selected=True)
        result = {{"ok": True, "node_path": _node.path(), "node_type": {node_type!r}, "file_set": _set}}
    """)

    resp = houdini_client.run(code)
    if resp.get("ok"):
        if (resp.get("result") or {}).get("file_set") is False:
            log.warning("create_import_node: no file parm found on %s for %s", node_type, Path(file_path).name)
        log.info("Created Houdini import node (%s) for %s", node_type, Path(file_path).name)
    else:
        log.error("create_import_node failed: %s", resp.get("error"))
    return resp


def create_character_import_node(network_path: str, file_path: str | Path) -> dict:
    """Import a skinned asset as a KineFX character → mesh carries `boneCapture`.

    ``.usd/.usda/.usdc/.usdz`` → ``kinefx::usdcharacterimport``
    ``.fbx``                   → ``kinefx::fbxcharacterimport``

    These are SOP nodes, so if *network_path* is an OBJ context a Geometry node is
    created to hold the import. The file parameter is discovered at runtime (a file
    string parm, else the first parm whose name contains "file") so it works across
    Houdini versions. Joints map to the skeleton by name 1:1 (UsdSkel / FBX names).

    Returns {"ok", "node_path", "node_type", "file_set", "has_bonecapture",
    "point_count"} or {"ok": False, "error": "..."}.
    """
    ext = _get_ext(file_path)
    if ext in (".usd", ".usda", ".usdc", ".usdz"):
        node_type = "kinefx::usdcharacterimport"
    elif ext == ".fbx":
        node_type = "kinefx::fbxcharacterimport"
    else:
        return {"ok": False, "error": f"Character import needs .usd*/.fbx (got {ext})"}

    file_str = str(file_path).replace("\\", "/")
    code = textwrap.dedent(f"""\
        _net = hou.node({network_path!r})
        if _net is None:
            raise RuntimeError("Network not found: {network_path}")
        # KineFX character import is a SOP — wrap in a Geometry node if needed.
        if _net.childTypeCategory() == hou.objNodeTypeCategory():
            _net = _net.createNode("geo", node_name="flux_character")
        _node = _net.createNode({node_type!r}, node_name="flux_character_import")

        # Find the file parm (version-agnostic): a file-reference string parm first,
        # else the first parm whose name mentions "file".
        _fp = None
        for _p in _node.parms():
            _t = _p.parmTemplate()
            try:
                if (_t.type() == hou.parmTemplateType.String
                        and _t.stringType() == hou.stringParmType.FileReference):
                    _fp = _p; break
            except Exception:
                pass
        if _fp is None:
            for _p in _node.parms():
                if "file" in _p.name().lower():
                    _fp = _p; break
        _set = False
        if _fp is not None:
            _fp.set({file_str!r}); _set = True

        _node.setSelected(True, clear_all_selected=True)

        # Cook and report whether boneCapture landed (so the hub can warn if not).
        _has_bc = False
        _npt = 0
        try:
            _g = _node.geometry()
            if _g is not None:
                _npt = _g.intrinsicValue("pointcount")
                _has_bc = _g.findPointAttrib("boneCapture") is not None
        except Exception:
            pass

        result = {{"ok": True, "node_path": _node.path(), "node_type": {node_type!r},
                   "file_set": _set, "has_bonecapture": _has_bc, "point_count": _npt}}
    """)

    resp = houdini_client.run(code)
    if resp.get("ok"):
        r = resp.get("result") or {}
        if not r.get("file_set"):
            log.warning("create_character_import_node: no file parm found on %s", node_type)
        if not r.get("has_bonecapture"):
            log.warning("create_character_import_node: %s imported but no boneCapture attr (check the asset carries skin weights)", Path(file_path).name)
        log.info("KineFX character import (%s) for %s -> boneCapture=%s, %s pts",
                 node_type, Path(file_path).name, r.get("has_bonecapture"), r.get("point_count"))
    else:
        log.error("create_character_import_node failed: %s", resp.get("error"))
    return resp


def _fallback_node_type(resolved_path: str) -> str:
    """Native Houdini node type to import *resolved_path* when the HDA is missing.

    Empty string when the extension has no native importer (caller then errors).
    """
    entry = _EXT_MAP.get(_get_ext(resolved_path))
    return entry[0] if entry else ""


def create_flux_importer_node(
    project: str = "",
    flux_class: str = "",
    flux_type: str = "",
    flux_name: str = "",
    flux_instance: str = "",
    flux_iter: str = "LAST",
    resolved_path: str = "",
) -> dict:
    """Create a FLUX import node in the active Houdini network pane.

    Prefers the ``flux_importer`` HDA (token-driven, live re-resolve). When that
    node type is not registered in the running Houdini (HDA not built/installed, or
    a stale otls scan), and the backend already resolved a concrete file, it falls
    back to a NATIVE import node (usdimport / alembic / file / kinefx) for that file
    — so "Open in Houdini" works even without the HDA. *resolved_path* is the
    backend-resolved absolute file (see importer_resolve.resolve_import_path).

    Uses the current NetworkEditor pwd(); an OBJ context is wrapped in a Geometry
    node. Returns {"ok": True, "node_path": "...", "resolved_path": "...", "mode": "hda"|"native"}.
    """
    fb_type = _fallback_node_type(resolved_path)
    fb_file = str(resolved_path).replace("\\", "/") if resolved_path else ""
    code = textwrap.dedent(f"""\
        import hou
        import re as _re
        try:
            _pane = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
            _pwd  = _pane.pwd() if _pane else hou.node("/obj")
        except Exception:
            _pwd = hou.node("/obj")
        if _pwd is None:
            _pwd = hou.node("/obj")
        # Node name derived from the import (asset/name), sanitised for Houdini.
        _nm = _re.sub(r"[^A-Za-z0-9_]", "_", ({flux_name!r} or "import").strip()) or "import"
        _cat = _pwd.childTypeCategory()
        # Import into the CURRENT context: /obj → new geo, SOP network → in place.
        # Any other context (e.g. /stage LOP) is incompatible with the SOP importer:
        # raise a clear error and create NO node rather than a node in the wrong place.
        if _cat == hou.objNodeTypeCategory():
            _target = _pwd.createNode("geo", node_name="flux_" + _nm)
        elif _cat == hou.sopNodeTypeCategory():
            _target = _pwd
        else:
            raise RuntimeError(
                "Contexte '" + _pwd.path() + "' incompatible avec l'importer FLUX (SOP). "
                "Place-toi dans /obj ou un réseau SOP (l'import USD /stage arrive bientôt)."
            )

        # Is the flux_importer HDA type actually registered here?
        _hda_type = hou.sopNodeTypeCategory().nodeType("flux_importer")
        _resolved = ""
        _mode = ""
        if _hda_type is not None:
            _node = _target.createNode("flux_importer", node_name="flux_import_" + _nm)
            if {project!r}:       _node.parm("project").set({project!r})
            if {flux_class!r}:    _node.parm("flux_class").set({flux_class!r})
            if {flux_type!r}:     _node.parm("flux_type").set({flux_type!r})
            if {flux_name!r}:     _node.parm("flux_name").set({flux_name!r})
            if {flux_instance!r}: _node.parm("flux_instance").set({flux_instance!r})
            _node.parm("flux_iter").set({flux_iter!r})
            _node.setSelected(True, clear_all_selected=True)
            _mode = "hda"
            # Setting parms via .set() does NOT fire the HDA's resolve callback, and
            # OnCreated only prefetches menus — so resolved_path would stay empty and
            # nothing would import. Trigger the resolve explicitly now.
            try:
                hou.phm().resolve_path(_node)
                _rp = _node.parm("resolved_path")
                _resolved = _rp.eval() if _rp is not None else ""
            except Exception as _re_exc:
                _sm = _node.parm("status_msg")
                if _sm is not None:
                    _sm.set("Resolve auto échoué : clique ↺ Resolve (" + str(_re_exc) + ")")
        else:
            # HDA absent → native fallback on the backend-resolved file.
            if not {fb_file!r}:
                raise RuntimeError(
                    "Le node 'flux_importer' n'existe pas dans ce Houdini (HDA non installée) "
                    "et aucun fichier n'a pu être résolu. Rebuild l'HDA (scripts/build_hdas.py) "
                    "ou réinstalle le shelf Houdini."
                )
            if not {fb_type!r}:
                raise RuntimeError("Extension non supportée par l'import natif : " + {fb_file!r})
            _node = _target.createNode({fb_type!r}, node_name="flux_import_" + _nm)
            # Find the file parm version-agnostically: a FileReference string parm,
            # else the first parm whose name mentions "file".
            _fp = None
            for _p in _node.parms():
                _t = _p.parmTemplate()
                try:
                    if (_t.type() == hou.parmTemplateType.String
                            and _t.stringType() == hou.stringParmType.FileReference):
                        _fp = _p; break
                except Exception:
                    pass
            if _fp is None:
                for _p in _node.parms():
                    if "file" in _p.name().lower():
                        _fp = _p; break
            if _fp is not None:
                _fp.set({fb_file!r})
            _node.setSelected(True, clear_all_selected=True)
            _resolved = {fb_file!r}
            _mode = "native"
        result = {{"ok": True, "node_path": _node.path(), "resolved_path": _resolved, "mode": _mode}}
    """)
    resp = houdini_client.run(code)
    if resp.get("ok"):
        r = resp.get("result") or {}
        if not r.get("resolved_path"):
            log.warning(
                "create_flux_importer_node: node %s created but resolved_path is empty "
                "(check the asset exists for these tokens / FLUX reachable from Houdini)",
                r.get("node_path"),
            )
        log.info("Created FLUX import node at %s (mode=%s, resolved=%s)",
                 r.get("node_path"), r.get("mode"), r.get("resolved_path") or "<none>")
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


def move_to_local(file_path: str | Path, dest_folder: str | Path | None = None) -> dict:
    """Copy *file_path* into a local folder, conflict-safe.

    *dest_folder* : an explicit local directory. When omitted, the copy lands in
    the current Houdini project's ``$HIP/sourceimages/`` (created if needed).
    On a name clash the copy is suffixed ``_1``, ``_2``… (never overwrites).

    Returns {"ok": True, "local_path": "...", "abs_path": "..."} or {"ok": False, "error": "..."}.
    """
    src = Path(file_path)
    if not src.is_file():
        return {"ok": False, "error": f"Fichier introuvable : {src}"}

    rel_prefix: str | None = None
    if dest_folder:
        dest_dir = Path(dest_folder)
    else:
        hip_resp = houdini_client.run("result = hou.hipFile.path()")
        if not hip_resp.get("ok"):
            return {"ok": False, "error": "Impossible de lire $HIP : " + hip_resp.get("error", "inconnu")}
        dest_dir = Path(hip_resp["result"]).parent / "sourceimages"
        rel_prefix = "$HIP/sourceimages"

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"ok": False, "error": f"Dossier local invalide : {exc}"}

    dest = dest_dir / src.name
    if dest.exists():
        stem = src.name.split(".")[0]
        suffix = src.name[len(stem):]   # keeps compound extensions (.bgeo.sc)
        n = 1
        while (dest_dir / f"{stem}_{n}{suffix}").exists():
            n += 1
        dest = dest_dir / f"{stem}_{n}{suffix}"

    try:
        shutil.copy2(src, dest)
    except OSError as exc:
        log.error("move_to_local copy failed: %s", exc)
        return {"ok": False, "error": str(exc)}

    local_path = f"{rel_prefix}/{dest.name}" if rel_prefix else str(dest)
    log.info("Copied %s → %s", src.name, local_path)
    return {"ok": True, "local_path": local_path, "abs_path": str(dest)}
