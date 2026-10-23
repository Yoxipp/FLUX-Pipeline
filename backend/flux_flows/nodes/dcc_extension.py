# dcc_extension.py — the nodes of the extension bridges (P6c, 00_LOGIQUE n°18: same
# transport nodes as the shipped softs).
#
#   session.ext_instance_core   core of every <Soft>Instance of an extension (param `soft`),
#                               hidden: the node is the team flow <prefix>_instance
#                               (node_type session.<prefix>_instance) made from the template
#   dcc.ext_run_script          Python in any extension soft (session[*]); `path` (or a
#                               temporary file when `temp_ext` is set) reaches the code as
#                               args["path"]: the publish template saves the scene there,
#                               then flux.publish_file publishes it
# Live only (no headless, no farm for the extensions). The code runs in the soft through the
# dcc_side script (bridges/templates/): same trust as the team's Python nodes.

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from flux_flows.nodes import dcc_common as dc
from flux_flows.nodes.contract import NodeError
from flux_flows.nodes.dcc_houdini import _script_code
from flux_flows.nodes.registry import flow_node, port

MODES = ("live_connect_or_open", "live_connect_only")


def _soft(params):
    from flux_flows.bridges import softs

    name = str(params.get("soft") or "").strip()
    if not name:
        raise NodeError("soft vide : le nom du bridge d'extension (bridge.yml)", code="E_PARAM_INVALID")
    try:
        spec = softs.get(name)
    except ValueError as exc:
        raise NodeError(str(exc), code="E_PARAM_INVALID") from None
    if not spec.extension:
        raise NodeError(f"`{name}` est un logiciel livre : utilise son node Instance", code="E_PARAM_INVALID")
    return spec


def _instance_simulate(ctx, inputs, params):
    try:
        spec = _soft(params)
    except NodeError as exc:
        return {"lines": [{"kind": "warn", "text_fr": str(exc)}],
                "outputs": {"session": None, "scene": "", "version": "", "state": "skipped"}}
    return dc.instance_simulate(ctx, inputs, params, spec)


@flow_node("session.ext_instance_core", "ExtensionInstanceCore", icon="Plug", internal=True,
           inputs=[dc.EXEC, port("scene", "path", "Scene : ouverte au lancement, ou cherchee avec pick scene",
                                 "Scene: opened at start, or looked for with pick scene", "$FLUX/PROJ/shot010.max")],
           outputs=[dc.THEN, dc.ERR, port("session", "session[*]", "Session du logiciel", "Software session"),
                    port("scene", "path", "Scene ouverte", "Open scene"),
                    port("version", "str", "Version du bridge ou du logiciel", "Bridge or software version"),
                    port("state", "str", "live, ou skipped en essai a blanc", "live, or skipped in a dry run", "live")],
           params=[port("soft", "str", "Logiciel : `soft` du bridge.yml", "Software: `soft` of bridge.yml", "max",
                        required=True, wirable=False),
                   port("mode", "str", "live_connect_or_open : se connecte, sinon ouvre ; live_connect_only",
                        "live_connect_or_open: connect, else open; live_connect_only", "live_connect_or_open",
                        default="live_connect_or_open", choices=MODES, wirable=False),
                   port("pick", "str", "Quelle instance : active (la premiere), scene, pid",
                        "Which instance: active (the first one), scene, pid", "active", default="active",
                        choices=("active", "scene", "pid"), wirable=False),
                   port("pid", "int", "Process vise (pick pid)", "Target process (pick pid)", 12345),
                   port("wait_s", "float", "Attente du bridge apres ouverture (s)",
                        "Wait for the bridge after opening (s)", 60, default=60)],
           shelf=290, aliases=["session", "instance", "extension", "bridge", "connecter", "ouvrir"],
           effect=True, simulate=_instance_simulate,
           doc_fr="Session d'un logiciel ajoute en extension (bridge.yml) : se connecte a l'instance ouverte, "
                  "sinon ouvre le logiciel (exe_hints) et attend son bridge. Live seulement.",
           doc_en="Session of a software added as an extension (bridge.yml): connects to the open instance, "
                  "else opens the software (exe_hints) and waits for its bridge. Live only.")
def ext_instance_core(ctx, inputs, params):
    return dc.instance_body(ctx, inputs, params, _soft(params), MODES)


def _run_simulate(ctx, inputs, params):
    shown = str(inputs.get("script") or inputs.get("code") or "")[:200]
    line = dc.SKIPPED_FR if inputs.get("session") is None else f"n'execute pas : {shown}"
    ext = str(params.get("temp_ext") or "")
    path = str(inputs.get("path") or "") or (f"<fichier temporaire{ext}>" if ext else "")
    return {"lines": [{"kind": "dcc", "text_fr": line}], "outputs": {"result": None, "log": "", "path": path}}


@flow_node("dcc.ext_run_script", "ExtRunScript", icon="FileCode",
           inputs=[dc.EXEC, port("session", "session[*]", "Session du logiciel (Instance d'extension)",
                                 "Software session (extension Instance)", required=True),
                   port("script", "path", "Fichier .py a executer", "Python file to run", "$FLUX/CONFIG/scripts/x.py"),
                   port("code", "str", "Code Python (si pas de script) ; affecte `result` pour rendre une valeur",
                        "Python code (when no script); assign `result` to return a value", "result = 1"),
                   port("args", "dict", "Valeurs lisibles par le code dans `args`", "Values the code reads in `args`",
                        {"frame": 1001}),
                   port("path", "path", "Fichier donne au code dans args[\"path\"]", "File given to the code as "
                        "args[\"path\"]", "$FLUX/PROJ/work/shot010.max")],
           outputs=[dc.THEN, dc.ERR, port("result", "any", "Valeur de `result`", "Value of `result`"),
                    port("log", "str", "Journal", "Log"),
                    port("path", "path", "args[\"path\"] (le fichier temporaire si temp_ext)",
                         "args[\"path\"] (the temporary file with temp_ext)")],
           params=[port("timeout_s", "float", "Delai maximal (s)", "Maximum delay (s)", 600, default=600),
                   port("temp_ext", "str", "Sans `path` : un fichier temporaire de cette extension (.max), "
                        "supprime a la fin du run", "Without `path`: a temporary file with this extension "
                        "(.max), removed at the end of the run", ".max", default="")],
           effect=True, destructive=True, simulate=_run_simulate, shelf=291,
           aliases=["script", "python", "code", "executer", "extension"],
           doc_fr="Execute du Python dans un logiciel ajoute en extension (fichier ou code) ; `args` donne des "
                  "valeurs au code, `result` rend une valeur, args[\"path\"] un fichier (temporaire avec temp_ext : "
                  "le modele de publish y enregistre la scene). Code libre : destructif par prudence.",
           doc_en="Runs Python in a software added as an extension (file or code); `args` gives values to the "
                  "code, `result` returns a value, args[\"path\"] a file (temporary with temp_ext: the publish "
                  "template saves the scene there). Free code: destructive by caution.")
def ext_run_script(ctx, inputs, params):
    s = dc.need_session(ctx, inputs)
    path = dc.path_input(ctx, inputs.get("path"), "path", required=False)
    ext = str(params.get("temp_ext") or "").strip()
    if not path and ext:
        if not ext.startswith(".") or "/" in ext or "\\" in ext:
            raise NodeError(f"temp_ext `{ext}` : une extension comme .max", code="E_PARAM_INVALID")
        folder = Path(tempfile.mkdtemp(prefix=f"flux_flows_{s.soft}_"))
        ctx.add_cleanup(lambda: shutil.rmtree(folder, ignore_errors=True))
        path = str(folder / f"{s.soft}_scene{ext}")
    args = inputs.get("args")
    args = dict(args) if isinstance(args, dict) else ({} if args is None else args)
    if path:
        if not isinstance(args, dict):
            raise NodeError("args : dictionnaire attendu")
        args["path"] = path
    code = _script_code(ctx, {**inputs, "args": args})
    resp = s.run(code, float(params.get("timeout_s") or 600))
    if not resp.get("ok"):
        raise NodeError(str(resp.get("error") or "le script a echoue"))
    if path and ext and not Path(path).is_file():
        raise NodeError(f"le script n'a pas ecrit {path} (args[\"path\"])")
    return {"result": resp.get("result"), "log": str(resp.get("trace") or ""), "path": path}
