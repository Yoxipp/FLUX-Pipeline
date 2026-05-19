"""
FLUX — Houdini export helpers.
Builds hou.* code strings and dispatches them to a running Houdini instance
via HoudiniClient.run().  No hou import required on this side.

Two usage modes:
  1. Programmatic export  — export_geo() / export_scene()
     Creates a temp ROP or uses geometry.saveToFile(). Useful for quick exports.

  2. ROP publish workflow — publish_houdini_rop()
     Builds a versioned pipeline path from tokens, sets it on the user's selected
     ROP node, triggers the cook, and archives the previous version.
     Reuses publish_core / version_resolver — no duplication.

Supported formats:
    Geometry  : .bgeo  .bgeo.sc  .geo  .obj  .abc
    Scene     : .hip  .hiplc  .hipnc
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from core.constants import ACTIVE_VERSION_LABEL, DEFAULT_PADDING
from core.logger import get_logger
from core.paths import ensure_dir
from dcc.houdini.client import houdini_client

log = get_logger(__name__)

_GEO_NATIVE_EXTS: frozenset[str] = frozenset({".bgeo", ".bgeo.sc", ".geo", ".obj"})
_SCENE_EXTS:      frozenset[str] = frozenset({".hip", ".hiplc", ".hipnc"})

# Houdini ROP node type → output path parameter name
_ROP_PARM: dict[str, str] = {
    "rop_geometry": "sopoutput",
    "alembic":      "filename",
    "rop_alembic":  "filename",
    "usdexport":    "lopoutput",
    "ifd":          "vm_picture",   # Mantra
    "karma":        "picture",
    "karma_old":    "picture",
    "opengl":       "picture",
    "rop_comp":     "copoutput",
    "filmboxcharacterimport": "fileName",
}
# Tried in order when node type is not in _ROP_PARM
_FALLBACK_PARMS = ("sopoutput", "filename", "picture", "vm_picture", "lopoutput", "fileName")

FRAME_PADDING = 4  # $F4 → 0001, 0002 …


def _norm_ext(extension: str) -> str:
    return extension if extension.startswith(".") else f".{extension}"


# ── Programmatic export ────────────────────────────────────────────────────────

def export_geo(node_path: str, file_path: str | Path, extension: str) -> dict:
    """Export geometry from a Houdini SOP node to disk.

    Supported extensions: .bgeo  .bgeo.sc  .geo  .obj  .abc
    Returns {"ok": True, "path": "..."} or {"ok": False, "error": "..."}.
    """
    ext = _norm_ext(extension).lower()
    out = str(Path(file_path).with_suffix(ext)).replace("\\", "/")

    if ext in _GEO_NATIVE_EXTS:
        code = textwrap.dedent(f"""\
            import pathlib
            _out = {out!r}
            pathlib.Path(_out).parent.mkdir(parents=True, exist_ok=True)
            _node = hou.node({node_path!r})
            if _node is None:
                raise RuntimeError("Node not found: {node_path}")
            _geo = _node.geometry()
            if _geo is None:
                raise RuntimeError("No geometry on node: {node_path}")
            _geo.saveToFile(_out)
            result = {{"ok": True, "path": _out}}
        """)

    elif ext == ".abc":
        # Temporary Alembic ROP — created in /out, cooked, destroyed.
        code = textwrap.dedent(f"""\
            import pathlib
            _out = {out!r}
            pathlib.Path(_out).parent.mkdir(parents=True, exist_ok=True)
            _node = hou.node({node_path!r})
            if _node is None:
                raise RuntimeError("Node not found: {node_path}")
            _obj = _node if _node.childTypeCategory() == hou.objNodeTypeCategory() else _node.parent()
            _rop = hou.node("/out").createNode("alembic")
            try:
                _rop.parm("filename").set(_out)
                _rop.parm("root").set(_obj.path())
                _rop.parm("objects").set(_obj.path())
                _rop.render()
                result = {{"ok": True, "path": _out}}
            finally:
                _rop.destroy()
        """)

    else:
        return {"ok": False, "error": f"Unsupported geometry extension: {ext}"}

    resp = houdini_client.run(code)
    if resp.get("ok"):
        log.info("Houdini geo export → %s", out)
    else:
        log.error("Houdini geo export failed: %s", resp.get("error"))
    return resp


def export_scene(file_path: str | Path, extension: str = ".hip") -> dict:
    """Save the current Houdini scene to disk.

    Supported extensions: .hip  .hiplc  .hipnc
    Returns {"ok": True, "path": "..."} or {"ok": False, "error": "..."}.
    """
    ext = _norm_ext(extension).lower()
    if ext not in _SCENE_EXTS:
        return {"ok": False, "error": f"Unsupported scene extension: {ext}"}

    out = str(Path(file_path).with_suffix(ext)).replace("\\", "/")
    code = textwrap.dedent(f"""\
        import pathlib
        _out = {out!r}
        pathlib.Path(_out).parent.mkdir(parents=True, exist_ok=True)
        hou.hipFile.save(_out)
        result = {{"ok": True, "path": _out}}
    """)

    resp = houdini_client.run(code)
    if resp.get("ok"):
        log.info("Houdini scene saved → %s", out)
    else:
        log.error("Houdini scene save failed: %s", resp.get("error"))
    return resp


# ── ROP publish workflow ───────────────────────────────────────────────────────

def build_rop_output_path(
    project_path: Path | str,
    filename: str,
    extension: str,
    is_sequence: bool = False,
    frame_padding: int = FRAME_PADDING,
) -> tuple[Path, int] | tuple[None, None]:
    """Build the versioned output path to set on a Houdini ROP.

    Reuses resolve_publish_path (tokens) + get_next_version (version_resolver).
    No duplication with publish_core.

    Single file : dest_folder/basename_LAST.ext
    Sequence    : dest_folder/basename_v001/basename_v001.$F4.ext

    Returns (output_path, next_version) or (None, None) on failure.
    """
    from features.folder_manager.naming_validator import get_base_name
    from features.publisher.publish_core import resolve_publish_path
    from features.publisher.version_resolver import get_next_version

    project_path = Path(project_path)
    ext = _norm_ext(extension)
    full_name = f"{filename}{ext}"

    dest_folder = resolve_publish_path(project_path, full_name)
    if dest_folder is None:
        log.error("Cannot resolve publish path for: %s", full_name)
        return None, None

    ensure_dir(dest_folder)
    base_name = get_base_name(full_name)
    next_ver = get_next_version(dest_folder, base_name)

    if is_sequence:
        ver_str = f"v{next_ver:0{DEFAULT_PADDING}d}"
        seq_folder = dest_folder / f"{base_name}_{ver_str}"
        ensure_dir(seq_folder)
        frame_token = f"$F{frame_padding}"
        output_path = seq_folder / f"{base_name}_{ver_str}.{frame_token}{ext}"
    else:
        output_path = dest_folder / f"{base_name}_{ACTIVE_VERSION_LABEL}{ext}"

    return output_path, next_ver


def set_rop_output(rop_node_path: str, output_path: str | Path) -> dict:
    """Set the output path parameter on an existing Houdini ROP node.

    Auto-detects the correct parameter name from the node type.
    Falls back to trying common parameter names if type is unknown.
    Returns {"ok": True, "parm": "...", "path": "..."} or {"ok": False, "error": "..."}.
    """
    out = str(output_path).replace("\\", "/")
    parm_map_repr = repr(_ROP_PARM)
    fallback_repr = repr(_FALLBACK_PARMS)

    code = textwrap.dedent(f"""\
        _node = hou.node({rop_node_path!r})
        if _node is None:
            raise RuntimeError("ROP node not found: {rop_node_path}")
        _type = _node.type().name()
        _parm_map = {parm_map_repr}
        _fallback = {fallback_repr}
        _parm_name = _parm_map.get(_type)
        if _parm_name is None:
            for _p in _fallback:
                if _node.parm(_p) is not None:
                    _parm_name = _p
                    break
        if _parm_name is None:
            raise RuntimeError(f"Cannot detect output parm on ROP type: {{_type}}")
        _node.parm(_parm_name).set({out!r})
        result = {{"ok": True, "parm": _parm_name, "node_type": _type, "path": {out!r}}}
    """)

    resp = houdini_client.run(code)
    if resp.get("ok"):
        log.info("Set ROP output parm '%s' → %s", resp.get("parm"), out)
    else:
        log.error("set_rop_output failed: %s", resp.get("error"))
    return resp


def cook_rop(
    rop_node_path: str,
    frame_range: tuple[int, int, int] | None = None,
) -> dict:
    """Trigger a Houdini ROP cook.

    frame_range: (start, end, step) — uses ROP's own frame range when None.
    Returns {"ok": True} or {"ok": False, "error": "..."}.
    """
    if frame_range is not None:
        fr_repr = repr(frame_range)
        code = textwrap.dedent(f"""\
            _node = hou.node({rop_node_path!r})
            if _node is None:
                raise RuntimeError("ROP node not found: {rop_node_path}")
            _node.render(frame_range={fr_repr})
            result = {{"ok": True}}
        """)
    else:
        code = textwrap.dedent(f"""\
            _node = hou.node({rop_node_path!r})
            if _node is None:
                raise RuntimeError("ROP node not found: {rop_node_path}")
            _node.render()
            result = {{"ok": True}}
        """)

    resp = houdini_client.run(code)
    if resp.get("ok"):
        log.info("ROP cook complete: %s", rop_node_path)
    else:
        log.error("cook_rop failed: %s", resp.get("error"))
    return resp


def publish_houdini_rop(
    project_path: Path | str,
    filename: str,
    extension: str,
    rop_node_path: str | None = None,
    is_sequence: bool = False,
    frame_range: tuple[int, int, int] | None = None,
    frame_padding: int = FRAME_PADDING,
    description: str = "",
    user: str = "",
) -> dict:
    """Full Houdini publish workflow via a ROP node.

    1. Get selected ROP if rop_node_path is None
    2. Build versioned output path (reuses publish_core + version_resolver)
    3. Archive existing LAST → vXXX  (single file only)
    4. Set output path on the ROP
    5. Cook the ROP
    6. Log publish activity

    Returns {"ok": True, "path": "...", "version": N} or {"ok": False, "error": "..."}.
    """
    from features.activity.activity_writer import log_publish
    from features.publisher.publish_core import rename_last_to_versioned, resolve_publish_path
    from features.publisher.version_resolver import get_next_version
    from features.folder_manager.naming_validator import get_base_name, format_version

    project_path = Path(project_path)
    ext = _norm_ext(extension)

    # 1. Resolve ROP node path — use first selected node in Houdini if not provided
    if rop_node_path is None:
        state = houdini_client.state()
        selected = state.get("selected_nodes", [])
        if not selected:
            return {"ok": False, "error": "No ROP node selected in Houdini"}
        rop_node_path = selected[0]

    # 2. Build output path
    output_path, next_ver = build_rop_output_path(
        project_path, filename, extension, is_sequence, frame_padding
    )
    if output_path is None:
        return {"ok": False, "error": f"Cannot resolve pipeline path for: {filename}{ext}"}

    # 3. For single files: archive existing LAST before cook overwrites it
    if not is_sequence:
        full_name = f"{filename}{ext}"
        dest_folder = resolve_publish_path(project_path, full_name)
        base_name = get_base_name(full_name)
        had_last = rename_last_to_versioned(dest_folder, base_name, next_ver) is not None
        effective_ver = next_ver + 1 if had_last else next_ver
    else:
        effective_ver = next_ver

    # 4. Set output path on the ROP
    set_resp = set_rop_output(rop_node_path, output_path)
    if not set_resp.get("ok"):
        return {"ok": False, "error": "set_rop_output: " + set_resp.get("error", "unknown")}

    # 5. Cook
    cook_resp = cook_rop(rop_node_path, frame_range)
    if not cook_resp.get("ok"):
        return {"ok": False, "error": "cook_rop: " + cook_resp.get("error", "unknown")}

    # 6. Log
    ver_str = format_version(effective_ver, DEFAULT_PADDING)
    try:
        log_publish(user or "unknown", output_path.name, project_path.name)
        from features.publisher.modif_log import append_log
        if not is_sequence:
            append_log(output_path.parent, get_base_name(f"{filename}{ext}"), ver_str, description, user)
    except Exception as exc:
        log.warning("Logging failed (non-fatal): %s", exc)

    log.info("Houdini publish complete → %s (v%s)", output_path.name, ver_str)
    return {
        "ok": True,
        "path": str(output_path),
        "version": effective_ver,
        "version_str": ver_str,
        "rop_node": rop_node_path,
        "is_sequence": is_sequence,
    }
