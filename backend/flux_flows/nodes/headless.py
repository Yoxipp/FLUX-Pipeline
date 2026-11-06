# headless.py — RunHeadless and Batch (02_NODES §6, P6a): a script in hython / mayapy
# without UI. One worker per scene (flux_flows/bridges/headless.py), closed right after:
# each launch takes a licence for its duration (W_LICENCE). A dry run starts nothing.

from __future__ import annotations

from typing import Any, Dict, List

from flux_flows.nodes import dcc_common as dc
from flux_flows.nodes.contract import NodeError
from flux_flows.nodes.registry import flow_node, port

HEADLESS_SOFTS = ("houdini", "maya")
_SOFT = port("soft", "str", "houdini (hython) ou maya (mayapy)", "houdini (hython) or maya (mayapy)", "houdini",
             default="houdini", choices=HEADLESS_SOFTS, wirable=False)
_ARGS = port("args", "dict", "Valeurs lisibles par le script dans `args`", "Values the script reads in `args`",
             {"frame": 1001})
_TIMEOUT = port("timeout_s", "float", "Delai maximal par scene (s)", "Maximum delay per scene (s)", 600, default=600)


def _script(ctx, value: Any) -> str:
    from flux_flows.nodes.common import as_path

    path = as_path(ctx, value, "script")
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise NodeError(f"script illisible {path} : {exc}") from None


def run_once(ctx, soft: str, scene: str, code: str, args: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    """Start a worker on *scene*, run *code* with ``args``, close it. {"ok", "result", "error", "log"}."""
    from flux_flows.bridges import headless

    try:
        session = headless.start_worker(soft, scene, cancelled=ctx.cancelled)
    except Exception as exc:  # noqa: BLE001 - BridgeError and OS errors are the item's error
        return {"ok": False, "scene": scene, "error": str(exc), "log": ""}
    try:
        resp = session.run(f"args = {dc.literal(args or {})}\n" + code, timeout)
    finally:
        session.close()
    try:
        log = session.log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
    except OSError:
        log = ""
    out = {"ok": bool(resp.get("ok")), "scene": scene, "log": log}
    out["result" if resp.get("ok") else "error"] = resp.get("result") if resp.get("ok") else resp.get("error")
    return out


def _sim_one(ctx, inputs, params):
    soft = str(params.get("soft") or "houdini")
    exe = "hython" if soft == "houdini" else "mayapy"
    scene = inputs.get("scene") or "scene vide"
    return {"lines": [{"kind": "licence", "text_fr": f"lancerait {exe} {inputs.get('script')} sur {scene} (1 licence)"}],
            "outputs": {"result": {}, "log": ""}}


@flow_node("action.run_headless", "RunHeadless", icon="Terminal",
           inputs=[dc.EXEC, port("scene", "path", "Scene ouverte avant le script (vide = scene vide)",
                                 "Scene opened before the script (empty = empty scene)", "$FLUX/PROJ/fx_v004.hip"),
                   port("script", "path", "Script Python ; affecte `result` pour rendre une valeur",
                        "Python script; assign `result` to return a value", "$FLUX/CONFIG/scripts/cache.py",
                        required=True)],
           outputs=[dc.THEN, dc.ERR, port("result", "dict", "Valeur de `result` (dict, sinon {value})",
                                          "Value of `result` (dict, else {value})"),
                    port("log", "str", "Sortie du logiciel", "Software output")],
           params=[_SOFT, _ARGS, _TIMEOUT], effect=True, simulate=_sim_one, licence=True, shelf=160,
           aliases=["headless", "hython", "mayapy", "batch", "sans interface"],
           doc_fr="Lance un script Python dans hython ou mayapy (sans interface) sur une scene, puis ferme le "
                  "process. Une licence du logiciel pendant le script.",
           doc_en="Runs a Python script in hython or mayapy (no UI) on a scene, then closes the process. One "
                  "licence of the software during the script.")
def run_headless(ctx, inputs, params):
    soft = str(params.get("soft") or "houdini")
    if soft not in HEADLESS_SOFTS:
        raise NodeError(f"soft `{soft}` : houdini ou maya")
    scene = dc.path_input(ctx, inputs.get("scene"), "scene", required=False)
    got = run_once(ctx, soft, scene, _script(ctx, inputs.get("script")), params.get("args") or {},
                   float(params.get("timeout_s") or 600))
    if not got["ok"]:
        raise NodeError(f"{soft} headless : {got.get('error')}")
    result = got.get("result")
    return {"result": result if isinstance(result, dict) else {"value": result}, "log": got.get("log") or ""}


def _sim_batch(ctx, inputs, params):
    scenes = inputs.get("scenes") or []
    soft = str(params.get("soft") or "houdini")
    exe = "hython" if soft == "houdini" else "mayapy"
    return {"lines": [{"kind": "licence", "text_fr": f"{len(scenes)} scene(s), {len(scenes)} lancement(s) de {exe} "
                                                     f"({inputs.get('script')})"}],
            "outputs": {"results": [], "failed": 0}}


@flow_node("action.batch", "Batch", icon="Layers",
           inputs=[dc.EXEC, port("scenes", "list[path]", "Scenes a traiter", "Scenes to process", required=True),
                   port("script", "path", "Script Python lance sur chaque scene", "Python script run on each scene",
                        "$FLUX/CONFIG/scripts/cache.py", required=True)],
           outputs=[dc.THEN, dc.ERR, port("results", "list[dict]", "Un resultat par scene : scene, ok, result / error",
                                          "One result per scene: scene, ok, result / error"),
                    port("failed", "int", "Scenes en echec", "Failed scenes", 0)],
           params=[_SOFT, _ARGS, _TIMEOUT,
                   port("on_item_error", "str", "stop : s'arrete a la premiere erreur ; continue : passe a la suite",
                        "stop: stops at the first error; continue: goes on", "stop", default="stop",
                        choices=("stop", "continue"), wirable=False),
                   port("mode", "str", "sequentiel (parallele : V2)", "sequential (parallel: V2)", "sequential",
                        default="sequential", choices=("sequential",), wirable=False)],
           effect=True, simulate=_sim_batch, licence=True, shelf=161,
           aliases=["batch", "lot", "scenes", "headless", "hython", "mayapy"],
           doc_fr="Lance le meme script sur une liste de scenes, une apres l'autre, chacune dans son process hython / "
                  "mayapy ; s'arrete a la premiere erreur ou continue.",
           doc_en="Runs the same script on a list of scenes, one after the other, each in its own hython / mayapy "
                  "process; stops at the first error or goes on.")
def batch(ctx, inputs, params):
    soft = str(params.get("soft") or "houdini")
    if soft not in HEADLESS_SOFTS:
        raise NodeError(f"soft `{soft}` : houdini ou maya")
    scenes = inputs.get("scenes") or []
    if not isinstance(scenes, list):
        raise NodeError("scenes : liste de chemins attendue")
    code = _script(ctx, inputs.get("script"))
    results: List[Dict[str, Any]] = []
    for value in scenes:
        if ctx.cancelled.is_set():
            raise NodeError("annule")
        scene = dc.path_input(ctx, value, "scene")
        got = run_once(ctx, soft, scene, code, params.get("args") or {}, float(params.get("timeout_s") or 600))
        got.pop("log", None)
        results.append(got)
        ctx.log(f"{scene} : {'ok' if got['ok'] else got.get('error')}", "info" if got["ok"] else "error")
        if not got["ok"] and params.get("on_item_error", "stop") != "continue":
            raise NodeError(f"{scene} : {got.get('error')} (arret a la premiere erreur)")
    return {"results": results, "failed": sum(1 for r in results if not r["ok"])}
