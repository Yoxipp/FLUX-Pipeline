# maya_hub.py — backend side of a Maya import and of the "MAJ" update of the imports.
#
# Extracted from routers/dcc.py (maya_import_file, maya_update_imports) so the Flows
# nodes mayImport / mayUpdateRef (P6a) run the same logic as the hub routes. Sync: the
# routes call them in an executor. Failures raise MayaHubError(status, message), the
# routes turn it into the same HTTPException as before.

from __future__ import annotations

import base64
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

from core.logger import get_logger
from dcc.maya.import_prep import ascii_path, call_maya_update, usd_source_for_maya

log = get_logger(__name__)

IMPORT_EXTS = {".obj", ".fbx", ".ma", ".mb", ".abc", ".usd", ".usda", ".usdc", ".usdz"}
# USD container extensions whose binary-crate form must be transcoded to ASCII for Maya.
USD_EXTS = {".usd", ".usda", ".usdc", ".usdz"}
_BACKEND_ROOT = str(Path(__file__).resolve().parents[2])


class MayaHubError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _enc(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def import_into_maya(file_path: Path, *, port: int, project_name: str, rel_path: str, mode: str = "import",
                     send: Optional[Callable[..., Any]] = None) -> dict:
    """Import *file_path* into the Maya on commandPort *port* (.obj .fbx .ma .mb .abc, USD
    flattened to ASCII, or a mayaUsdProxyShape in ``proxy`` mode). The import is tagged
    {project, source, stamp, mode} for the MAJ update. Returns {"ok": True, "file"}."""
    from features.importer.import_tracking import source_stamp

    if send is None:
        from dcc.maya.maya_connection import send_command_direct as send

    file_path = Path(file_path)
    ext = file_path.suffix.lower()
    if ext not in IMPORT_EXTS:
        raise MayaHubError(400, f"Format non supporté pour l'import Maya : {ext}")
    proxy_mode = mode == "proxy"
    if proxy_mode and ext not in USD_EXTS:
        raise MayaHubError(400, "Le mode proxy USD ne s'applique qu'a un fichier USD")

    # Maya writes a JSON result envelope here so the hub knows if the import actually
    # succeeded (Maya runs in another process; a plain call always looked like success).
    result_dir = tempfile.mkdtemp(prefix="flux_maya_import_")
    result_path = result_dir.replace("\\", "/") + "/_flux_import_result.json"
    try:
        # Maya 2024's mayaUsd cannot read recent crates nor accented paths: flatten USD to a
        # temp ASCII .usda (in result_dir, cleaned up with it). Other formats pass through.
        if proxy_mode:
            # The stage itself (no flattening): mayaUsd reads the sublayers and variants. An
            # accented folder goes through its Windows short name (mayaUsd fails on accents).
            fp_fwd = ascii_path(file_path)
            if fp_fwd is None:
                raise MayaHubError(400, "Chemin avec accents sans nom court Windows : ouvre plutot l'import aplati")
        elif ext in USD_EXTS:
            fp_fwd = usd_source_for_maya(file_path, result_dir)
        else:
            fp_fwd = str(file_path).replace("\\", "/")

        # Every path travels as base64(UTF-8) and is decoded inside Maya: commandPort decodes
        # the incoming bytes with the system locale (cp1252 on a French Windows), so a raw
        # accented path gets mojibaked. base64 is pure ASCII and survives any decode.
        tag = json.dumps({"project": project_name, "source": rel_path.replace("\\", "/"),
                          "stamp": source_stamp(file_path), "mode": "proxy" if proxy_mode else "import"})
        cmd = (
            f"import sys, base64 as _b64; "
            f"sys.path.insert(0, _b64.b64decode('{_enc(_BACKEND_ROOT)}').decode('utf-8')); "
            f"sys.modules.pop('dcc.maya.maya_import', None); "
            f"sys.modules.pop('dcc.maya.maya_update', None); "
            f"from dcc.maya.maya_import import run_import; "
            f"run_import(_b64.b64decode('{_enc(fp_fwd)}').decode('utf-8'), "
            f"_b64.b64decode('{_enc(result_path)}').decode('utf-8'), "
            f"mode={'proxy' if proxy_mode else 'import'!r}, "
            f"tag_json=_b64.b64decode('{_enc(tag)}').decode('utf-8'))"
        )
        result = send(cmd, timeout=30.0, port=port)
        if result is None:
            raise MayaHubError(503, "Maya ne répond pas. Assure-toi que Maya est ouvert et le commandPort actif.")

        # Read the envelope; mirror Maya's logs into the hub logger (Flux console) and
        # keep error lines for the failure detail.
        ok = False
        maya_errors: list[str] = []
        if os.path.exists(result_path):
            try:
                with open(result_path, encoding="utf-8") as fh:
                    envelope = json.load(fh)
            except (OSError, ValueError):
                envelope = None
            if envelope:
                ok = bool(envelope.get("ok"))
                for rec in envelope.get("logs", []):
                    lvl = str(rec.get("level", "INFO")).upper()
                    text = f"[Maya] {rec.get('msg', '')}"
                    if lvl in ("ERROR", "CRITICAL"):
                        log.error(text)
                        maya_errors.append(str(rec.get("msg", "")))
                    elif lvl == "WARNING":
                        log.warning(text)
                    else:
                        log.info(text)
        if not ok:
            reason = f" ({' | '.join(maya_errors)})" if maya_errors else ""
            log.error("Import Maya échoué : %s%s", fp_fwd, reason)
            raise MayaHubError(500, f"Import Maya échoué : {Path(fp_fwd).name}{reason}")
        return {"ok": True, "file": fp_fwd}
    finally:
        shutil.rmtree(result_dir, ignore_errors=True)


def update_imports(port: int, *, dry: bool = False, only: Optional[str] = None,
                   call: Callable[..., Optional[dict]] = call_maya_update) -> dict:
    """Bring the FLUX imports of the Maya scene to their LAST (X4): each tagged import whose
    published file changed is re-imported in place; vNNN imports stay frozen. *dry* = the
    plan only (nothing replaced). *only* = one Maya node (full path). Returns
    {"ok", "message", "items", "updated", "skipped"}."""
    from core.paths import get_project_path
    from features.importer.import_tracking import plan_updates, summary

    listed = call(port, "run_list")
    if listed is None:
        raise MayaHubError(503, "Maya ne repond pas (commandPort).")
    items = listed.get("items", [])
    if only:
        items = [i for i in items if i.get("node") == only]
    projects = {p: get_project_path(p) for p in {str(i.get("project") or "") for i in items} if p}
    plan = plan_updates(items, {k: v for k, v in projects.items() if v.exists()})
    done, failed, updated = 0, [], []
    for entry in plan:
        if entry["status"] != "update" or dry:
            continue
        file_path = projects[entry["project"]] / entry["source"]
        tmp = tempfile.mkdtemp(prefix="flux_maya_update_src_")
        try:
            if entry["mode"] != "proxy" and file_path.suffix.lower() in USD_EXTS:
                fp = usd_source_for_maya(file_path, tmp)
            else:
                fp = str(file_path).replace("\\", "/")
            tag = json.dumps({"project": entry["project"], "source": entry["source"],
                              "stamp": entry["stamp"], "mode": entry["mode"] or "import"})
            res = call(port, "run_replace", entry["node"], fp, tag, timeout=120.0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if res and res.get("ok"):
            done += 1
            entry["status"] = "updated"
            updated.append(entry["node"])
        else:
            failed.append(entry["node"].rsplit("|", 1)[-1])
            log.warning("[Maya] MAJ import %s echouee : %s", entry["node"], (res or {}).get("error"))
    message = summary(plan, done, failed)
    log.info("[Maya] %s", message)
    skipped = sum(1 for e in plan if e["status"] not in ("update", "updated"))
    return {"ok": not failed, "message": message, "items": plan, "updated": updated, "skipped": skipped}
