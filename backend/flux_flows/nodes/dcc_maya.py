# dcc_maya.py — MayaInstance and the may* nodes (02_NODES §8.1). P6a.
#
# Every node talks to Maya through the session's run(code) (commandPort live, mayapy
# worker headless), the code runs with `cmds` and assigns ``result``. Export, import and
# MAJ reuse the hub code with the session as transport:
#   mayExport     maya_export_client._build_command (dcc.maya.maya_export in Maya) + envelope
#   mayImport     dcc/maya/maya_hub.import_into_maya (tagged import, USD flattened)
#   mayUpdateRef  dcc/maya/maya_hub.update_imports (run_list / run_replace of maya_update)
#   mayPlayblast  dcc/maya/maya_playblast.py (new, Live only)
# The Maya side modules are imported from the backend root like maya_update (import_prep).
# A dcc_node value is a Maya node name (full path when Maya gives one).
# mayPublish (black box, run_maya_publish_action in a thread) is in dcc_publish.py.

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from flux_flows.nodes import dcc_common as dc
from flux_flows.nodes.contract import NodeError
from flux_flows.nodes.dcc_houdini import _exists_guard, _increment, run_script_node
from flux_flows.nodes.registry import flow_node, port

SOFT = "maya"
_S = dc.session_port(SOFT, "Maya")
_OVERWRITE = port("overwrite", "bool", "Ecraser un fichier existant", "Overwrite an existing file", False,
                  default=False, wirable=False)
_D_OVERWRITE = {"param": "overwrite", "equals": True}
_NODE_REQ = port("node", "dcc_node", "Node Maya", "Maya node", "|chair_grp|chair_geo", required=True)
SCENE_TYPES = {".ma": "mayaAscii", ".mb": "mayaBinary"}
_BACKEND_ROOT = str(Path(__file__).resolve().parents[2])

dc.instance_node(SOFT, icon="Box", shelf=190)


def _scene_type(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext not in SCENE_TYPES:
        raise NodeError(f"extension de scene Maya inconnue `{ext}` (.ma, .mb)")
    return SCENE_TYPES[ext]


def maya_module_call(session, module: str, func: str, *args: str, timeout: float = 120.0) -> Optional[Dict[str, Any]]:
    """``dcc.maya.<module>.<func>(*args, result_path)`` in Maya through *session* (live or
    mayapy), its JSON answer; None when Maya does not answer. Same code as
    import_prep.call_maya_update, with the session as transport."""
    def enc(text: str) -> str:
        return base64.b64encode(text.encode("utf-8")).decode("ascii")

    tmp = tempfile.mkdtemp(prefix="flux_flows_maya_call_")
    result_path = tmp.replace("\\", "/") + "/result.json"
    decoded = ", ".join(f"_b64.b64decode('{enc(a)}').decode('utf-8')" for a in (*args, result_path))
    code = (f"import sys, base64 as _b64\n"
            f"_root = _b64.b64decode('{enc(_BACKEND_ROOT)}').decode('utf-8')\n"
            f"if _root not in sys.path:\n    sys.path.insert(0, _root)\n"
            f"sys.modules.pop('dcc.maya.{module}', None)\n"
            f"from dcc.maya import {module} as _mu\n_mu.{func}({decoded})\nresult = True\n")
    try:
        resp = session.run(code, timeout)
        if not resp.get("ok"):
            return None if "ne repond pas" in str(resp.get("error")) else {"ok": False, "error": resp.get("error")}
        if not os.path.exists(result_path):
            return {"ok": False, "error": "Maya n'a rien renvoye"}
        with open(result_path, encoding="utf-8") as fh:
            return json.load(fh)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# -- scenes ------------------------------------------------------------------------------

@flow_node("dcc.may_open_scene", "mayOpenScene", icon="FolderOpen",
           inputs=[dc.EXEC, _S, port("path", "path", "Scene a ouvrir (.ma, .mb)", "Scene to open (.ma, .mb)",
                                     "$FLUX/PROJ/shot010_anim_v003.ma")],
           outputs=[dc.THEN, dc.ERR, port("scene", "path", "Scene ouverte", "Opened scene")],
           params=[port("new", "bool", "Scene vide (ignore path)", "Empty scene (path ignored)", False, default=False,
                        wirable=False),
                   port("discard_changes", "bool", "Perdre les modifications non enregistrees", "Drop unsaved changes",
                        False, default=False, wirable=False)],
           session="maya", effect=True, destructive={"param": "discard_changes", "equals": True},
           simulate=dc.sim(lambda i, p: "viderait la scene" if p.get("new") else f"ouvrirait {i.get('path')}",
                           lambda i, p: {"scene": str(i.get("path") or "")}, "path"),
           shelf=191, aliases=["ouvrir", "open", "scene"],
           doc_fr="Ouvre une scene dans Maya (ou une scene vide). Refuse si la scene courante a des modifications "
                  "non enregistrees, sauf discard_changes.",
           doc_en="Opens a scene in Maya (or an empty one). Refused when the current scene has unsaved changes, "
                  "unless discard_changes.")
def may_open_scene(ctx, inputs, params):
    s = dc.need_session(ctx, inputs)
    new = bool(params.get("new"))
    path = "" if new else dc.path_input(ctx, inputs.get("path"), "path")
    code = (f"_discard = {bool(params.get('discard_changes'))!r}\n"
            "if cmds.file(q=True, modified=True) and not _discard:\n"
            "    raise RuntimeError('scene modifiee non enregistree : enregistre-la ou coche discard_changes')\n"
            + ("cmds.file(new=True, force=True)\n" if new else f"cmds.file({path!r}, open=True, force=True)\n")
            + "result = cmds.file(q=True, sceneName=True) or ''\n")
    return {"scene": str(dc.call(s, code))}


@flow_node("dcc.may_save_scene", "maySaveScene", icon="Save",
           inputs=[dc.EXEC, _S, port("path", "path", "Vide = en place ; sinon enregistre sous ce nom",
                                     "Empty = in place; else saved under this name", "")],
           outputs=[dc.THEN, dc.ERR, port("path", "path", "Scene enregistree", "Saved scene")],
           params=[_OVERWRITE], session="maya", effect=True, destructive=_D_OVERWRITE,
           simulate=dc.sim(lambda i, p: "sauverait la scene" + (f" sous {i.get('path')}" if i.get("path") else " en place"),
                           lambda i, p: {"path": str(i.get("path") or "")}, "path"),
           shelf=192, aliases=["enregistrer", "save", "sauver"],
           doc_fr="Enregistre la scene Maya en place, ou sous un autre nom (.ma, .mb).",
           doc_en="Saves the Maya scene in place, or under another name (.ma, .mb).")
def may_save_scene(ctx, inputs, params):
    s = dc.need_session(ctx, inputs)
    if inputs.get("path") in (None, ""):
        code = ("if not cmds.file(q=True, sceneName=True):\n"
                "    raise RuntimeError('scene sans nom : donne un chemin')\n"
                "cmds.file(save=True, force=True)\nresult = cmds.file(q=True, sceneName=True)\n")
        return {"path": str(dc.call(s, code))}
    path = dc.path_input(ctx, inputs.get("path"), "path")
    kind = _scene_type(path)
    _exists_guard(path, bool(params.get("overwrite")))
    code = (f"import os\nos.makedirs(os.path.dirname({path!r}) or '.', exist_ok=True)\n"
            f"cmds.file(rename={path!r})\ncmds.file(save=True, type={kind!r}, force=True)\nresult = {path!r}\n")
    return {"path": str(dc.call(s, code))}


@flow_node("dcc.may_save_as", "maySaveAs", icon="SaveAll",
           inputs=[dc.EXEC, _S, port("path", "path", "Nouveau nom de la scene", "New scene name",
                                     "$FLUX/PROJ/shot010_anim.ma", required=True)],
           outputs=[dc.THEN, dc.ERR, port("path", "path", "Scene enregistree", "Saved scene")],
           params=[port("copy", "bool", "Copie : la scene ouverte garde son nom", "Copy: the open scene keeps its name",
                        False, default=False, wirable=False),
                   port("increment", "bool", "Ajoute _vNNN (version suivante libre)", "Adds _vNNN (next free version)",
                        False, default=False, wirable=False), _OVERWRITE],
           session="maya", effect=True, destructive=_D_OVERWRITE,
           simulate=dc.sim(lambda i, p: f"enregistrerait sous {i.get('path')}" + (" (copie)" if p.get("copy") else ""),
                           lambda i, p: {"path": str(i.get("path") or "")}, "path"),
           shelf=193, aliases=["enregistrer sous", "save as", "copie", "version"],
           doc_fr="Enregistre la scene sous un autre nom ; copy garde le nom de la scene ouverte (export de tout), "
                  "increment ajoute la version suivante libre.",
           doc_en="Saves the scene under another name; copy keeps the open scene name (export all), increment adds "
                  "the next free version.")
def may_save_as(ctx, inputs, params):
    s = dc.need_session(ctx, inputs)
    path = dc.path_input(ctx, inputs.get("path"), "path")
    if params.get("increment"):
        path = _increment(path)
    kind = _scene_type(path)
    _exists_guard(path, bool(params.get("overwrite")))
    head = f"import os\nos.makedirs(os.path.dirname({path!r}) or '.', exist_ok=True)\n"
    if params.get("copy"):
        code = head + f"cmds.file({path!r}, exportAll=True, type={kind!r}, force=True)\nresult = {path!r}\n"
    else:
        code = head + f"cmds.file(rename={path!r})\ncmds.file(save=True, type={kind!r}, force=True)\nresult = {path!r}\n"
    return {"path": str(dc.call(s, code))}


run_script_node(SOFT, "may", "Maya", _S, 194)


# -- export / import / references -----------------------------------------------------

@flow_node("dcc.may_export", "mayExport", icon="FileOutput",
           inputs=[dc.EXEC, _S, port("path", "path", "Fichier de sortie (.ma .mb .abc .fbx .obj .usd)",
                                     "Output file (.ma .mb .abc .fbx .obj .usd)", "$FLUX/PROJ/cache/anim.abc",
                                     required=True)],
           outputs=[dc.THEN, dc.ERR, port("files", "list[path]", "Fichiers ecrits", "Written files")],
           params=[port("scope", "str", "scene ou selection", "scene or selection", "selection", default="selection",
                        choices=("selection", "scene"), wirable=False),
                   port("frame_range", "str", "Plage (abc, usd) : 1001-1050", "Range (abc, usd): 1001-1050", "1001-1050"),
                   port("options", "dict", "Options d'export (comme le Publisher)", "Export options (like the Publisher)",
                        {}), _OVERWRITE],
           session="maya", effect=True, destructive=_D_OVERWRITE,
           simulate=dc.sim(lambda i, p: f"exporterait {p.get('scope') or 'selection'} vers {i.get('path')}",
                           lambda i, p: {"files": [str(i.get("path"))] if i.get("path") else []}, "path"),
           shelf=195, aliases=["exporter", "export", "abc", "fbx", "usd", "cache"],
           doc_fr="Exporte la scene ou la selection de Maya vers un fichier (meme export que le Publisher Maya).",
           doc_en="Exports the Maya scene or selection to a file (same export as the Maya Publisher).")
def may_export(ctx, inputs, params):
    from dcc.maya.maya_export_client import _build_command, _read_envelope

    s = dc.need_session(ctx, inputs)
    out = Path(dc.path_input(ctx, inputs.get("path"), "path"))
    _exists_guard(str(out), bool(params.get("overwrite")))
    ext = ".bgeo.sc" if out.name.lower().endswith(".bgeo.sc") else out.suffix.lower()
    out.parent.mkdir(parents=True, exist_ok=True)
    result_path = out.parent / f"_flux_export_result_{os.getpid()}.json"
    scope = "scene" if params.get("scope") == "scene" else "selection"
    fr = dc.frame_range(params.get("frame_range"))
    try:
        cmd = _build_command(out, result_path, ext, scope, fr[:2] if fr else None, params.get("options") or None)
        resp = s.run(cmd, 1800.0)
        logs, errors = _read_envelope(result_path)
    finally:
        try:
            result_path.unlink()
        except OSError:
            pass
    for rec in logs:
        ctx.log(f"[Maya] {rec.get('msg', '')}", "error" if str(rec.get("level")).upper() == "ERROR" else "info")
    if not resp.get("ok") or not out.exists():
        reason = " | ".join(errors) or resp.get("error") or "fichier absent"
        raise NodeError(f"export Maya echoue : {reason}")
    return {"files": [str(out)]}


def _project_of(path: Path) -> tuple:
    """(project name, path relative to it) when *path* is under a FLUX project, else ("", path)."""
    try:
        from core.paths import get_projects_dir

        rel = path.resolve().relative_to(get_projects_dir().resolve())
        return rel.parts[0], str(Path(*rel.parts[1:])).replace("\\", "/")
    except (ValueError, RuntimeError, OSError, IndexError):
        return "", str(path).replace("\\", "/")


def _send_through(session):
    """send_command_direct(cmd, timeout, port) for maya_hub, over the session."""
    def send(cmd, timeout=30.0, port=None):
        resp = session.run(cmd, timeout)
        return "ok" if resp.get("ok") else None
    return send


@flow_node("dcc.may_import", "mayImport", icon="FileInput",
           inputs=[dc.EXEC, _S, port("path", "path", "Fichier a importer (.ma .mb .abc .fbx .obj .usd)",
                                     "File to import", "$FLUX/PROJ/ASSET/chair_model_LAST.fbx", required=True)],
           outputs=[dc.THEN, dc.ERR, port("nodes", "list[dcc_node]", "Fichier importe (tag FLUX pour la MAJ)",
                                          "Imported file (FLUX tag for the update)")],
           params=[port("mode", "str", "import, reference ou proxy (USD : mayaUsdProxyShape)",
                        "import, reference or proxy (USD: mayaUsdProxyShape)", "import", default="import",
                        choices=("import", "reference", "proxy"), wirable=False)],
           session="maya", effect=True,
           simulate=dc.sim(lambda i, p: f"importerait {i.get('path')} ({p.get('mode') or 'import'})",
                           lambda i, p: {"nodes": []}, "path"),
           shelf=196, aliases=["importer", "import", "reference", "charger"],
           doc_fr="Importe un fichier dans Maya comme le Hub (USD aplati, import marque pour la MAJ) ; reference = "
                  "reference Maya ; proxy = USD vivant (mayaUsdProxyShape).",
           doc_en="Imports a file into Maya like the Hub (USD flattened, import tagged for the update); reference = "
                  "Maya reference; proxy = live USD (mayaUsdProxyShape).")
def may_import(ctx, inputs, params):
    from dcc.maya.maya_hub import MayaHubError, import_into_maya

    s = dc.need_session(ctx, inputs)
    path = Path(dc.path_input(ctx, inputs.get("path"), "path"))
    if not path.exists():
        raise NodeError(f"fichier introuvable : {path}")
    mode = str(params.get("mode") or "import")
    if mode == "reference":
        ns = re.sub(r"[^A-Za-z0-9_]", "_", path.stem)
        got = dc.call(s, f"result = cmds.file({str(path).replace(chr(92), '/')!r}, reference=True, "
                         f"namespace={ns!r}, returnNewNodes=True) or []\n")
        return {"nodes": [str(n) for n in got][:200]}
    project, rel = _project_of(path)
    try:
        got = import_into_maya(path, port=s.port or 0, project_name=project, rel_path=rel, mode=mode,
                               send=_send_through(s))
    except MayaHubError as exc:
        raise NodeError(exc.message) from None
    return {"nodes": [got.get("file") or str(path)]}


def _sim_update(ctx, inputs, params):
    """A dry run lists the imports that would be replaced (a read on an open session)."""
    from dcc.maya.maya_hub import MayaHubError, update_imports

    s = inputs.get("session")
    if s is None:
        return {"lines": [{"kind": "skip", "text_fr": dc.SKIPPED_FR}], "outputs": {"updated": [], "skipped": 0}}
    try:
        out = update_imports(s.port or 0, dry=True, only=str(inputs.get("node") or "") or None,
                             call=lambda port, func, *args, timeout=60.0, module="maya_update":
                             maya_module_call(s, module, func, *args, timeout=timeout))
    except MayaHubError as exc:
        return {"lines": [{"kind": "dcc", "text_fr": f"liste des imports illisible : {exc.message}"}],
                "outputs": {"updated": [], "skipped": 0}}
    todo = [e["node"] for e in out["items"] if e["status"] == "update"]
    lines = [{"kind": "dcc", "text_fr": f"remplacerait {n}"} for n in todo] or \
            [{"kind": "dcc", "text_fr": "aucun import a mettre a jour"}]
    return {"lines": lines, "outputs": {"updated": todo, "skipped": out["skipped"]}}



@flow_node("dcc.may_update_ref", "mayUpdateRef", icon="RefreshCw",
           inputs=[dc.EXEC, _S, port("node", "dcc_node", "Un import FLUX (vide = tous)", "One FLUX import (empty = all)",
                                     "|chair_model_grp")],
           outputs=[dc.THEN, dc.ERR, port("updated", "list[dcc_node]", "Imports remplaces", "Replaced imports"),
                    port("skipped", "int", "Imports deja a jour ou figes (vNNN)", "Imports up to date or frozen (vNNN)")],
           session="maya", effect=True, simulate=_sim_update, shelf=197, aliases=["maj", "update", "mettre a jour", "last"],
           doc_fr="Met a jour les imports FLUX de la scene dont le LAST a change (comme le bouton MAJ) ; les imports "
                  "vNNN restent figes.",
           doc_en="Updates the FLUX imports of the scene whose LAST changed (like the MAJ button); vNNN imports stay "
                  "frozen.")
def may_update_ref(ctx, inputs, params):
    from dcc.maya.maya_hub import MayaHubError, update_imports

    s = dc.need_session(ctx, inputs)
    try:
        out = update_imports(s.port or 0, only=str(inputs.get("node") or "") or None,
                             call=lambda port, func, *args, timeout=60.0, module="maya_update":
                             maya_module_call(s, module, func, *args, timeout=timeout))
    except MayaHubError as exc:
        raise NodeError(exc.message) from None
    if not out["ok"]:
        raise NodeError(out["message"])
    ctx.log(out["message"])
    return {"updated": out["updated"], "skipped": out["skipped"]}




# -- playblast, nodes and attributes ---------------------------------------------------------

def _playblast_target(ctx, inputs, params) -> str:
    return dc.path_input(ctx, inputs.get("path"), "path")


@flow_node("dcc.may_playblast", "mayPlayblast", icon="Video",
           inputs=[dc.EXEC, _S, port("path", "path", "Fichier video, ou base des images (sequence)",
                                     "Video file, or image base (sequence)", "$FLUX/PROJ/review/shot010_anim.mov",
                                     required=True)],
           outputs=[dc.THEN, dc.ERR, port("file", "path", "Video ou premiere image", "Video or first image")],
           params=[port("frame_range", "str", "Plage (vide = plage de lecture) : 1001-1050",
                        "Range (empty = playback range): 1001-1050", "1001-1050"),
                   port("size", "str", "Taille LxH (vide = taille de la vue)", "Size WxH (empty = view size)", "1920x1080"),
                   port("format", "str", "mov, mp4 ou sequence (PNG)", "mov, mp4 or sequence (PNG)", "mov", default="mov",
                        choices=("mov", "mp4", "sequence"), wirable=False),
                   port("camera", "str", "Camera (vide = celle de la vue)", "Camera (empty = the view's)", "shotCam"),
                   _OVERWRITE],
           session="maya", live_only=True, effect=True, destructive=_D_OVERWRITE,
           simulate=dc.sim(lambda i, p: f"capturerait la vue vers {i.get('path')}",
                           lambda i, p: {"file": str(i.get("path") or "")}, "path"),
           shelf=198, aliases=["playblast", "video", "capture", "review"],
           doc_fr="Capture la vue active de Maya (playblast) en video ou en images. Session Live seulement : il faut "
                  "une vue a l'ecran.",
           doc_en="Captures the active Maya view (playblast) as a video or images. Live session only: a view must be "
                  "on screen.")
def may_playblast(ctx, inputs, params):
    s = dc.need_session(ctx, inputs)
    if not s.live:
        raise NodeError("mayPlayblast demande une session Live (une vue a l'ecran)")
    fr = dc.frame_range(params.get("frame_range"))
    size = str(params.get("size") or "").lower().replace(" ", "")
    width = height = 0
    if size:
        m = re.match(r"^(\d+)x(\d+)$", size)
        if not m:
            raise NodeError(f"size invalide `{params.get('size')}` (ex. 1920x1080)")
        width, height = int(m.group(1)), int(m.group(2))
    cfg = {"out": _playblast_target(ctx, inputs, params), "start": fr[0] if fr else None, "end": fr[1] if fr else None,
           "width": width, "height": height, "fmt": str(params.get("format") or "mov"),
           "camera": str(params.get("camera") or ""), "overwrite": bool(params.get("overwrite"))}
    got = maya_module_call(s, "maya_playblast", "run_playblast", json.dumps(cfg), timeout=1800.0)
    if got is None:
        raise NodeError("Maya ne repond pas (commandPort)")
    if not got.get("ok"):
        raise NodeError(f"playblast : {got.get('error')}")
    return {"file": str(got.get("file") or "")}


@flow_node("dcc.may_find_nodes", "mayFindNodes", icon="ScanSearch",
           inputs=[dc.EXEC_OPT, _S],
           outputs=[dc.THEN_OPT, port("nodes", "list[dcc_node]", "Nodes trouves (chemins complets)", "Nodes found (full paths)"),
                    port("count", "int", "Nombre", "Count", 4)],
           params=[port("pattern", "pattern", "Motif sur le nom court", "Pattern on the short name", "*_geo ^tmp*",
                        required=True),
                   port("type", "str", "Type Maya (mesh, transform, joint...), vide = tous", "Maya type, empty = all",
                        "transform")],
           session="maya", shelf=199, aliases=["chercher", "find", "ls", "nodes"],
           doc_fr="Les nodes de la scene dont le nom court passe le motif (et du type donne). Lecture.",
           doc_en="The scene nodes whose short name passes the pattern (and of the given type). Read only.")
def may_find_nodes(ctx, inputs, params):
    from flux_flows.patterns import PatternError, mask

    skipped = dc.skip_read(ctx, inputs, {"nodes": [], "count": 0})
    if skipped is not None:
        return skipped
    s = dc.need_session(ctx, inputs)
    pattern = dc.text_param(ctx, params.get("pattern"), "pattern")
    kind = str(params.get("type") or "").strip()
    rows = dc.call(s, "result = cmds.ls(long=True" + (f", type={kind!r}" if kind else "") + ") or []\n", 120) or []
    try:
        keep = mask(pattern, [str(r).rsplit("|", 1)[-1].rsplit(":", 1)[-1] for r in rows], case_sensitive=True)
    except PatternError as exc:
        raise NodeError(f"motif invalide : {exc.message}", code="E_PARAM_INVALID") from None
    found: List[str] = [str(r) for r, k in zip(rows, keep) if k]
    return {"nodes": found, "count": len(found)}


@flow_node("dcc.may_set_attr", "maySetAttr", icon="SlidersHorizontal",
           inputs=[dc.EXEC, _S, _NODE_REQ, port("attr", "str", "Attribut", "Attribute", "visibility", required=True),
                   port("value", "any", "Valeur (liste pour un attribut compose)", "Value (list for a compound)", 1,
                        required=True)],
           outputs=[dc.THEN, dc.ERR], session="maya", effect=True,
           simulate=dc.sim(lambda i, p: f"mettrait {i.get('node')}.{i.get('attr')} = {i.get('value')!r}"),
           shelf=200, aliases=["attribut", "set", "regler", "setattr"],
           doc_fr="Regle un attribut d'un node Maya (texte, nombre, booleen, ou liste pour un attribut compose).",
           doc_en="Sets an attribute of a Maya node (text, number, bool, or a list for a compound).")
def may_set_attr(ctx, inputs, params):
    s = dc.need_session(ctx, inputs)
    plug = f"{dc.text_param(ctx, inputs.get('node'), 'node')}.{dc.text_param(ctx, inputs.get('attr'), 'attr')}"
    code = (f"_v = {dc.literal(inputs.get('value'))}\n"
            f"if isinstance(_v, str):\n    cmds.setAttr({plug!r}, _v, type='string')\n"
            f"elif isinstance(_v, (list, tuple)):\n    cmds.setAttr({plug!r}, *_v)\n"
            f"else:\n    cmds.setAttr({plug!r}, _v)\nresult = True\n")
    dc.call(s, code)
    return {}


@flow_node("dcc.may_get_attr", "mayGetAttr", icon="Gauge",
           inputs=[dc.EXEC_OPT, _S, _NODE_REQ, port("attr", "str", "Attribut", "Attribute", "translateX", required=True)],
           outputs=[dc.THEN_OPT, port("value", "any", "Valeur", "Value", 0.0)],
           session="maya", shelf=201, aliases=["attribut", "lire", "get", "getattr"],
           doc_fr="Lit un attribut d'un node Maya. Lecture.", doc_en="Reads an attribute of a Maya node. Read only.")
def may_get_attr(ctx, inputs, params):
    skipped = dc.skip_read(ctx, inputs, {"value": None})
    if skipped is not None:
        return skipped
    s = dc.need_session(ctx, inputs)
    plug = f"{dc.text_param(ctx, inputs.get('node'), 'node')}.{dc.text_param(ctx, inputs.get('attr'), 'attr')}"
    value = dc.call(s, f"result = cmds.getAttr({plug!r})\n")
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], (list, tuple)):
        value = list(value[0])          # compound attributes come as [(x, y, z)]
    return {"value": value}
