# dcc_houdini.py — HoudiniInstance and the hou* nodes (02_NODES §8.2). P6a.
#
# Every node talks to Houdini through the session's run(code): the live server
# (HoudiniClient /run) or the hython worker, same code. Export / save / ROP cooks reuse
# dcc/houdini/houdini_export.py with client=session (P6a refactor); imports reuse
# houdini_import.py. The code sent assigns ``result``. A dcc_node value is a node path.
# houPublish (black box, run_houdini_publish_action in a thread) is in dcc_publish.py.

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from flux_flows.nodes import dcc_common as dc
from flux_flows.nodes.contract import NodeError
from flux_flows.nodes.registry import flow_node, port

SOFT = "houdini"
_S = dc.session_port(SOFT, "Houdini")
_NODE = port("node", "dcc_node", "Node Houdini (chemin)", "Houdini node (path)", "/obj/geo1/OUT")
_NODE_REQ = port("node", "dcc_node", "Node Houdini (chemin)", "Houdini node (path)", "/obj/geo1/OUT", required=True)
_OVERWRITE = port("overwrite", "bool", "Ecraser un fichier existant", "Overwrite an existing file", False,
                  default=False, wirable=False)
_D_OVERWRITE = {"param": "overwrite", "equals": True}
SCENE_EXTS = (".hip", ".hiplc", ".hipnc")

dc.instance_node(SOFT, icon="Flame", shelf=170)


def _exists_guard(path: str, overwrite: bool) -> None:
    if Path(path).exists() and not overwrite:
        raise NodeError(f"{path} existe deja : coche overwrite pour l'ecraser")


def _resp(resp: Dict[str, Any], what: str) -> Dict[str, Any]:
    if not resp.get("ok"):
        raise NodeError(f"{what} : {resp.get('error') or 'echec'}")
    return resp.get("result") or {}


# -- scenes ------------------------------------------------------------------------------

@flow_node("dcc.hou_open_scene", "houOpenScene", icon="FolderOpen",
           inputs=[dc.EXEC, _S, port("path", "path", "Scene a ouvrir (.hip)", "Scene to open (.hip)",
                                     "$FLUX/PROJ/shot010_fx_v003.hip")],
           outputs=[dc.THEN, dc.ERR, port("scene", "path", "Scene ouverte", "Opened scene")],
           params=[port("new", "bool", "Scene vide (ignore path)", "Empty scene (path ignored)", False, default=False,
                        wirable=False),
                   port("discard_changes", "bool", "Perdre les modifications non enregistrees",
                        "Drop unsaved changes", False, default=False, wirable=False)],
           session="houdini", effect=True, destructive={"param": "discard_changes", "equals": True},
           simulate=dc.sim(lambda i, p: "viderait la scene" if p.get("new") else f"ouvrirait {i.get('path')}",
                           lambda i, p: {"scene": str(i.get("path") or "")}, "path"),
           shelf=171, aliases=["ouvrir", "open", "load", "hip"],
           doc_fr="Ouvre une scene dans Houdini (ou une scene vide). Refuse si la scene courante a des "
                  "modifications non enregistrees, sauf discard_changes.",
           doc_en="Opens a scene in Houdini (or an empty one). Refused when the current scene has unsaved "
                  "changes, unless discard_changes.")
def hou_open_scene(ctx, inputs, params):
    s = dc.need_session(ctx, inputs)
    new = bool(params.get("new"))
    path = "" if new else dc.path_input(ctx, inputs.get("path"), "path")
    code = (f"_discard = {bool(params.get('discard_changes'))!r}\n"
            "if hou.hipFile.hasUnsavedChanges() and not _discard:\n"
            "    raise RuntimeError('scene modifiee non enregistree : enregistre-la ou coche discard_changes')\n"
            + ("hou.hipFile.clear(suppress_save_prompt=True)\n" if new else
               f"hou.hipFile.load({path!r}, suppress_save_prompt=True, ignore_load_warnings=True)\n")
            + "result = hou.hipFile.path()\n")
    return {"scene": str(dc.call(s, code))}


@flow_node("dcc.hou_save_scene", "houSaveScene", icon="Save",
           inputs=[dc.EXEC, _S, port("path", "path", "Vide = en place ; sinon enregistre sous ce nom",
                                     "Empty = in place; else saved under this name", "")],
           outputs=[dc.THEN, dc.ERR, port("path", "path", "Scene enregistree", "Saved scene")],
           params=[_OVERWRITE], session="houdini", effect=True, destructive=_D_OVERWRITE,
           simulate=dc.sim(lambda i, p: f"sauverait la scene" + (f" sous {i.get('path')}" if i.get("path") else
                                                                 " en place"),
                           lambda i, p: {"path": str(i.get("path") or "")}, "path"),
           shelf=172, aliases=["enregistrer", "save", "sauver"],
           doc_fr="Enregistre la scene Houdini en place, ou sous un autre nom (.hip, .hiplc, .hipnc).",
           doc_en="Saves the Houdini scene in place, or under another name (.hip, .hiplc, .hipnc).")
def hou_save_scene(ctx, inputs, params):
    from dcc.houdini.houdini_export import export_scene

    s = dc.need_session(ctx, inputs)
    if inputs.get("path") in (None, ""):
        return {"path": str(dc.call(s, "hou.hipFile.save()\nresult = hou.hipFile.path()\n"))}
    path = dc.path_input(ctx, inputs.get("path"), "path")
    ext = Path(path).suffix.lower() or ".hip"
    if ext not in SCENE_EXTS:
        raise NodeError(f"extension de scene inconnue `{ext}` ({', '.join(SCENE_EXTS)})")
    _exists_guard(path, bool(params.get("overwrite")))
    return {"path": str(_resp(export_scene(path, ext, client=s), "houSaveScene").get("path") or path)}


def _increment(path: str) -> str:
    """<stem>_vNNN<ext>: the next free version in the folder (proposition 02 §8)."""
    import re

    p = Path(path)
    stem = re.sub(r"_v\d+$", "", p.stem)
    nums = [int(m.group(1)) for f in p.parent.glob(f"{stem}_v*{p.suffix}")
            if (m := re.match(rf"^{re.escape(stem)}_v(\d+)$", f.stem))]
    return str(p.with_name(f"{stem}_v{(max(nums) + 1) if nums else 1:03d}{p.suffix}")).replace("\\", "/")


@flow_node("dcc.hou_save_as", "houSaveAs", icon="SaveAll",
           inputs=[dc.EXEC, _S, port("path", "path", "Nouveau nom de la scene", "New scene name",
                                     "$FLUX/PROJ/shot010_fx.hip", required=True)],
           outputs=[dc.THEN, dc.ERR, port("path", "path", "Scene enregistree", "Saved scene")],
           params=[port("copy", "bool", "Copie : la scene ouverte garde son nom", "Copy: the open scene keeps its name",
                        False, default=False, wirable=False),
                   port("increment", "bool", "Ajoute _vNNN (version suivante libre)", "Adds _vNNN (next free version)",
                        False, default=False, wirable=False), _OVERWRITE],
           session="houdini", effect=True, destructive=_D_OVERWRITE,
           simulate=dc.sim(lambda i, p: f"enregistrerait sous {i.get('path')}" + (" (copie)" if p.get("copy") else ""),
                           lambda i, p: {"path": str(i.get("path") or "")}, "path"),
           shelf=173, aliases=["enregistrer sous", "save as", "copie", "version"],
           doc_fr="Enregistre la scene sous un autre nom ; copy garde le nom de la scene ouverte, increment ajoute "
                  "la version suivante libre (_v001, _v002...).",
           doc_en="Saves the scene under another name; copy keeps the open scene name, increment adds the next "
                  "free version (_v001, _v002...).")
def hou_save_as(ctx, inputs, params):
    s = dc.need_session(ctx, inputs)
    path = dc.path_input(ctx, inputs.get("path"), "path")
    if params.get("increment"):
        path = _increment(path)
    _exists_guard(path, bool(params.get("overwrite")))
    code = ("import pathlib\n_before = hou.hipFile.path()\n"
            f"pathlib.Path({path!r}).parent.mkdir(parents=True, exist_ok=True)\n"
            f"hou.hipFile.save({path!r})\n"
            + ("hou.hipFile.setName(_before)\n" if params.get("copy") else "")
            + f"result = {path!r}\n")
    return {"path": str(dc.call(s, code))}


# -- code --------------------------------------------------------------------------------

def _script_code(ctx, inputs) -> str:
    code = inputs.get("code")
    if inputs.get("script") not in (None, ""):
        from flux_flows.nodes.common import as_path

        script = as_path(ctx, inputs.get("script"), "script")
        try:
            code = script.read_text(encoding="utf-8")
        except OSError as exc:
            raise NodeError(f"script illisible {script} : {exc}") from None
    code = str(code or "")
    if not code.strip():
        raise NodeError("RunScript attend `code` ou `script`")
    args = inputs.get("args") or {}
    if not isinstance(args, dict):
        raise NodeError("args : dictionnaire attendu")
    return f"args = {dc.literal(args)}\n" + code


def run_script_node(soft: str, prefix: str, label: str, session_port: Any, shelf: int, before: Any = None) -> None:
    """dcc.<prefix>_run_script for *soft* (Houdini and Maya share it). *before(ctx, session)*
    runs first (ZBrush: release it at the end of the run)."""

    def simulate(ctx, inputs, params):
        shown = str(inputs.get("script") or inputs.get("code") or "")[:200]
        line = dc.SKIPPED_FR if inputs.get("session") is None else f"n'execute pas : {shown}"
        return {"lines": [{"kind": "dcc", "text_fr": line}], "outputs": {"result": None, "log": ""}}

    @flow_node(f"dcc.{prefix}_run_script", f"{prefix}RunScript", icon="FileCode",
               inputs=[dc.EXEC, session_port, port("script", "path", "Fichier .py a executer", "Python file to run",
                                                   "$FLUX/CONFIG/scripts/cleanup.py"),
                       port("code", "str", "Code Python (si pas de script) ; affecte `result` pour rendre une valeur",
                            "Python code (when no script); assign `result` to return a value",
                            "result = len(hou.selectedNodes())"),
                       port("args", "dict", "Valeurs lisibles par le code dans `args`", "Values the code reads in `args`",
                            {"frame": 1001})],
               outputs=[dc.THEN, dc.ERR, port("result", "any", "Valeur de `result`", "Value of `result`"),
                        port("log", "str", "Journal", "Log")],
               params=[port("timeout_s", "float", "Delai maximal (s)", "Maximum delay (s)", 600, default=600)],
               session=soft, effect=True, destructive=True, simulate=simulate, shelf=shelf,
               aliases=["script", "python", "code", "executer"],
               doc_fr=f"Execute du Python dans {label} (fichier ou code) ; `args` donne des valeurs au code, `result` "
                      "rend une valeur. Code libre : destructif par prudence.",
               doc_en=f"Runs Python in {label} (file or code); `args` gives values to the code, `result` returns "
                      "a value. Free code: destructive by caution.")
    def _run_script(ctx, inputs, params):
        s = dc.need_session(ctx, inputs)
        if before is not None:
            before(ctx, s)
        resp = s.run(_script_code(ctx, inputs), float(params.get("timeout_s") or 600))
        if not resp.get("ok"):
            raise NodeError(str(resp.get("error") or "le script a echoue"))
        return {"result": resp.get("result"), "log": str(resp.get("trace") or "")}


run_script_node(SOFT, "hou", "Houdini", _S, 174)


# -- export / import ---------------------------------------------------------------------

@flow_node("dcc.hou_export", "houExport", icon="FileOutput",
           inputs=[dc.EXEC, _S, port("path", "path", "Fichier de sortie", "Output file", "$FLUX/PROJ/geo/rock.bgeo.sc",
                                     required=True), _NODE],
           outputs=[dc.THEN, dc.ERR, port("files", "list[path]", "Fichiers ecrits", "Written files")],
           params=[port("format", "str", "Extension (vide = celle du chemin) : .bgeo.sc .abc .usd .fbx .obj",
                        "Extension (empty = the path's): .bgeo.sc .abc .usd .fbx .obj", ".abc"),
                   port("frame_range", "str", "Plage (1001-1050) : un fichier anime pour abc / usd",
                        "Range (1001-1050): one animated file for abc / usd", "1001-1050"),
                   port("scope", "str", "Sans node : selection (premier node selectionne)",
                        "Without node: selection (first selected node)", "selection", default="selection",
                        choices=("selection",), wirable=False),
                   port("options", "dict", "Parms du ROP a regler", "ROP parms to set", {"trange": 1}), _OVERWRITE],
           session="houdini", effect=True, destructive=_D_OVERWRITE,
           simulate=dc.sim(lambda i, p: f"exporterait {i.get('node') or 'la selection'} vers {i.get('path')}",
                           lambda i, p: {"files": [str(i.get("path"))] if i.get("path") else []}, "path"),
           shelf=175, aliases=["exporter", "export", "abc", "bgeo", "usd", "cache"],
           doc_fr="Exporte un node (ou le premier node selectionne) vers un fichier : reutilise le ROP ou en cree un "
                  "(geometry, alembic, usd), regle la sortie et le cuit.",
           doc_en="Exports a node (or the first selected node) to a file: reuses the ROP or creates one (geometry, "
                  "alembic, usd), sets the output and cooks it.")
def hou_export(ctx, inputs, params):
    from dcc.houdini.houdini_export import export_via_node

    s = dc.need_session(ctx, inputs)
    path = dc.path_input(ctx, inputs.get("path"), "path")
    name = Path(path).name.lower()
    ext = str(params.get("format") or (".bgeo.sc" if name.endswith(".bgeo.sc") else Path(path).suffix)).lower()
    ext = ext if ext.startswith(".") else "." + ext
    _exists_guard(path, bool(params.get("overwrite")))
    node = str(inputs.get("node") or "")
    if not node:
        selected = s.state().get("selected_nodes") if hasattr(s, "state") else None
        if selected is None:
            selected = dc.call(s, "result = [n.path() for n in hou.selectedNodes()]")
        if not selected:
            raise NodeError("aucun node : relie `node` ou selectionne un node dans Houdini")
        node = selected[0]
    _resp(export_via_node(node, ext, path, dc.frame_range(params.get("frame_range")), params.get("options") or None,
                          client=s), "houExport")
    return {"files": [path]}


@flow_node("dcc.hou_import", "houImport", icon="FileInput",
           inputs=[dc.EXEC, _S, port("path", "path", "Fichier a importer", "File to import",
                                     "$FLUX/PROJ/ASSET/chair_model_LAST.usd", required=True)],
           outputs=[dc.THEN, dc.ERR, port("nodes", "list[dcc_node]", "Nodes crees ou modifies", "Created or changed nodes")],
           params=[port("mode", "str", "node : node d'import dans `network` ; reference, payload, sublayer : LOP",
                        "node: import node in `network`; reference, payload, sublayer: LOP", "node", default="node",
                        choices=("node", "reference", "payload", "sublayer"), wirable=False),
                   port("network", "str", "Reseau du node d'import (mode node)", "Network of the import node (node mode)",
                        "/obj/geo1", default="/obj")],
           session="houdini", effect=True,
           simulate=dc.sim(lambda i, p: f"importerait {i.get('path')} ({p.get('mode') or 'node'})",
                           lambda i, p: {"nodes": []}, "path"),
           shelf=176, aliases=["importer", "import", "reference", "charger"],
           doc_fr="Importe un fichier dans Houdini : node d'import adapte a l'extension dans un reseau, ou "
                  "Reference / Payload / Sublayer dans un reseau LOP.",
           doc_en="Imports a file into Houdini: an import node fitting the extension in a network, or a "
                  "Reference / Payload / Sublayer in a LOP network.")
def hou_import(ctx, inputs, params):
    from dcc.houdini.houdini_import import create_import_node, import_into_lop

    s = dc.need_session(ctx, inputs)
    path = dc.path_input(ctx, inputs.get("path"), "path")
    mode = str(params.get("mode") or "node")
    if mode == "node":
        got = _resp(create_import_node(str(params.get("network") or "/obj"), path, client=s), "houImport")
    else:
        got = _resp(import_into_lop(path, mode, abs_path=path, client=s), "houImport")
    node = got.get("node_path") or got.get("node")
    return {"nodes": [node] if node else []}


# -- nodes and parms ---------------------------------------------------------------------

_FIND_CODE = ("_root = hou.node({root!r})\n"
              "if _root is None:\n    raise RuntimeError('reseau introuvable : {root}')\n"
              "result = [[n.path(), n.name(), n.type().name()] for n in _root.allSubChildren()]\n")


def _find(ctx, inputs, params) -> List[str]:
    from flux_flows.patterns import PatternError, mask

    s = dc.need_session(ctx, inputs)
    pattern = dc.text_param(ctx, params.get("pattern"), "pattern")
    rows = dc.call(s, _FIND_CODE.format(root=str(params.get("root") or "/")), 120) or []
    try:
        keep = mask(pattern, [r[1] for r in rows], case_sensitive=True)   # Houdini names are case sensitive
        type_pat = str(params.get("type") or "").strip()
        keep_t = mask(type_pat, [r[2] for r in rows], case_sensitive=True) if type_pat else [True] * len(rows)
    except PatternError as exc:
        raise NodeError(f"motif invalide : {exc.message}", code="E_PARAM_INVALID") from None
    return [r[0] for r, a, b in zip(rows, keep, keep_t) if a and b]


_FIND_PARAMS = [port("root", "str", "Reseau de depart", "Starting network", "/obj", default="/"),
                port("pattern", "pattern", "Motif sur le nom des nodes", "Pattern on node names", "*_OUT ^tmp*",
                     required=True, default="*"),
                port("type", "pattern", "Motif sur le type (geo, rop_geometry...)", "Pattern on the type", "rop_*")]


@flow_node("dcc.hou_find_node", "houFindNode", icon="Search",
           inputs=[dc.EXEC_OPT, _S],
           outputs=[dc.THEN_OPT, port("node", "dcc_node", "Premier node trouve", "First node found", "/obj/geo1/OUT"),
                    port("found", "bool", "Vrai si un node est trouve", "True when a node is found", True)],
           params=_FIND_PARAMS, session="houdini", shelf=177, aliases=["chercher", "find", "node"],
           doc_fr="Premier node dont le nom (et le type) passe le motif, sous `root`. Lecture.",
           doc_en="First node whose name (and type) passes the pattern, under `root`. Read only.")
def hou_find_node(ctx, inputs, params):
    skipped = dc.skip_read(ctx, inputs, {"node": "", "found": False})
    if skipped is not None:
        return skipped
    found = _find(ctx, inputs, params)
    return {"node": found[0] if found else "", "found": bool(found)}


@flow_node("dcc.hou_find_nodes", "houFindNodes", icon="ScanSearch",
           inputs=[dc.EXEC_OPT, _S],
           outputs=[dc.THEN_OPT, port("nodes", "list[dcc_node]", "Nodes trouves", "Nodes found"),
                    port("count", "int", "Nombre", "Count", 3)],
           params=_FIND_PARAMS, session="houdini", shelf=178, aliases=["chercher", "find", "nodes", "lister"],
           doc_fr="Tous les nodes dont le nom (et le type) passe le motif, sous `root`. Lecture.",
           doc_en="All nodes whose name (and type) passes the pattern, under `root`. Read only.")
def hou_find_nodes(ctx, inputs, params):
    skipped = dc.skip_read(ctx, inputs, {"nodes": [], "count": 0})
    if skipped is not None:
        return skipped
    found = _find(ctx, inputs, params)
    return {"nodes": found, "count": len(found)}


@flow_node("dcc.hou_cook_node", "houCookNode", icon="Flame",
           inputs=[dc.EXEC, _S, _NODE_REQ],
           outputs=[dc.THEN, dc.ERR, port("cooked", "bool", "Vrai une fois cuit", "True once cooked", True)],
           params=[port("wait", "bool", "Attendre la fin", "Wait for the end", True, default=True, wirable=False),
                   port("frame_range", "str", "Plage (ROP) : 1001-1050", "Range (ROP): 1001-1050", "1001-1050"),
                   port("force", "bool", "Forcer (node non ROP)", "Force (non ROP node)", False, default=False)],
           session="houdini", effect=True,
           simulate=dc.sim(lambda i, p: f"cuirait {i.get('node')}", lambda i, p: {"cooked": False}),
           shelf=179, aliases=["cuire", "cook", "rop", "calculer"],
           doc_fr="Cuit un node : un ROP est rendu (sur sa plage ou `frame_range`), un autre node est recalcule.",
           doc_en="Cooks a node: a ROP is rendered (on its range or `frame_range`), another node is recomputed.")
def hou_cook_node(ctx, inputs, params):
    from dcc.houdini.houdini_export import cook_rop

    s = dc.need_session(ctx, inputs)
    node = dc.text_param(ctx, inputs.get("node"), "node")
    is_rop = dc.call(s, f"_n = hou.node({node!r})\n"
                        f"if _n is None:\n    raise RuntimeError('node introuvable : {node}')\n"
                        # A ROP: /out (Driver) or a ROP inside a network (it has the execute button).
                        "result = _n.type().category().name() == 'Driver' or _n.parm('execute') is not None\n")
    if is_rop:
        _resp(cook_rop(node, dc.frame_range(params.get("frame_range")), client=s), "houCookNode")
    else:
        dc.call(s, f"hou.node({node!r}).cook(force={bool(params.get('force'))!r})\nresult = True\n")
    return {"cooked": True}


@flow_node("dcc.hou_render", "houRender", icon="Film",
           inputs=[dc.EXEC, _S, _NODE_REQ],
           outputs=[dc.THEN, dc.ERR, port("files", "list[path]", "Images ecrites", "Written images")],
           params=[port("frame_range", "str", "Plage : 1001-1050", "Range: 1001-1050", "1001-1050"),
                   port("output", "path", "Sortie ($F4 pour le numero d'image) ; vide = celle du ROP",
                        "Output ($F4 for the frame number); empty = the ROP's", "$FLUX/PROJ/render/beauty.$F4.exr"),
                   _OVERWRITE],
           session="houdini", effect=True, destructive=_D_OVERWRITE,
           simulate=dc.sim(lambda i, p: f"rendrait {i.get('node')}" + (f" vers {p.get('output')}" if p.get("output")
                                                                       else ""), lambda i, p: {"files": []}),
           shelf=180, aliases=["rendu", "render", "karma", "mantra", "images"],
           doc_fr="Rend un ROP (Karma, Mantra...) sur une plage, vers `output` si donne. Rend la liste des images "
                  "ecrites.",
           doc_en="Renders a ROP (Karma, Mantra...) on a range, to `output` when given. Returns the written images.")
def hou_render(ctx, inputs, params):
    from dcc.houdini.houdini_export import cook_rop, set_rop_output

    s = dc.need_session(ctx, inputs)
    node = dc.text_param(ctx, inputs.get("node"), "node")
    output = params.get("output")
    if output:
        output = dc.path_input(ctx, output, "output")
        _resp(set_rop_output(node, output, client=s), "houRender")
    fr = dc.frame_range(params.get("frame_range"))
    _resp(cook_rop(node, fr, client=s), "houRender")
    code = (f"_n = hou.node({node!r})\n_fr = {list(fr) if fr else None!r}\n"
            "_p = None\nfor _name in ('vm_picture', 'picture', 'sopoutput', 'outputimage', 'lopoutput'):\n"
            "    if _n.parm(_name) is not None:\n        _p = _n.parm(_name)\n        break\n"
            "if _fr:\n    _r = _fr\n"
            "elif _n.parm('f1') is not None:\n"
            "    _r = [int(_n.parm('f1').eval()), int(_n.parm('f2').eval()), int(_n.parm('f3').eval() or 1)]\n"
            "else:\n    _r = [int(hou.frame()), int(hou.frame()), 1]\n"
            "result = [] if _p is None else sorted({_p.evalAtFrame(_f) for _f in range(_r[0], _r[1] + 1, _r[2] or 1)})\n")
    files = dc.call(s, code) or []
    return {"files": [f for f in files if Path(f).exists()] or list(files)}


@flow_node("dcc.hou_set_parm", "houSetParm", icon="SlidersHorizontal",
           inputs=[dc.EXEC, _S, _NODE_REQ, port("parm", "str", "Nom du parm", "Parm name", "tx", required=True),
                   port("value", "any", "Valeur", "Value", 1.5, required=True)],
           outputs=[dc.THEN, dc.ERR], session="houdini", effect=True,
           simulate=dc.sim(lambda i, p: f"mettrait {i.get('node')}.{i.get('parm')} = {i.get('value')!r}"),
           shelf=181, aliases=["parm", "parametre", "set", "regler"],
           doc_fr="Regle la valeur d'un parm d'un node Houdini.", doc_en="Sets the value of a parm of a Houdini node.")
def hou_set_parm(ctx, inputs, params):
    s = dc.need_session(ctx, inputs)
    node, parm = dc.text_param(ctx, inputs.get("node"), "node"), dc.text_param(ctx, inputs.get("parm"), "parm")
    dc.call(s, f"_p = hou.node({node!r}).parm({parm!r})\n"
               f"if _p is None:\n    raise RuntimeError('parm introuvable : {node}/{parm}')\n"
               f"_p.set({dc.literal(inputs.get('value'))})\nresult = True\n")
    return {}


@flow_node("dcc.hou_get_parm", "houGetParm", icon="Gauge",
           inputs=[dc.EXEC_OPT, _S, _NODE_REQ, port("parm", "str", "Nom du parm", "Parm name", "tx", required=True)],
           outputs=[dc.THEN_OPT, port("value", "any", "Valeur evaluee", "Evaluated value", 1.5)],
           session="houdini", shelf=182, aliases=["parm", "lire", "get", "valeur"],
           doc_fr="Lit la valeur evaluee d'un parm d'un node Houdini. Lecture.",
           doc_en="Reads the evaluated value of a parm of a Houdini node. Read only.")
def hou_get_parm(ctx, inputs, params):
    skipped = dc.skip_read(ctx, inputs, {"value": None})
    if skipped is not None:
        return skipped
    s = dc.need_session(ctx, inputs)
    node, parm = dc.text_param(ctx, inputs.get("node"), "node"), dc.text_param(ctx, inputs.get("parm"), "parm")
    return {"value": dc.call(s, f"_p = hou.node({node!r}).parm({parm!r})\n"
                                f"if _p is None:\n    raise RuntimeError('parm introuvable : {node}/{parm}')\n"
                                "result = _p.eval()\n")}


@flow_node("dcc.hou_selected", "houSelectedNodes", icon="Crosshair",
           inputs=[dc.EXEC_OPT, _S],
           outputs=[dc.THEN_OPT, port("nodes", "list[dcc_node]", "Nodes selectionnes", "Selected nodes")],
           session="houdini", live_only=True, shelf=183, aliases=["selection", "selected", "choisis"],
           doc_fr="Les nodes selectionnes dans Houdini (session Live). Lecture.",
           doc_en="The nodes selected in Houdini (Live session). Read only.")
def hou_selected(ctx, inputs, params):
    skipped = dc.skip_read(ctx, inputs, {"nodes": []})
    if skipped is not None:
        return skipped
    s = dc.need_session(ctx, inputs)
    return {"nodes": [str(n) for n in (dc.call(s, "result = [n.path() for n in hou.selectedNodes()]") or [])]}
