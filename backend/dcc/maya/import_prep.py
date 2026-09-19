# import_prep.py — backend side of the Maya imports (moved out of routers/dcc.py, V9-08).
#
#   ascii_path            accented folder -> Windows short name (mayaUsd fails on accents)
#   usd_source_for_maya   flatten a USD into one ASCII .usda Maya 2024 can read, proxy removed
#   call_maya_update      run dcc.maya.maya_update.<func> in Maya, read its JSON answer (X4)

from __future__ import annotations

from core.logger import get_logger

log = get_logger("routers.dcc")


def ascii_path(path) -> str | None:
    """*path* with an ASCII folder (Windows short name of an accented folder), file name
    kept, forward slashes. None when no ASCII form exists (8.3 names disabled)."""
    from pathlib import Path as _PLib

    p = _PLib(path)
    text = str(p).replace("\\", "/")
    if text.isascii():
        return text
    if not p.name.isascii():
        return None
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.windll.kernel32.GetShortPathNameW(str(p.parent), buf, 1024)
    except Exception:           # noqa: BLE001 - not Windows
        return None
    short = buf.value if 0 < n < 1024 else ""
    if not short or not short.isascii():
        return None
    return (short.rstrip("\\/") + "/" + p.name).replace("\\", "/")


def usd_source_for_maya(file_path, work_dir: str):
    """Return a USD path Maya's mayaUsd can actually read.

    Maya 2024 ships an older mayaUsd that fails with "Error reading file" on two
    things FLUX produces: binary crates authored by the backend's recent USD, and
    files under an accented path (OneDrive "Projets d'ete"), even for
    a plain ASCII .usda whose sublayers are fine. Flattening the composed stage into a
    self-contained ASCII .usda inside *work_dir* (an ASCII temp dir the caller owns and
    cleans up) avoids both: one file, no sublayer/reference resolution, no accents.
    .usdz packages and unreadable stages are returned unchanged.
    """
    from pathlib import Path as _PLib

    src = _PLib(file_path)
    if src.suffix.lower() == ".usdz":
        return str(src).replace("\\", "/")

    try:
        from pxr import Usd
        stage = Usd.Stage.Open(str(src))
        if stage is None:
            return str(src).replace("\\", "/")
        out = _PLib(work_dir) / (src.stem + ".usda")
        flat = stage.Flatten()
        drop_proxy_prims(flat)
        flat.Export(str(out))
        log.info("[Maya] flattened USD to ASCII for import: %s", src.name)
        return str(out).replace("\\", "/")
    except Exception as exc:
        # Best-effort: if flattening fails, fall back to the original file.
        log.warning("[Maya] USD flatten for import failed for %s: %s", src.name, exc)
        return str(src).replace("\\", "/")


def drop_proxy_prims(layer) -> None:
    """Remove purpose=proxy prims from a flattened layer: Maya has no purpose, so the
    decimated proxy (geo/proxy, ADR 0019) would land as a second visible copy."""
    from pxr import Usd, UsdGeom

    stage = Usd.Stage.Open(layer)
    doomed = [p.GetPath() for p in stage.Traverse()
              if p.IsA(UsdGeom.Imageable)
              and UsdGeom.Imageable(p).GetPurposeAttr().Get() == UsdGeom.Tokens.proxy]
    for path in doomed:
        parent = layer.GetPrimAtPath(path.GetParentPath())
        if parent is not None and path.name in parent.nameChildren:
            del parent.nameChildren[path.name]


def call_maya_update(port: int, func: str, *args: str, timeout: float = 60.0) -> dict | None:
    """Run ``dcc.maya.maya_update.<func>(*args, result_path)`` in Maya, return its JSON.
    Arguments travel as base64 (commandPort decodes with the system locale)."""
    import base64 as _b64
    import json as _json
    import os as _os
    import shutil as _shutil
    import tempfile as _tempfile
    from pathlib import Path as _PLib

    from dcc.maya.maya_connection import send_command_direct

    def _enc(s: str) -> str:
        return _b64.b64encode(s.encode("utf-8")).decode("ascii")

    backend_root = str(_PLib(__file__).resolve().parents[2])
    tmp = _tempfile.mkdtemp(prefix="flux_maya_update_")
    result_path = tmp.replace("\\", "/") + "/result.json"
    decoded = ", ".join(f"_b64.b64decode('{_enc(a)}').decode('utf-8')" for a in (*args, result_path))
    cmd = (f"import sys, base64 as _b64; "
           f"sys.path.insert(0, _b64.b64decode('{_enc(backend_root)}').decode('utf-8')); "
           f"sys.modules.pop('dcc.maya.maya_update', None); "
           f"from dcc.maya import maya_update as _mu; _mu.{func}({decoded})")
    try:
        if send_command_direct(cmd, timeout=timeout, port=port) is None:
            return None
        if not _os.path.exists(result_path):
            return {"ok": False, "error": "Maya n'a rien renvoye"}
        with open(result_path, encoding="utf-8") as fh:
            return _json.load(fh)
    finally:
        _shutil.rmtree(tmp, ignore_errors=True)
