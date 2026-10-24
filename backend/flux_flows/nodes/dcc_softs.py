# dcc_softs.py — Nuke, Substance Painter, Substance Designer, Marvelous, ZBrush and Mari
# nodes (02_NODES §8.3 to §8.8). P6b.
#
# Only the verbs their bridge REALLY supports today are nodes (A17); the "bridge+" verbs
# (open / save / save_as / run_script / import of sp, sd, zb, mari; open / save / save_as /
# run_script of mvd) need a new command in the soft's script: not invented, listed in
# flux_flows/CONTEXT.md as postponed. All Live (no headless; nuke -t not offered in V1).
#   Nuke       TcpJsonSession ({"cmd": "run"}): scene verbs, script, export (temporary Write),
#              import (Read), render (an existing Write), find nodes. Code runs in Nuke with
#              exec(code, {"nuke"}, locals): no comprehension over a local name.
#   Painter    export (build_export_config + client.export), info ; "bridge+" (P6b step 9):
#              open (.spp or new project from a mesh), save, save_as, import (mesh reload or
#              project resource), run_script (bridge `run`, gated by the machine secret)
#   Designer   export, info, sdCook (sbscooker next to Designer.exe, hub side, session optional)
#   Marvelous  file mailbox: export, import, info
#   ZBrush     export ztl / obj / fbx, mesh info; ZBrush is ALWAYS released (stop) after an
#              export, on error, timeout or cancel, and at the end of the run
#   Mari       export (one at a time), info
# Clients are built on the session's port (P6b refactor `port=`). The publish black boxes
# (cores of the locked subflows) are in dcc_publish.py.

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from flux_flows.nodes import dcc_common as dc
from flux_flows.nodes.contract import NodeError
from flux_flows.nodes.dcc_houdini import _exists_guard, _increment, run_script_node
from flux_flows.nodes.registry import flow_node, port

_OVERWRITE = port("overwrite", "bool", "Ecraser un fichier existant", "Overwrite an existing file", False,
                  default=False, wirable=False)
_D_OVERWRITE = {"param": "overwrite", "equals": True}


def client_for(session, soft: str):
    """The existing client of *soft*, on the session's port."""
    p = getattr(session, "port", None)
    if soft == "painter":
        from dcc.substance_painter.client import SubstancePainterClient

        return SubstancePainterClient(port=p)
    if soft == "designer":
        from dcc.substance_designer.client import SubstanceDesignerClient

        return SubstanceDesignerClient(port=p)
    if soft == "mari":
        from dcc.mari.client import MariClient

        return MariClient(port=p)
    if soft == "zbrush":
        from dcc.zbrush.client import ZBRUSH_BRIDGE_PORT, ZBrushClient

        return ZBrushClient(port=p or ZBRUSH_BRIDGE_PORT)
    if soft == "marvelous":
        from dcc.marvelous.client import marvelous_client

        return marvelous_client
    if soft == "nuke":
        from dcc.nuke.client import NukeClient

        return NukeClient(port=p)
    raise NodeError(f"logiciel inconnu {soft}")


def _ok(resp: Any, what: str) -> Dict[str, Any]:
    if not isinstance(resp, dict) or not (resp.get("ok") or resp.get("status") == "ok"):
        msg = str((resp or {}).get("error") or (resp or {}).get("msg") or "echec")
        if msg.lower().startswith("unknown action"):
            msg = "bridge trop ancien pour ce node : reinstalle le bridge depuis FLUX puis relance le logiciel"
        raise NodeError(f"{what} : {msg}")
    return resp


def _dir_input(ctx, value: Any, what: str = "dossier") -> str:
    return dc.path_input(ctx, value, what)


# == Instances ================================================================================

for _soft, _icon, _shelf in (("nuke", "Clapperboard", 210), ("painter", "Palette", 230), ("designer", "Waypoints", 240),
                             ("marvelous", "Shirt", 250), ("zbrush", "Brush", 260), ("mari", "PaintBucket", 270)):
    dc.instance_node(_soft, icon=_icon, shelf=_shelf, headless=False)


# == Nuke ======================================================================================

_NK = dc.session_port("nuke", "Nuke")


@flow_node("dcc.nk_open_scene", "nkOpenScene", icon="FolderOpen",
           inputs=[dc.EXEC, _NK, port("path", "path", "Script a ouvrir (.nk)", "Script to open (.nk)",
                                      "$FLUX/PROJ/shot010_comp_v004.nk")],
           outputs=[dc.THEN, dc.ERR, port("scene", "path", "Script ouvert", "Opened script")],
           params=[port("new", "bool", "Script vide (ignore path)", "Empty script (path ignored)", False, default=False,
                        wirable=False),
                   port("discard_changes", "bool", "Perdre les modifications non enregistrees", "Drop unsaved changes",
                        False, default=False, wirable=False)],
           session="nuke", live_only=True, effect=True, destructive={"param": "discard_changes", "equals": True},
           simulate=dc.sim(lambda i, p: "viderait le script" if p.get("new") else f"ouvrirait {i.get('path')}",
                           lambda i, p: {"scene": str(i.get("path") or "")}, "path"),
           shelf=211, aliases=["ouvrir", "open", "script", "nk"],
           doc_fr="Ouvre un script Nuke (ou un script vide). Refuse si le script courant a des modifications non "
                  "enregistrees, sauf discard_changes.",
           doc_en="Opens a Nuke script (or an empty one). Refused when the current script has unsaved changes, unless "
                  "discard_changes.")
def nk_open_scene(ctx, inputs, params):
    s = dc.need_session(ctx, inputs)
    new = bool(params.get("new"))
    path = "" if new else dc.path_input(ctx, inputs.get("path"), "path")
    code = (f"if nuke.root().modified() and not {bool(params.get('discard_changes'))!r}:\n"
            "    raise RuntimeError('script modifie non enregistre : enregistre-le ou coche discard_changes')\n"
            "nuke.root().setModified(False)\nnuke.scriptClear()\n"
            + ("" if new else f"nuke.scriptOpen({path!r})\n")
            + "result = nuke.root().name()\n")
    return {"scene": str(dc.call(s, code))}


@flow_node("dcc.nk_save_scene", "nkSaveScene", icon="Save",
           inputs=[dc.EXEC, _NK, port("path", "path", "Vide = en place ; sinon enregistre sous ce nom",
                                      "Empty = in place; else saved under this name", "")],
           outputs=[dc.THEN, dc.ERR, port("path", "path", "Script enregistre", "Saved script")],
           params=[_OVERWRITE], session="nuke", live_only=True, effect=True, destructive=_D_OVERWRITE,
           simulate=dc.sim(lambda i, p: "sauverait le script" + (f" sous {i.get('path')}" if i.get("path") else " en place"),
                           lambda i, p: {"path": str(i.get("path") or "")}, "path"),
           shelf=212, aliases=["enregistrer", "save"],
           doc_fr="Enregistre le script Nuke en place, ou sous un autre nom.",
           doc_en="Saves the Nuke script in place, or under another name.")
def nk_save_scene(ctx, inputs, params):
    from dcc.nuke.nuke_publish import build_script_save_code

    s = dc.need_session(ctx, inputs)
    if inputs.get("path") in (None, ""):
        return {"path": str(dc.call(s, "nuke.scriptSave()\nresult = nuke.root().name()\n"))}
    path = dc.path_input(ctx, inputs.get("path"), "path")
    _exists_guard(path, bool(params.get("overwrite")))
    return {"path": str(dc.call(s, build_script_save_code(path)))}


@flow_node("dcc.nk_save_as", "nkSaveAs", icon="SaveAll",
           inputs=[dc.EXEC, _NK, port("path", "path", "Nouveau nom du script", "New script name",
                                      "$FLUX/PROJ/shot010_comp.nk", required=True)],
           outputs=[dc.THEN, dc.ERR, port("path", "path", "Script enregistre", "Saved script")],
           params=[port("copy", "bool", "Copie : le script ouvert garde son nom", "Copy: the open script keeps its name",
                        False, default=False, wirable=False),
                   port("increment", "bool", "Ajoute _vNNN (version suivante libre)", "Adds _vNNN (next free version)",
                        False, default=False, wirable=False), _OVERWRITE],
           session="nuke", live_only=True, effect=True, destructive=_D_OVERWRITE,
           simulate=dc.sim(lambda i, p: f"enregistrerait sous {i.get('path')}", lambda i, p: {"path": str(i.get("path") or "")},
                           "path"),
           shelf=213, aliases=["enregistrer sous", "save as", "version"],
           doc_fr="Enregistre le script sous un autre nom (copy : le script ouvert garde son nom ; increment : version "
                  "suivante libre).",
           doc_en="Saves the script under another name (copy: the open script keeps its name; increment: next free "
                  "version).")
def nk_save_as(ctx, inputs, params):
    from dcc.nuke.nuke_publish import build_script_save_code

    s = dc.need_session(ctx, inputs)
    path = dc.path_input(ctx, inputs.get("path"), "path")
    if params.get("increment"):
        path = _increment(path)
    _exists_guard(path, bool(params.get("overwrite")))
    code = "_before = nuke.root().name()\n" + build_script_save_code(path) + "\n"
    if params.get("copy"):
        code += "nuke.root()['name'].setValue(_before)\n"
    return {"path": str(dc.call(s, code))}


run_script_node("nuke", "nk", "Nuke", _NK, 214)


@flow_node("dcc.nk_export", "nkExport", icon="FileOutput",
           inputs=[dc.EXEC, _NK, port("path", "path", "Fichier de sortie (#### ou %04d pour une sequence)",
                                      "Output file (#### or %04d for a sequence)", "$FLUX/PROJ/comp/shot010.%04d.exr",
                                      required=True),
                   port("node", "dcc_node", "Node a ecrire (vide = selection)", "Node to write (empty = selection)", "Merge1")],
           outputs=[dc.THEN, dc.ERR, port("files", "list[path]", "Fichier ecrit (motif pour une sequence)",
                                          "Written file (pattern for a sequence)")],
           params=[port("frame_range", "str", "Plage : 1001-1050 (vide = image courante)", "Range (empty = current frame)",
                        "1001-1050"),
                   port("options", "dict", "Knobs du Write (file_type, datatype...)", "Write knobs", {"file_type": "exr"}),
                   port("colorspace", "str", "Espace couleur du Write", "Write colorspace", "ACES - ACEScg"),
                   _OVERWRITE],
           session="nuke", live_only=True, effect=True, destructive=_D_OVERWRITE,
           simulate=dc.sim(lambda i, p: f"ecrirait {i.get('node') or 'la selection'} vers {i.get('path')}",
                           lambda i, p: {"files": [str(i.get("path"))] if i.get("path") else []}, "path"),
           shelf=215, aliases=["exporter", "write", "export", "exr"],
           doc_fr="Ecrit un node (ou la selection) avec un Write temporaire, sur une plage ou l'image courante.",
           doc_en="Writes a node (or the selection) with a temporary Write, on a range or the current frame.")
def nk_export(ctx, inputs, params):
    from dcc.nuke.nuke_publish import DEFAULT_WRITE_COLORSPACE, build_write_export_code

    s = dc.need_session(ctx, inputs)
    path = dc.path_input(ctx, inputs.get("path"), "path")
    if "%" not in path and "#" not in path:
        _exists_guard(path, bool(params.get("overwrite")))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fr = dc.frame_range(params.get("frame_range"))
    code = build_write_export_code(path, params.get("options") or None, fr[0] if fr else None, fr[1] if fr else None,
                                   str(inputs.get("node") or "") or None,
                                   str(params.get("colorspace") or "") or DEFAULT_WRITE_COLORSPACE)
    return {"files": [str(dc.call(s, code))]}


@flow_node("dcc.nk_import", "nkImport", icon="FileInput",
           inputs=[dc.EXEC, _NK, port("path", "path", "Image ou sequence a lire", "Image or sequence to read",
                                      "$FLUX/PROJ/render/beauty.%04d.exr", required=True)],
           outputs=[dc.THEN, dc.ERR, port("nodes", "list[dcc_node]", "Read cree", "Created Read")],
           params=[port("frame_range", "str", "Plage de la sequence : 1001-1050", "Sequence range", "1001-1050"),
                   port("colorspace", "str", "Espace couleur du Read", "Read colorspace", "rendering", default="rendering")],
           session="nuke", live_only=True, effect=True,
           simulate=dc.sim(lambda i, p: f"lirait {i.get('path')}", lambda i, p: {"nodes": []}, "path"),
           shelf=216, aliases=["importer", "read", "lire", "import"],
           doc_fr="Cree un Read dans Nuke pour une image ou une sequence.",
           doc_en="Creates a Read in Nuke for an image or a sequence.")
def nk_import(ctx, inputs, params):
    from dcc.nuke.nuke_import import build_read_node_code

    s = dc.need_session(ctx, inputs)
    fr = dc.frame_range(params.get("frame_range"))
    code = build_read_node_code(dc.path_input(ctx, inputs.get("path"), "path"), fr[0] if fr else None,
                                fr[1] if fr else None, str(params.get("colorspace") or "rendering"))
    return {"nodes": [str(dc.call(s, code))]}


@flow_node("dcc.nk_render", "nkRender", icon="Film",
           inputs=[dc.EXEC, _NK, port("node", "dcc_node", "Write a executer", "Write to execute", "Write1", required=True)],
           outputs=[dc.THEN, dc.ERR, port("files", "list[path]", "Images ecrites", "Written images")],
           params=[port("frame_range", "str", "Plage : 1001-1050 (vide = celle du script)", "Range (empty = the script's)",
                        "1001-1050"), _OVERWRITE],
           session="nuke", live_only=True, effect=True, destructive=_D_OVERWRITE,
           simulate=dc.sim(lambda i, p: f"rendrait le Write {i.get('node')}", lambda i, p: {"files": []}),
           shelf=217, aliases=["rendu", "render", "write", "executer"],
           doc_fr="Execute un Write existant avec ses reglages, sur une plage. Refuse d'ecraser la premiere image sans "
                  "overwrite.",
           doc_en="Executes an existing Write with its settings, on a range. Refuses to overwrite the first image "
                  "without overwrite.")
def nk_render(ctx, inputs, params):
    s = dc.need_session(ctx, inputs)
    node = dc.text_param(ctx, inputs.get("node"), "node")
    fr = dc.frame_range(params.get("frame_range"))
    head = (f"_w = nuke.toNode({node!r})\n"
            f"if _w is None or _w.Class() != 'Write':\n    raise RuntimeError('Write introuvable : {node}')\n"
            + (f"_a, _b = {fr[0]}, {fr[1]}\n" if fr else
               "_a, _b = int(nuke.root()['first_frame'].value()), int(nuke.root()['last_frame'].value())\n"))
    first = dc.call(s, head + "result = _w['file'].evaluate(_a)\n")
    if first and Path(str(first)).exists() and not params.get("overwrite"):
        raise NodeError(f"{first} existe deja : coche overwrite pour l'ecraser")
    code = head + ("nuke.execute(_w, _a, _b)\nresult = []\n"
                   "for _f in range(_a, _b + 1):\n    result.append(_w['file'].evaluate(_f))\n")
    return {"files": [str(f) for f in (dc.call(s, code) or [])]}


@flow_node("dcc.nk_find_nodes", "nkFindNodes", icon="ScanSearch",
           inputs=[dc.EXEC_OPT, _NK],
           outputs=[dc.THEN_OPT, port("nodes", "list[dcc_node]", "Nodes trouves", "Nodes found"),
                    port("count", "int", "Nombre", "Count", 2)],
           params=[port("pattern", "pattern", "Motif sur le nom", "Pattern on the name", "Write* ^*_tmp", required=True),
                   port("class", "str", "Classe Nuke (Write, Read...), vide = toutes", "Nuke class, empty = all", "Write")],
           session="nuke", live_only=True, shelf=218, aliases=["chercher", "find", "nodes", "write"],
           doc_fr="Les nodes du script dont le nom passe le motif (et de la classe donnee). Lecture.",
           doc_en="The script nodes whose name passes the pattern (and of the given class). Read only.")
def nk_find_nodes(ctx, inputs, params):
    from flux_flows.patterns import PatternError, mask

    skipped = dc.skip_read(ctx, inputs, {"nodes": [], "count": 0})
    if skipped is not None:
        return skipped
    s = dc.need_session(ctx, inputs)
    rows = dc.call(s, "result = [[n.fullName(), n.Class()] for n in nuke.allNodes(recurseGroups=True)]\n") or []
    kind = str(params.get("class") or "").strip()
    rows = [r for r in rows if not kind or r[1] == kind]
    try:
        keep = mask(dc.text_param(ctx, params.get("pattern"), "pattern"), [r[0] for r in rows], case_sensitive=True)
    except PatternError as exc:
        raise NodeError(f"motif invalide : {exc.message}", code="E_PARAM_INVALID") from None
    found = [r[0] for r, k in zip(rows, keep) if k]
    return {"nodes": found, "count": len(found)}


# == Substance Painter ===========================================================================

_SP = dc.session_port("painter", "Painter")


@flow_node("dcc.sp_export", "spExport", icon="FileOutput",
           inputs=[dc.EXEC, _SP, port("path", "dir", "Dossier de sortie des textures", "Texture output folder",
                                      "$FLUX/PROJ/textures/chair", required=True)],
           outputs=[dc.THEN, dc.ERR, port("files", "list[path]", "Textures ecrites", "Written textures")],
           params=[port("preset", "str", "Preset d'export de Painter", "Painter export preset", "PBR Metallic Roughness",
                        default="PBR Metallic Roughness"),
                   port("format", "str", "Format (png, exr, tif...)", "Format", "png", default="png"),
                   port("bit_depth", "str", "Profondeur (8, 16, 16f, 32f)", "Bit depth", "8", default="8"),
                   port("size", "int", "Largeur en pixels (vide = celle du texture set)", "Width in pixels", 2048),
                   port("texture_sets", "list[str]", "Texture sets (vide = tous)", "Texture sets (empty = all)", ["body"]),
                   port("maps", "list[str]", "Maps du preset (vide = toutes)", "Preset maps (empty = all)", ["BaseColor"])],
           session="painter", live_only=True, effect=True,
           simulate=dc.sim(lambda i, p: f"exporterait les textures vers {i.get('path')}", lambda i, p: {"files": []},
                           "path"),
           shelf=231, aliases=["exporter", "textures", "export", "painter"],
           doc_fr="Exporte les textures du projet Painter ouvert dans un dossier, avec un preset.",
           doc_en="Exports the textures of the open Painter project to a folder, with a preset.")
def sp_export(ctx, inputs, params):
    from dcc.substance_painter.substance_export import build_export_config

    s = dc.need_session(ctx, inputs)
    folder = _dir_input(ctx, inputs.get("path"))
    Path(folder).mkdir(parents=True, exist_ok=True)
    config = build_export_config(folder, str(params.get("preset") or "PBR Metallic Roughness"),
                                 str(params.get("format") or "png"), str(params.get("bit_depth") or "8"),
                                 params.get("texture_sets") or None, params.get("size") or None,
                                 maps=params.get("maps") or None)
    resp = _ok(client_for(s, "painter").export(config), "export Painter")
    return {"files": [str(f) for f in resp.get("files") or []]}


@flow_node("dcc.sp_info", "spInfo", icon="Info",
           inputs=[dc.EXEC_OPT, _SP],
           outputs=[dc.THEN_OPT, port("info", "dict", "Projet ouvert", "Open project"),
                    port("texture_sets", "list[str]", "Texture sets", "Texture sets")],
           session="painter", live_only=True, shelf=232, aliases=["info", "texture sets", "projet"],
           doc_fr="Le projet ouvert dans Painter et ses texture sets. Lecture.",
           doc_en="The project open in Painter and its texture sets. Read only.")
def sp_info(ctx, inputs, params):
    skipped = dc.skip_read(ctx, inputs, {"info": {}, "texture_sets": []})
    if skipped is not None:
        return skipped
    resp = _ok(client_for(dc.need_session(ctx, inputs), "painter").info(), "info Painter")
    sets = [t.get("name") if isinstance(t, dict) else str(t) for t in resp.get("texture_sets") or []]
    return {"info": resp, "texture_sets": sets}


@flow_node("dcc.sp_open_scene", "spOpenScene", icon="FolderOpen",
           inputs=[dc.EXEC, _SP, port("path", "path", "Projet a ouvrir (.spp)", "Project to open (.spp)",
                                      "$FLUX/PROJ/chair_tex_v003.spp"),
                   port("mesh", "path", "Mesh d'un nouveau projet (ignore path)", "Mesh of a new project (path ignored)",
                        "$FLUX/PROJ/chair_mod.fbx")],
           outputs=[dc.THEN, dc.ERR, port("scene", "path", "Projet ouvert (vide si nouveau)", "Opened project")],
           params=[port("discard_changes", "bool", "Perdre les modifications non enregistrees", "Drop unsaved changes",
                        False, default=False, wirable=False)],
           session="painter", live_only=True, effect=True, destructive={"param": "discard_changes", "equals": True},
           simulate=dc.sim(lambda i, p: f"creerait un projet depuis {i.get('mesh')}" if i.get("mesh")
                           else f"ouvrirait {i.get('path')}", lambda i, p: {"scene": str(i.get("path") or "")}),
           shelf=234, aliases=["ouvrir", "open", "projet", "spp", "nouveau", "mesh"],
           doc_fr="Ouvre un projet Painter, ou en cree un depuis un mesh. Refuse si le projet courant a des "
                  "modifications non enregistrees, sauf discard_changes.",
           doc_en="Opens a Painter project, or creates one from a mesh. Refused when the current project has unsaved "
                  "changes, unless discard_changes.")
def sp_open_scene(ctx, inputs, params):
    s = dc.need_session(ctx, inputs)
    mesh = dc.path_input(ctx, inputs.get("mesh"), "mesh") if inputs.get("mesh") not in (None, "") else ""
    path = "" if mesh else dc.path_input(ctx, inputs.get("path"), "path")
    resp = _ok(client_for(s, "painter").open_project(path=path, mesh=mesh,
                                                     discard=bool(params.get("discard_changes"))), "ouverture Painter")
    return {"scene": str(resp.get("project") or "")}


@flow_node("dcc.sp_save_scene", "spSaveScene", icon="Save",
           inputs=[dc.EXEC, _SP],
           outputs=[dc.THEN, dc.ERR, port("path", "path", "Projet enregistre", "Saved project")],
           session="painter", live_only=True, effect=True,
           simulate=dc.sim(lambda i, p: "sauverait le projet en place", lambda i, p: {"path": ""}),
           shelf=235, aliases=["enregistrer", "save"],
           doc_fr="Enregistre le projet Painter en place (un projet jamais enregistre demande spSaveAs).",
           doc_en="Saves the Painter project in place (a never saved project needs spSaveAs).")
def sp_save_scene(ctx, inputs, params):
    resp = _ok(client_for(dc.need_session(ctx, inputs), "painter").save(), "enregistrement Painter")
    return {"path": str(resp.get("project") or "")}


@flow_node("dcc.sp_save_as", "spSaveAs", icon="SaveAll",
           inputs=[dc.EXEC, _SP, port("path", "path", "Nouveau nom du projet (.spp)", "New project name (.spp)",
                                      "$FLUX/PROJ/chair_tex.spp", required=True)],
           outputs=[dc.THEN, dc.ERR, port("path", "path", "Projet enregistre", "Saved project")],
           params=[port("copy", "bool", "Copie : le projet ouvert garde son nom", "Copy: the open project keeps its name",
                        False, default=False, wirable=False),
                   port("increment", "bool", "Ajoute _vNNN (version suivante libre)", "Adds _vNNN (next free version)",
                        False, default=False, wirable=False), _OVERWRITE],
           session="painter", live_only=True, effect=True, destructive=_D_OVERWRITE,
           simulate=dc.sim(lambda i, p: f"enregistrerait sous {i.get('path')}", lambda i, p: {"path": str(i.get("path") or "")},
                           "path"),
           shelf=236, aliases=["enregistrer sous", "save as", "version", "copie"],
           doc_fr="Enregistre le projet sous un autre nom (copy : le projet ouvert garde son nom ; increment : version "
                  "suivante libre).",
           doc_en="Saves the project under another name (copy: the open project keeps its name; increment: next free "
                  "version).")
def sp_save_as(ctx, inputs, params):
    s = dc.need_session(ctx, inputs)
    path = dc.path_input(ctx, inputs.get("path"), "path")
    if not path.lower().endswith(".spp"):
        raise NodeError("spSaveAs : un projet Painter finit par .spp", code="E_PARAM_INVALID")
    if params.get("increment"):
        path = _increment(path)
    _exists_guard(path, bool(params.get("overwrite")))
    resp = _ok(client_for(s, "painter").save_as(path, copy=bool(params.get("copy"))), "enregistrement Painter")
    return {"path": str(resp.get("project") or path)}


SP_USAGES = ["texture", "alpha", "environment", "smart_material", "smart_mask", "material", "brush", "filter",
             "generator"]


@flow_node("dcc.sp_import", "spImport", icon="FileInput",
           inputs=[dc.EXEC, _SP, port("path", "path", "Fichier a importer", "File to import",
                                      "$FLUX/PROJ/chair_mod.fbx", required=True)],
           outputs=[dc.THEN, dc.ERR, port("url", "str", "Ressource ajoutee (vide pour un mesh)",
                                          "Added resource (empty for a mesh)")],
           params=[port("kind", "str", "mesh = remplace le mesh du projet ; resource = ajoute a l'etagere du projet",
                        "mesh = replaces the project mesh; resource = adds to the project shelf", "resource",
                        default="resource", choices=["resource", "mesh"], wirable=False),
                   port("usage", "str", "Type de ressource (texture, alpha, smart_material...)",
                        "Resource type (texture, alpha, smart_material...)", "texture", default="texture",
                        choices=SP_USAGES, wirable=False)],
           session="painter", live_only=True, effect=True,
           simulate=dc.sim(lambda i, p: (f"remplacerait le mesh par {i.get('path')}" if p.get("kind") == "mesh"
                                         else f"importerait {i.get('path')} ({p.get('usage') or 'texture'})"),
                           lambda i, p: {"url": ""}, "path"),
           shelf=237, aliases=["importer", "import", "mesh", "texture", "ressource", "retake"],
           doc_fr="Importe dans le projet Painter ouvert : remplace le mesh (retake modelisation) ou ajoute une "
                  "ressource (texture, smart material...) a l'etagere du projet.",
           doc_en="Imports into the open Painter project: replaces the mesh (modeling retake) or adds a resource "
                  "(texture, smart material...) to the project shelf.")
def sp_import(ctx, inputs, params):
    s = dc.need_session(ctx, inputs)
    path = dc.path_input(ctx, inputs.get("path"), "path")
    if not Path(path).exists():
        raise NodeError(f"fichier introuvable : {path}")
    resp = _ok(client_for(s, "painter").import_file(path, kind=str(params.get("kind") or "resource"),
                                                    usage=str(params.get("usage") or "texture")), "import Painter")
    return {"url": str(resp.get("url") or "")}


run_script_node("painter", "sp", "Substance Painter", _SP, 238)


# == "bridge+" verbs shared by Mari, ZBrush, Designer and Marvelous (P6b step 9) ===============
# Same bridge protocol for all: {"action": open | save | save_as | import | run}. Painter has
# its own nodes above (first one done, validated live 2026-10-24).

def _verb(ctx, inputs, soft: str, payload: Dict[str, Any], what: str, timeout: float = 1800.0) -> Dict[str, Any]:
    client = client_for(dc.need_session(ctx, inputs), soft)
    if soft != "zbrush":
        return _ok(client.verb(payload, timeout), what)
    # ZBrush stays frozen between the verbs of one run (open then save...): released at the
    # end of the run, and right away on error.
    zbrush_released(ctx, client)
    try:
        return _ok(client.verb(payload, timeout), what)
    except Exception:
        try:
            client.release(timeout=2.0)
        except Exception:  # noqa: BLE001 - the run's cleanup tries again
            pass
        raise


def bridge_verb_nodes(soft: str, prefix: str, label: str, session_port: Any, shelf: int, *,
                      open_doc: tuple, open_example: str, mesh_new: bool, save_as_ext: tuple,
                      save_as_doc: tuple, save_as_example: str, copy_param: bool = True, discard_param: bool = True,
                      import_kinds: Optional[List[str]] = None, import_doc: tuple = ("", ""),
                      import_example: str = "") -> None:
    """dcc.<prefix>_{open_scene, save_scene, save_as, import, run_script} for one soft."""
    from flux_flows.bridges.session import RUN_SOFTS

    open_inputs = [dc.EXEC, session_port, port("path", "path", open_doc[0], open_doc[1], open_example)]
    if mesh_new:
        open_inputs.append(port("mesh", "path", "Mesh d'un nouveau projet (ignore path)",
                                "Mesh of a new project (path ignored)", "$FLUX/PROJ/chair_mod.obj"))

    @flow_node(f"dcc.{prefix}_open_scene", f"{prefix}OpenScene", icon="FolderOpen", inputs=open_inputs,
               outputs=[dc.THEN, dc.ERR, port("scene", "path", "Projet ouvert", "Opened project")],
               params=[port("discard_changes", "bool", "Perdre les modifications non enregistrees",
                            "Drop unsaved changes", False, default=False, wirable=False)] if discard_param else [],
               session=soft, live_only=True, effect=True,
               destructive={"param": "discard_changes", "equals": True} if discard_param else None,
               simulate=dc.sim(lambda i, p: f"creerait un projet depuis {i.get('mesh')}" if i.get("mesh")
                               else f"ouvrirait {i.get('path')}", lambda i, p: {"scene": str(i.get("path") or "")}),
               shelf=shelf, aliases=["ouvrir", "open", "projet", "scene"] + (["nouveau", "mesh"] if mesh_new else []),
               doc_fr=f"Ouvre un projet {label}" + (", ou en cree un depuis un mesh" if mesh_new else "")
                      + (". Refuse si le projet courant a des modifications non enregistrees, sauf discard_changes."
                         if discard_param else " (s'ajoute aux projets ouverts, rien n'est remplace)."),
               doc_en=f"Opens a {label} project" + (", or creates one from a mesh" if mesh_new else "")
                      + (". Refused when the current project has unsaved changes, unless discard_changes."
                         if discard_param else " (added to the open projects, nothing is replaced)."))
    def _open(ctx, inputs, params):
        mesh = ""
        if mesh_new and inputs.get("mesh") not in (None, ""):
            mesh = dc.path_input(ctx, inputs.get("mesh"), "mesh")
        path = ""
        if not mesh:
            raw = inputs.get("path")
            if raw in (None, ""):
                raise NodeError(f"{prefix}OpenScene : path" + (" ou mesh" if mesh_new else "") + " attendu")
            text = str(raw)
            # A Mari project is a name in its cache, not a path.
            path = text if (soft == "mari" and not text.lower().endswith(".mra")) else dc.path_input(ctx, raw, "path")
        resp = _verb(ctx, inputs, soft, {"action": "open", "path": path, "mesh": mesh,
                                         "discard": bool(params.get("discard_changes"))}, f"ouverture {label}")
        return {"scene": str(resp.get("project") or "")}

    @flow_node(f"dcc.{prefix}_save_scene", f"{prefix}SaveScene", icon="Save", inputs=[dc.EXEC, session_port],
               outputs=[dc.THEN, dc.ERR, port("path", "path", "Projet enregistre", "Saved project")],
               session=soft, live_only=True, effect=True,
               simulate=dc.sim(lambda i, p: "sauverait le projet en place", lambda i, p: {"path": ""}),
               shelf=shelf + 1, aliases=["enregistrer", "save"],
               doc_fr=f"Enregistre le projet {label} en place.", doc_en=f"Saves the {label} project in place.")
    def _save(ctx, inputs, params):
        resp = _verb(ctx, inputs, soft, {"action": "save"}, f"enregistrement {label}")
        return {"path": str(resp.get("project") or "")}

    as_params = [port("increment", "bool", "Ajoute _vNNN (version suivante libre)", "Adds _vNNN (next free version)",
                      False, default=False, wirable=False), _OVERWRITE]
    if copy_param:
        as_params.insert(0, port("copy", "bool", "Copie : le projet ouvert garde son nom",
                                 "Copy: the open project keeps its name", False, default=False, wirable=False))

    @flow_node(f"dcc.{prefix}_save_as", f"{prefix}SaveAs", icon="SaveAll",
               inputs=[dc.EXEC, session_port, port("path", "path", save_as_doc[0], save_as_doc[1], save_as_example,
                                                   required=True)],
               outputs=[dc.THEN, dc.ERR, port("path", "path", "Fichier enregistre", "Saved file")],
               params=as_params, session=soft, live_only=True, effect=True, destructive=_D_OVERWRITE,
               simulate=dc.sim(lambda i, p: f"enregistrerait sous {i.get('path')}",
                               lambda i, p: {"path": str(i.get("path") or "")}, "path"),
               shelf=shelf + 2, aliases=["enregistrer sous", "save as", "version", "copie"],
               doc_fr=save_as_doc[0] + " (increment : version suivante libre).",
               doc_en=save_as_doc[1] + " (increment: next free version).")
    def _save_as(ctx, inputs, params):
        path = dc.path_input(ctx, inputs.get("path"), "path")
        if not path.lower().endswith(save_as_ext):
            raise NodeError(f"{prefix}SaveAs : extension attendue {', '.join(save_as_ext)}", code="E_PARAM_INVALID")
        if params.get("increment"):
            path = _increment(path)
        _exists_guard(path, bool(params.get("overwrite")))
        resp = _verb(ctx, inputs, soft, {"action": "save_as", "path": path, "copy": bool(params.get("copy"))},
                     f"enregistrement {label}", timeout=4 * 3600.0)
        return {"path": str(resp.get("project") or path)}

    if import_kinds:
        @flow_node(f"dcc.{prefix}_import", f"{prefix}Import", icon="FileInput",
                   inputs=[dc.EXEC, session_port, port("path", "path", "Fichier a importer", "File to import",
                                                       import_example, required=True)],
                   outputs=[dc.THEN, dc.ERR],
                   params=[port("kind", "str", import_doc[0], import_doc[1], import_kinds[0], default=import_kinds[0],
                                choices=list(import_kinds), wirable=False)],
                   session=soft, live_only=True, effect=True,
                   simulate=dc.sim(lambda i, p: f"importerait {i.get('path')} ({p.get('kind') or import_kinds[0]})",
                                   None, "path"),
                   shelf=shelf + 3, aliases=["importer", "import", "mesh", "retake"],
                   doc_fr=f"Importe un fichier dans {label} : " + import_doc[0] + ".",
                   doc_en=f"Imports a file into {label}: " + import_doc[1] + ".")
        def _import(ctx, inputs, params):
            path = dc.path_input(ctx, inputs.get("path"), "path")
            if not Path(path).exists():
                raise NodeError(f"fichier introuvable : {path}")
            _verb(ctx, inputs, soft, {"action": "import", "kind": str(params.get("kind") or import_kinds[0]),
                                      "path": path}, f"import {label}")
            return {}

    if soft in RUN_SOFTS:
        before = (lambda ctx, s: zbrush_released(ctx, client_for(s, soft))) if soft == "zbrush" else None
        run_script_node(soft, prefix, label, session_port, shelf + 4, before=before)


# == Substance Designer ===========================================================================

_SD = dc.session_port("designer", "Designer")


@flow_node("dcc.sd_export", "sdExport", icon="FileOutput",
           inputs=[dc.EXEC, _SD, port("path", "dir", "Dossier de sortie", "Output folder", "$FLUX/PROJ/textures/rock",
                                      required=True)],
           outputs=[dc.THEN, dc.ERR, port("files", "list[path]", "Fichiers ecrits", "Written files")],
           params=[port("graphs", "list[any]", "Graphs : {package, graph, outputs} (vide = le graph ouvert)",
                        "Graphs: {package, graph, outputs} (empty = the open graph)", []),
                   port("format", "str", "Format des maps", "Map format", "png", default="png"),
                   port("size", "int", "Largeur en pixels (vide = celle du graph)", "Width in pixels", 2048),
                   port("bit_depth", "str", "8, 16, 16f, 32f (vide = celle du graph)", "Bit depth", "16"),
                   port("maps", "bool", "Exporter les maps", "Export the maps", True, default=True, wirable=False),
                   port("sbsar", "bool", "Exporter le .sbsar", "Export the .sbsar", False, default=False, wirable=False),
                   port("sbs", "bool", "Copier le .sbs", "Copy the .sbs", False, default=False, wirable=False)],
           session="designer", live_only=True, effect=True,
           simulate=dc.sim(lambda i, p: f"exporterait vers {i.get('path')}", lambda i, p: {"files": []}, "path"),
           shelf=241, aliases=["exporter", "export", "sbsar", "maps"],
           doc_fr="Exporte les maps, le .sbsar et / ou le .sbs du graph ouvert (ou des graphs donnes) dans un dossier.",
           doc_en="Exports the maps, the .sbsar and / or the .sbs of the open graph (or the given graphs) to a folder.")
def sd_export(ctx, inputs, params):
    from dcc.substance_designer.designer_export import build_export_config

    s = dc.need_session(ctx, inputs)
    folder = _dir_input(ctx, inputs.get("path"))
    Path(folder).mkdir(parents=True, exist_ok=True)
    config = build_export_config(folder, params.get("graphs") or None, str(params.get("format") or "png"),
                                 params.get("size") or None, str(params.get("bit_depth") or "") or None,
                                 maps=params.get("maps", True) is not False, sbsar=bool(params.get("sbsar")),
                                 sbs=bool(params.get("sbs")))
    resp = _ok(client_for(s, "designer").export(config), "export Designer")
    return {"files": [str(f) for f in resp.get("files") or []]}


@flow_node("dcc.sd_info", "sdInfo", icon="Info",
           inputs=[dc.EXEC_OPT, _SD],
           outputs=[dc.THEN_OPT, port("info", "dict", "Packages, graphs, sorties ouverts", "Open packages, graphs, outputs")],
           session="designer", live_only=True, shelf=242, aliases=["info", "graphs", "packages"],
           doc_fr="Les packages et graphs ouverts dans Designer. Lecture.",
           doc_en="The packages and graphs open in Designer. Read only.")
def sd_info(ctx, inputs, params):
    skipped = dc.skip_read(ctx, inputs, {"info": {}})
    if skipped is not None:
        return skipped
    return {"info": _ok(client_for(dc.need_session(ctx, inputs), "designer").info(), "info Designer")}


def find_sbscooker() -> Optional[Path]:
    """sbscooker next to the Designer executable (configured or detected)."""
    name = "sbscooker.exe" if os.name == "nt" else "sbscooker"
    try:
        from features.launcher.launcher_core import _resolve_exe

        exe = _resolve_exe("substance_designer")
    except Exception:  # noqa: BLE001 - no config yet
        exe = None
    if not exe:
        return None
    start = Path(exe).parent
    for folder in (start, start.parent, start / "bin"):
        if (folder / name).is_file():
            return folder / name
    return None


@flow_node("dcc.sd_cook", "sdCook", icon="Flame",
           inputs=[dc.EXEC, port("session", "session[designer]", "Session Designer (facultative)",
                                 "Designer session (optional)"),
                   port("source", "path", "Package .sbs", ".sbs package", "$FLUX/PROJ/sbs/rock.sbs", required=True),
                   port("dest", "path", "Fichier .sbsar a ecrire", ".sbsar file to write", "$FLUX/PROJ/sbsar/rock.sbsar",
                        required=True)],
           outputs=[dc.THEN, dc.ERR, port("path", "path", ".sbsar ecrit", "Written .sbsar")],
           params=[_OVERWRITE], effect=True, destructive=_D_OVERWRITE,
           simulate=lambda ctx, i, p: {"lines": [{"kind": "dcc", "text_fr": f"cuirait {i.get('source')} en .sbsar",
                                                  "path": str(i.get("dest") or "")}],
                                       "outputs": {"path": str(i.get("dest") or "")}},
           shelf=243, aliases=["cuire", "cook", "sbsar", "sbscooker"],
           doc_fr="Cuit un .sbs en .sbsar avec sbscooker (a cote de Designer), sans ouvrir Designer.",
           doc_en="Cooks a .sbs into a .sbsar with sbscooker (next to Designer), without opening Designer.")
def sd_cook(ctx, inputs, params):
    source = Path(dc.path_input(ctx, inputs.get("source"), "source"))
    dest = Path(dc.path_input(ctx, inputs.get("dest"), "dest"))
    if not source.is_file():
        raise NodeError(f"package introuvable : {source}")
    if dest.suffix.lower() != ".sbsar":
        raise NodeError("dest doit finir par .sbsar")
    _exists_guard(str(dest), bool(params.get("overwrite")))
    cooker = find_sbscooker()
    if cooker is None:
        raise NodeError("sbscooker introuvable (a cote de Substance Designer : Parametres > Logiciels)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([str(cooker), "--inputs", str(source), "--output-path", str(dest.parent),
                        "--output-name", dest.stem], check=True, capture_output=True, timeout=600)
    except subprocess.CalledProcessError as exc:
        raise NodeError(f"sbscooker a echoue : {(exc.stderr or b'').decode('utf-8', 'replace')[-400:]}") from None
    except subprocess.TimeoutExpired:
        raise NodeError("sbscooker : timeout (600 s)") from None
    if not dest.is_file():
        raise NodeError("sbscooker n'a rien ecrit")
    return {"path": str(dest)}


# == Marvelous Designer ===========================================================================

_MVD = dc.session_port("marvelous", "Marvelous")


@flow_node("dcc.mvd_export", "mvdExport", icon="FileOutput",
           inputs=[dc.EXEC, _MVD, port("path", "dir", "Dossier de sortie", "Output folder", "$FLUX/PROJ/cloth/dress",
                                       required=True),
                   port("name", "str", "Nom des fichiers", "File name", "dress_sim", required=True)],
           outputs=[dc.THEN, dc.ERR, port("files", "list[path]", "Fichiers ecrits", "Written files")],
           params=[port("format", "str", "abc, obj, fbx, usd, zprj", "abc, obj, fbx, usd, zprj", "abc", default="abc"),
                   port("options", "dict", "Options d'export Marvelous", "Marvelous export options", {}),
                   port("with_zprj", "bool", "Ajouter le .zprj", "Add the .zprj", False, default=False, wirable=False)],
           session="marvelous", live_only=True, effect=True,
           simulate=dc.sim(lambda i, p: f"exporterait {i.get('name')} ({p.get('format') or 'abc'}) vers {i.get('path')}",
                           lambda i, p: {"files": []}, "path"),
           shelf=251, aliases=["exporter", "export", "abc", "cloth", "simulation"],
           doc_fr="Exporte le projet Marvelous ouvert (abc, obj, fbx, usd, zprj) dans un dossier.",
           doc_en="Exports the open Marvelous project (abc, obj, fbx, usd, zprj) to a folder.")
def mvd_export(ctx, inputs, params):
    from dcc.marvelous.marvelous_export import build_export_config

    s = dc.need_session(ctx, inputs)
    folder = _dir_input(ctx, inputs.get("path"))
    Path(folder).mkdir(parents=True, exist_ok=True)
    config = build_export_config(folder, dc.text_param(ctx, inputs.get("name"), "name"),
                                 str(params.get("format") or "abc"), params.get("options") or None,
                                 bool(params.get("with_zprj")))
    resp = _ok(client_for(s, "marvelous").export(config), "export Marvelous")
    for warning in resp.get("warnings") or []:
        ctx.log(str(warning), "warn")
    return {"files": [str(f) for f in resp.get("files") or []]}


@flow_node("dcc.mvd_import", "mvdImport", icon="FileInput",
           inputs=[dc.EXEC, _MVD, port("path", "path", "Fichier a importer (avatar, obj, abc...)", "File to import",
                                       "$FLUX/PROJ/ASSET/body_LAST.obj", required=True)],
           outputs=[dc.THEN, dc.ERR, port("nodes", "list[dcc_node]", "Fonction d'import utilisee", "Import function used")],
           params=[port("options", "dict", "Options d'import Marvelous", "Marvelous import options", {})],
           session="marvelous", live_only=True, effect=True,
           simulate=dc.sim(lambda i, p: f"importerait {i.get('path')}", lambda i, p: {"nodes": []}, "path"),
           shelf=252, aliases=["importer", "import", "avatar"],
           doc_fr="Importe un fichier dans la scene Marvelous ouverte.",
           doc_en="Imports a file into the open Marvelous scene.")
def mvd_import(ctx, inputs, params):
    s = dc.need_session(ctx, inputs)
    resp = _ok(client_for(s, "marvelous").import_file(dc.path_input(ctx, inputs.get("path"), "path"),
                                                      params.get("options") or None), "import Marvelous")
    return {"nodes": [str(resp.get("function") or "")] if resp.get("function") else []}


@flow_node("dcc.mvd_info", "mvdInfo", icon="Info",
           inputs=[dc.EXEC_OPT, _MVD],
           outputs=[dc.THEN_OPT, port("project", "str", "Projet ouvert", "Open project", "dress.zprj"),
                    port("formats", "list[str]", "Formats exportables", "Exportable formats")],
           session="marvelous", live_only=True, shelf=253, aliases=["info", "projet", "formats"],
           doc_fr="Le projet ouvert dans Marvelous et les formats qu'il sait exporter. Lecture.",
           doc_en="The project open in Marvelous and the formats it can export. Read only.")
def mvd_info(ctx, inputs, params):
    skipped = dc.skip_read(ctx, inputs, {"project": "", "formats": []})
    if skipped is not None:
        return skipped
    resp = _ok(client_for(dc.need_session(ctx, inputs), "marvelous").info(), "info Marvelous")
    return {"project": str(resp.get("project") or ""), "formats": [str(f) for f in resp.get("formats") or []]}


# == ZBrush =========================================================================================

_ZB = dc.session_port("zbrush", "ZBrush")
ZB_FORMATS = (".ztl", ".obj", ".fbx")


def zbrush_released(ctx, client) -> None:
    """ZBrush must never stay frozen: released after the call and at the end of the run."""
    ctx.add_cleanup(lambda: client.release(timeout=2.0))


@flow_node("dcc.zb_export", "zbExport", icon="FileOutput",
           inputs=[dc.EXEC, _ZB, port("path", "path", "Fichier de sortie (.ztl, .obj, .fbx)", "Output file",
                                      "$FLUX/PROJ/sculpt/head.ztl", required=True)],
           outputs=[dc.THEN, dc.ERR, port("files", "list[path]", "Fichier ecrit", "Written file")],
           params=[port("options", "dict", "Options d'export (obj, fbx)", "Export options (obj, fbx)", {}), _OVERWRITE],
           session="zbrush", live_only=True, effect=True, destructive=_D_OVERWRITE,
           simulate=dc.sim(lambda i, p: f"exporterait l'outil actif vers {i.get('path')}", lambda i, p: {"files": []},
                           "path"),
           shelf=261, aliases=["exporter", "export", "ztl", "obj", "fbx", "sculpt"],
           doc_fr="Exporte l'outil actif de ZBrush (.ztl, .obj, .fbx selon l'extension). ZBrush est toujours relache "
                  "apres, meme en cas d'erreur ou d'annulation.",
           doc_en="Exports the active ZBrush tool (.ztl, .obj, .fbx by extension). ZBrush is always released after, "
                  "even on error or cancel.")
def zb_export(ctx, inputs, params):
    s = dc.need_session(ctx, inputs)
    path = dc.path_input(ctx, inputs.get("path"), "path")
    ext = Path(path).suffix.lower()
    if ext not in ZB_FORMATS:
        raise NodeError(f"extension `{ext}` : {', '.join(ZB_FORMATS)}")
    _exists_guard(path, bool(params.get("overwrite")))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    client = client_for(s, "zbrush")
    zbrush_released(ctx, client)
    try:
        if ext == ".ztl":
            resp = client.export_ztl(path)
        elif ext == ".obj":
            resp = client.export_obj(path, params.get("options") or None)
        else:
            resp = client.export_fbx(path, params.get("options") or None)
        _ok(resp, "export ZBrush")
    finally:
        try:
            client.release(timeout=2.0)
        except Exception:  # noqa: BLE001 - the run's cleanup tries again
            pass
    return {"files": [path]}


@flow_node("dcc.zb_mesh_info", "zbMeshInfo", icon="Info",
           inputs=[dc.EXEC_OPT, _ZB],
           outputs=[dc.THEN_OPT, port("info", "dict", "Points, polygones, subtools de l'outil actif",
                                      "Points, polygons, subtools of the active tool")],
           session="zbrush", live_only=True, shelf=262, aliases=["info", "mesh", "polygones"],
           doc_fr="Points et polygones de l'outil actif de ZBrush. Lecture.",
           doc_en="Points and polygons of the active ZBrush tool. Read only.")
def zb_mesh_info(ctx, inputs, params):
    skipped = dc.skip_read(ctx, inputs, {"info": {}})
    if skipped is not None:
        return skipped
    return {"info": _ok(client_for(dc.need_session(ctx, inputs), "zbrush").get_mesh_info(), "info ZBrush")}


# == Mari ============================================================================================

_MARI = dc.session_port("mari", "Mari")


@flow_node("dcc.mari_export", "mariExport", icon="FileOutput",
           inputs=[dc.EXEC, _MARI, port("path", "dir", "Dossier de sortie", "Output folder", "$FLUX/PROJ/textures/chair",
                                        required=True)],
           outputs=[dc.THEN, dc.ERR, port("files", "list[path]", "Textures ecrites", "Written textures")],
           params=[port("format", "str", "tif, exr, png (auto = sans perte)", "tif, exr, png (auto = lossless)", "tif",
                        default="tif"),
                   port("channels", "list[str]", "Channels (vide = tous)", "Channels (empty = all)", ["BaseColor"]),
                   port("formats", "dict", "Format par channel", "Format per channel", {}),
                   port("sizes", "dict", "Taille par channel", "Size per channel", {})],
           session="mari", live_only=True, effect=True,
           simulate=dc.sim(lambda i, p: f"exporterait les channels vers {i.get('path')}", lambda i, p: {"files": []},
                           "path"),
           shelf=271, aliases=["exporter", "export", "textures", "udim"],
           doc_fr="Exporte les channels de la geo courante de Mari dans un dossier (un export a la fois).",
           doc_en="Exports the channels of Mari's current geo to a folder (one export at a time).")
def mari_export(ctx, inputs, params):
    s = dc.need_session(ctx, inputs)
    folder = _dir_input(ctx, inputs.get("path"))
    Path(folder).mkdir(parents=True, exist_ok=True)
    resp = _ok(client_for(s, "mari").export(folder, str(params.get("format") or "tif"), params.get("channels") or None,
                                            params.get("formats") or None, params.get("sizes") or None), "export Mari")
    return {"files": [str(f) for f in resp.get("files") or []]}


@flow_node("dcc.mari_info", "mariInfo", icon="Info",
           inputs=[dc.EXEC_OPT, _MARI],
           outputs=[dc.THEN_OPT, port("geo", "str", "Geo courante", "Current geo", "chair_geo"),
                    port("channels", "list[str]", "Channels", "Channels")],
           session="mari", live_only=True, shelf=272, aliases=["info", "channels", "geo"],
           doc_fr="La geo courante de Mari et ses channels. Lecture.",
           doc_en="Mari's current geo and its channels. Read only.")
def mari_info(ctx, inputs, params):
    skipped = dc.skip_read(ctx, inputs, {"geo": "", "channels": []})
    if skipped is not None:
        return skipped
    resp = _ok(client_for(dc.need_session(ctx, inputs), "mari").info(), "info Mari")
    channels = [c.get("name") if isinstance(c, dict) else str(c) for c in resp.get("channels") or []]
    return {"geo": str(resp.get("geo") or ""), "channels": channels}


bridge_verb_nodes("mari", "mari", "Mari", _MARI, 274,
                  open_doc=("Projet Mari : son nom dans le cache Mari, ou une archive .mra",
                            "Mari project: its name in the Mari cache, or a .mra archive"),
                  open_example="chair_tex", mesh_new=True, save_as_ext=(".mra",), copy_param=False,
                  save_as_doc=("Archive le projet Mari en .mra (le projet reste dans le cache, toujours une copie)",
                               "Archives the Mari project as .mra (the project stays in the cache, always a copy)"),
                  save_as_example="$FLUX/PROJ/chair_tex.mra", import_kinds=["image", "object", "version"],
                  import_doc=("image = dans l'Image Manager ; object = nouvel objet ; version = nouvelle version de "
                              "geometrie de l'objet courant (retake)",
                              "image = into the Image Manager; object = new object; version = new geometry version "
                              "of the current object (retake)"),
                  import_example="$FLUX/PROJ/chair_mod.obj")


bridge_verb_nodes("zbrush", "zb", "ZBrush", _ZB, 264,
                  open_doc=("Projet .zpr (remplace la scene, demande discard_changes) ou tool .ztl (ajoute un tool). "
                            "ZBrush doit attendre FLUX (Export FLUX clique)",
                            "Project .zpr (replaces the scene, needs discard_changes) or tool .ztl (adds a tool). "
                            "ZBrush must wait for FLUX (Export FLUX clicked)"),
                  open_example="$FLUX/PROJ/head_sculpt_v004.zpr", mesh_new=False, save_as_ext=(".zpr", ".ztl"),
                  save_as_doc=("Enregistre le projet (.zpr) ou le tool actif (.ztl, toujours une copie)",
                               "Saves the project (.zpr) or the active tool (.ztl, always a copy)"),
                  save_as_example="$FLUX/PROJ/head_sculpt.zpr", import_kinds=["mesh", "tool"],
                  import_doc=("mesh = dans le tool actif (Tool:Import, obj / fbx) ; tool = un .ztl charge comme "
                              "nouveau tool",
                              "mesh = into the active tool (Tool:Import, obj / fbx); tool = a .ztl loaded as a new "
                              "tool"),
                  import_example="$FLUX/PROJ/head_retopo.obj")


bridge_verb_nodes("designer", "sd", "Substance Designer", _SD, 245,
                  open_doc=("Package .sbs a charger (s'ajoute aux packages ouverts)",
                            "Package .sbs to load (added to the open packages)"),
                  open_example="$FLUX/PROJ/wood_planks_v002.sbs", mesh_new=False, discard_param=False,
                  save_as_ext=(".sbs",), copy_param=False,
                  save_as_doc=("Enregistre le package du graphe courant sous un nouveau .sbs (il devient son fichier)",
                               "Saves the current graph's package as a new .sbs (it becomes its file)"),
                  save_as_example="$FLUX/PROJ/wood_planks.sbs", import_kinds=["bitmap", "mesh"],
                  import_doc=("bitmap ou mesh lie dans les ressources du package du graphe courant",
                              "bitmap or mesh linked into the resources of the current graph's package"),
                  import_example="$FLUX/PROJ/wood_scan.png")


bridge_verb_nodes("marvelous", "mvd", "Marvelous Designer", _MVD, 255,
                  open_doc=("Projet .zprj (remplace la scene, demande discard_changes)",
                            "Project .zprj (replaces the scene, needs discard_changes)"),
                  open_example="$FLUX/PROJ/dress_cloth_v003.zprj", mesh_new=False, save_as_ext=(".zprj",),
                  copy_param=False,
                  save_as_doc=("Enregistre le projet Marvelous en .zprj", "Saves the Marvelous project as .zprj"),
                  save_as_example="$FLUX/PROJ/dress_cloth.zprj")
