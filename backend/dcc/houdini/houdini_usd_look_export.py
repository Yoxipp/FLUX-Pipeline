"""
FLUX - Houdini look USD export glue (Solaris).

Houdini writes its LOP stage (Material Library + assignments) to a throwaway USD with a
USD ROP; the FLUX backend rewrites it into the look department layer with pxr
(features/usd_export/look_export.py, ADR 0019 A1b).

Same split as the light export: Houdini only writes a file (no pxr Python from Houdini
is ever used by FLUX), the backend authors what gets published.
"""

from __future__ import annotations

import tempfile
import textwrap
from pathlib import Path

from core.logger import get_logger
from dcc.houdini.client import houdini_client

log = get_logger(__name__)

# Runs inside Houdini: writes the chosen LOP stage to _OUT with a usd_rop and assigns
# {"usd": path} to `result` (or {"__error__": msg}).
_EXPORT_CODE = textwrap.dedent(r'''
    import hou

    _LOP = {lop!r}
    _OUT = {out!r}
    _logs = []

    def _log(level, msg):
        _logs.append({{"level": level, "msg": msg}})

    def _pick_lop():
        if _LOP:
            node = hou.node(_LOP)
            if node is None:
                return None, "node LOP introuvable : %s" % _LOP
            return node, None
        stage = hou.node("/stage")
        if stage is None:
            return None, "pas de contexte /stage dans cette scene"
        node = stage.displayNode()
        if node is None:
            return None, "aucun node affiche dans /stage : selectionne le LOP a publier"
        return node, None

    result = None
    try:
        node, err = _pick_lop()
        if err:
            result = {{"__error__": err, "__logs__": _logs}}
        else:
            parent = node.parent()
            rop = parent.node("flux_look_export")
            if rop is not None:
                rop.destroy()                     # leftover of a crashed run
            rop = parent.createNode("usd_rop", "flux_look_export")
            def _set(name, value):
                parm = rop.parm(name)
                if parm is not None:
                    parm.set(value)
                else:
                    _log("WARNING", "parametre %s absent du usd_rop" % name)

            _set("lopoutput", _OUT)
            # Absolute paths in a throwaway file: the backend rewrites them anyway.
            _set("enableoutputprocessor_simplerelativepaths", 0)
            # One self-contained file: the backend reads it once and throws it away.
            _set("savestyle", "flattenstage")
            rop.setInput(0, node)
            try:
                rop.render()
            finally:
                rop.destroy()                     # the artist's scene stays as it was
            _log("INFO", "look ecrit depuis %s" % node.path())
            result = {{"usd": _OUT, "__logs__": _logs}}
    except Exception as exc:
        result = {{"__error__": "export look: %s" % exc, "__logs__": _logs}}
''')


def run_look_export(project_path: str, *, lop_node: str | None = None, fmt: str = "usda",
                    dest_dir: str | None = None, base_name: str | None = None,
                    user: str = "") -> dict:
    """Export the materials of a Houdini LOP stage and publish them as the look layer.

    Returns {"ok": True, "version": "vNNN", "root": "...", "materials": n, "bindings": n}
    or {"ok": False, "error": "..."}.
    """
    import shutil

    if not dest_dir or not base_name:
        return {"ok": False, "error": "chemin de publish introuvable pour ce nom"}

    tmp_dir = tempfile.mkdtemp(prefix="flux_hou_look_")
    out = (Path(tmp_dir) / "look_export.usda").as_posix()
    try:
        resp = houdini_client.run(_EXPORT_CODE.format(lop=lop_node or "", out=out))
        if not resp.get("ok"):
            return {"ok": False, "error": resp.get("error", "Houdini run failed")}

        payload = resp.get("result") or {}
        for rec in payload.get("__logs__", []):
            lvl = str(rec.get("level", "INFO")).upper()
            msg = f"[Houdini] {rec.get('msg', '')}"
            (log.warning if lvl == "WARNING" else log.error if lvl in ("ERROR", "CRITICAL")
             else log.info)(msg)
        if "__error__" in payload:
            log.error("Houdini look export: %s", payload["__error__"])
            return {"ok": False, "error": payload["__error__"]}
        written = payload.get("usd")
        if not written or not Path(written).is_file():
            return {"ok": False, "error": "Houdini n'a ecrit aucun USD"}

        from features.usd_export.look_export import publish_look_asset

        pub = publish_look_asset(written, Path(project_path), fmt=fmt, dest_dir=dest_dir,
                                 base_name=base_name, user=user)
        log.info("Houdini look published: %s (%s)", base_name, pub["version"])
        return {"ok": True, "asset": base_name, "version": pub["version"],
                "root": str(pub["root"]), "materials": pub["materials"],
                "bindings": pub["bindings"], "warnings": pub["warnings"]}
    except Exception as exc:
        log.error("Houdini look export failed: %s", exc)
        return {"ok": False, "error": str(exc)}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
