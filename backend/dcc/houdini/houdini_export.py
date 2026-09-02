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
    "rop_fbx":      "sopoutput",
    "filmboxfbx":   "sopoutput",    # Filmbox FBX ROP (/out)
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

    Single file : dest_folder/basename_<FMT>_LAST/basename_LAST.ext
    Sequence    : dest_folder/basename_v001/basename_v001.$F4.ext

    Returns (output_path, next_version) or (None, None) on failure.
    """
    from features.folder_manager.naming_validator import get_base_name
    from features.publisher.publish_core import resolve_publish_path
    from features.publisher.publish_layout import last_folder
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
        # Single file lands in its own <FMT>/<base>_<FMT>_LAST folder. The folder is
        # created by publish_via_rop AFTER archiving the previous LAST (not here).
        last_dir = last_folder(dest_folder, base_name, ext.lstrip("."))
        output_path = last_dir / f"{base_name}_{ACTIVE_VERSION_LABEL}{ext}"

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
        parm = (resp.get("result") or {}).get("parm")
        log.info("Set ROP output parm '%s' -> %s", parm, out)
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


def export_via_node(
    node_path: str,
    extension: str,
    output_path: str | Path,
    frame_range: tuple[int, int, int] | None = None,
    options: dict | None = None,
    attr_filter: dict | None = None,
) -> dict:
    """Export from ANY selected node: reuse it if it is a ROP, otherwise create the
    right output ROP (rop_geometry for geo/obj/usd, rop_alembic for .abc) as a child of
    the node's SOP network, wire it to the node, set the output path and cook.

    *options* is a {parm_name: value} dict of ROP parameters to apply before the
    cook (see houdiniExportOptions.ts). Each is set only if the parm exists on the
    ROP and never fails the export — an unknown/absent parm is silently skipped.

    *attr_filter* optionally inserts an attribdelete before the ROP to filter point
    attributes: ``{"mode": "keep"|"remove", "names": ["curveu", ...]}``. "keep" keeps
    only the listed point attributes (P is always protected); "remove" deletes them.
    Applies to the SOP-based ROPs (geo/obj/usd/abc); not to the FBX object ROP.

    Returns {"ok": True, "rop": "..."} or {"ok": False, "error": "..."}.
    """
    ext = _norm_ext(extension).lower()
    out = str(output_path).replace("\\", "/")
    fr_repr = repr(tuple(frame_range)) if frame_range else "None"
    rop_map_repr = repr(_ROP_PARM)
    opts_repr = repr(dict(options or {}))
    af_repr = repr(dict(attr_filter or {}))

    code = textwrap.dedent(f"""\
        _n = hou.node({node_path!r})
        if _n is None:
            raise RuntimeError("Node not found: {node_path}")
        _out = {out!r}
        _ext = {ext!r}
        _fr = {fr_repr}
        _ropmap = {rop_map_repr}
        _opts = {opts_repr}
        _af = {af_repr}
        import pathlib as _pl
        _pl.Path(_out).parent.mkdir(parents=True, exist_ok=True)

        _tname = _n.type().name()
        if _tname in _ropmap:
            _rop = _n
            _op = _ropmap[_tname]
        else:
            _cat = _n.type().category().name()
            if _cat == 'Sop':
                _parent, _sop, _objroot = _n.parent(), _n, _n.parent()
            elif _n.childTypeCategory() and _n.childTypeCategory().name() == 'Sop':
                _parent, _sop, _objroot = _n, (_n.renderNode() or _n.displayNode()), _n
            else:
                raise RuntimeError("Select a SOP or a geo object (got %s)" % _cat)
            if _sop is None:
                raise RuntimeError("No SOP to export inside %s" % _n.path())

            # Optional attribute filter: insert an attribdelete on the SOP stream
            # (point attributes) before the ROP. Not applied to the FBX object ROP.
            _tail = _sop
            _af_names = [_x for _x in _af.get('names', []) if _x]
            if _af_names and _ext != '.fbx':
                _adl = _parent.createNode('attribdelete', node_name='flux_attr_filter')
                _adl.setFirstInput(_tail)
                if _af.get('mode') == 'keep':
                    _keep = list(_af_names)
                    if 'P' not in _keep:
                        _keep.append('P')
                    if _adl.parm('negate') is not None:
                        _adl.parm('negate').set(True)
                    if _adl.parm('ptdel') is not None:
                        _adl.parm('ptdel').set(' '.join(_keep))
                else:
                    if _adl.parm('ptdel') is not None:
                        _adl.parm('ptdel').set(' '.join(_af_names))
                _tail = _adl

            if _ext == '.abc':
                _rop = _parent.createNode('rop_alembic', node_name='flux_export'); _op = 'filename'
                for _sp in ('soppath', 'sopname'):
                    if _rop.parm(_sp) is not None:
                        _rop.parm(_sp).set(_tail.path()); break
            elif _ext == '.fbx':
                # FBX is written by the Filmbox ROP in /out, scoped to the geo object
                # root (rop_geometry cannot write FBX). Reuse the node if it exists.
                _rop = hou.node('/out/flux_fbx_export')
                if _rop is None:
                    _rop = hou.node('/out').createNode('filmboxfbx', node_name='flux_fbx_export')
                _op = 'sopoutput'
                for _sp in ('startnode', 'exportnode', 'root'):
                    if _rop.parm(_sp) is not None:
                        _rop.parm(_sp).set(_objroot.path()); break
            else:
                _rop = _parent.createNode('rop_geometry', node_name='flux_export'); _op = 'sopoutput'
                for _sp in ('soppath', 'sopname'):
                    if _rop.parm(_sp) is not None:
                        _rop.parm(_sp).set(_tail.path()); break

        _set = False
        for _pn in (_op, 'sopoutput', 'filename', 'lopoutput', 'file', 'picture'):
            if _pn and _rop.parm(_pn) is not None:
                _rop.parm(_pn).set(_out); _set = True; break
        if not _set:
            raise RuntimeError("Cannot set output parm on ROP type: %s" % _rop.type().name())

        # Apply per-format ROP options defensively (skip absent parms / bad values).
        for _k, _v in _opts.items():
            _p = _rop.parm(_k)
            if _p is not None:
                try:
                    _p.set(_v)
                except Exception:
                    pass

        if _fr:
            _rop.render(frame_range=_fr)
        else:
            _rop.render()
        result = {{"ok": True, "rop": _rop.path()}}
    """)

    resp = houdini_client.run(code)
    if resp.get("ok"):
        rop = (resp.get("result") or {}).get("rop")
        log.info("Houdini export via node %s -> %s (%s)", node_path, out, rop)
    else:
        log.error("export_via_node failed: %s", resp.get("error"))
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
    options: dict | None = None,
    attr_filter: dict | None = None,
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
    from features.publisher.publish_core import resolve_publish_path
    from features.publisher.publish_layout import archive_last_folder, format_suffix
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

    # 3. For single files: archive the previous LAST folder before the cook writes
    #    the new one, then (re)create the empty LAST folder the ROP will render into.
    if not is_sequence:
        full_name = f"{filename}{ext}"
        dest_folder = resolve_publish_path(project_path, full_name)
        base_name = get_base_name(full_name)
        fmt = format_suffix(ext)
        archived = archive_last_folder(dest_folder, base_name, fmt, ext)
        effective_ver = archived + 1 if archived is not None else next_ver
        ensure_dir(output_path.parent)  # the <base>_<FMT>_LAST folder
    else:
        effective_ver = next_ver

    # 4+5. Export: reuse the node if it is a ROP, else auto-create the right output ROP
    # as a child, wire it, set the path and cook — so any selected node can be exported.
    exp_resp = export_via_node(rop_node_path, ext, output_path, frame_range, options, attr_filter)
    if not exp_resp.get("ok"):
        return {"ok": False, "error": "export: " + exp_resp.get("error", "unknown")}

    # 6. Log
    ver_str = format_version(effective_ver, DEFAULT_PADDING)
    try:
        log_publish(user or "unknown", output_path.name, project_path.name, dest_folder=output_path.parent)
        from features.publisher.modif_log import append_log
        if not is_sequence:
            # modif log stays in the shared publish folder (spans all versions/formats)
            append_log(dest_folder, get_base_name(f"{filename}{ext}"), ver_str, description, user)
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
