# bridge.py — transport nodes (02_NODES §9). P6a.
#
# Thin nodes over flux_flows/bridges/primitives.py: mostly the leaves of the shipped
# DCC subflows (shipped/dcc/<soft>/), and the building blocks of an extension bridge
# (P6c). The protocol stays in the primitive, never in the node. Calls send
# something to a DCC: ``effect`` (simulated in a dry run, which never starts a soft);
# ScanPorts and BridgePing are readers (``exec?``).

from __future__ import annotations

from typing import Any, Dict

from flux_flows.nodes.contract import NodeError
from flux_flows.nodes.registry import flow_node, port

_EXEC = port("exec", "exec", required=True)
_EXEC_OPT = port("exec", "exec", "Optionnel : relie, la lecture se fait a cet endroit du flow",
                 "Optional: linked, the read runs at this point of the flow")
_THEN = port("then", "exec")
_THEN_OPT = port("then", "exec", "Suite (si exec est relie)", "Next step (when exec is linked)")
_ERR = port("on_error", "exec")
_SOFT = port("soft", "str", "Logiciel : maya, houdini, nuke, painter, designer, marvelous, zbrush, mari",
             "Software: maya, houdini, nuke, painter, designer, marvelous, zbrush, mari", "houdini", required=True)
_PORT = port("port", "int", "Port du bridge (vide = port de base du logiciel)", "Bridge port (empty = base port)",
             48884)
_TIMEOUT = port("timeout_s", "float", "Delai maximal en secondes", "Maximum delay in seconds", 60, default=60)


def _prim():
    from flux_flows.bridges import primitives

    return primitives


def _run(fn, *args, **kwargs):
    """A primitive call: BridgeError / ValueError become the node's error message."""
    from flux_flows.bridges.primitives import BridgeError

    try:
        return fn(*args, **kwargs)
    except (BridgeError, ValueError) as exc:
        raise NodeError(str(exc)) from None


def _port(value: Any) -> Any:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        raise NodeError(f"port invalide `{value}`") from None


def _sim_send(what: str):
    def simulate(ctx, inputs, params):
        payload = inputs.get("payload") or inputs.get("body") or inputs.get("code") or inputs.get("args")
        return {"lines": [{"kind": "bridge", "text_fr": f"enverrait {what} : {str(payload)[:160]}"}],
                "outputs": {"response": {}, "result": None}}
    return simulate


@flow_node("bridge.scan_ports", "ScanPorts", icon="Radar",
           inputs=[_EXEC_OPT, _SOFT],
           outputs=[_THEN_OPT, port("instances", "list[dict]", "Instances ouvertes : id, port, pid, scene, version",
                                    "Open instances: id, port, pid, scene, version"),
                    port("count", "int", "Nombre d'instances", "Number of instances", 1)],
           shelf=150, aliases=["instances", "ports", "scan", "logiciels ouverts"],
           doc_fr="Liste les instances ouvertes d'un logiciel sur ce poste (ports de son bridge). Lecture.",
           doc_en="Lists the open instances of a software on this workstation (its bridge ports). Read only.")
def scan_ports(ctx, inputs, params):
    found = _run(_prim().scan_ports, str(inputs.get("soft") or ""))
    return {"instances": found, "count": len(found)}


def _sim_launch(ctx, inputs, params):
    scene = inputs.get("scene")
    return {"lines": [{"kind": "launch", "text_fr": f"lancerait {inputs.get('soft')}" + (f" avec {scene}" if scene else ""),
                       "path": str(scene) if scene else None}],
            "outputs": {"launched": False}}


@flow_node("bridge.launch", "Launch", icon="Rocket",
           inputs=[_EXEC, _SOFT, port("scene", "path", "Scene a ouvrir (optionnel)", "Scene to open (optional)",
                                       "$FLUX/PROJ/shot010_v003.hip")],
           outputs=[_THEN, _ERR, port("launched", "bool", "Vrai si le logiciel a demarre", "True when started", True)],
           effect=True, simulate=_sim_launch, shelf=151, aliases=["lancer", "ouvrir logiciel", "start"],
           doc_fr="Lance un logiciel detache de FLUX (fermer FLUX ne le ferme pas), avec une scene si donnee.",
           doc_en="Starts a software detached from FLUX (closing FLUX does not close it), with a scene if given.")
def launch(ctx, inputs, params):
    scene = inputs.get("scene")
    if scene:
        from flux_flows.nodes.common import as_path

        scene = str(as_path(ctx, scene, "scene"))
    ok = _run(_prim().launch, str(inputs.get("soft") or ""), scene)
    if not ok:
        raise NodeError(f"{inputs.get('soft')} : executable introuvable (Parametres > Logiciels)")
    ctx.log(f"{inputs.get('soft')} lance" + (f" sur {scene}" if scene else ""))
    return {"launched": True}


def _sim_wait(ctx, inputs, params):
    return {"lines": [{"kind": "skip", "text_fr": f"attendrait le bridge {inputs.get('soft')} (saute en essai a blanc)"}],
            "outputs": {"version": "", "port": _port(inputs.get("port")) or 0}}


@flow_node("bridge.wait_ready", "WaitReady", icon="HeartPulse",
           inputs=[_EXEC, _SOFT, _PORT],
           outputs=[_THEN, _ERR, port("version", "str", "Version du logiciel", "Software version", "20.5.410"),
                    port("port", "int", "Port qui a repondu", "Port that answered", 48884)],
           params=[_TIMEOUT, port("poll_s", "float", "Premier intervalle entre deux pings", "First delay between pings",
                                  1, default=1)],
           effect=True, simulate=_sim_wait, shelf=152, aliases=["attendre", "pret", "ready"],
           doc_fr="Attend que le bridge du logiciel reponde (ping de plus en plus espace) ; sans port, le premier "
                  "port de sa plage qui repond.",
           doc_en="Waits until the software bridge answers (pings further and further apart); without a port, the "
                  "first port of its range that answers.")
def wait_ready(ctx, inputs, params):
    got = _run(_prim().wait_ready, str(inputs.get("soft") or ""), _port(inputs.get("port")),
               timeout=float(params.get("timeout_s") or 60), poll=float(params.get("poll_s") or 1),
               cancelled=ctx.cancelled, any_port=inputs.get("port") in (None, ""))
    return {"version": got.get("version") or "", "port": got.get("port")}


@flow_node("bridge.ping", "BridgePing", icon="HeartPulse",
           inputs=[_EXEC_OPT, _SOFT, _PORT],
           outputs=[_THEN_OPT, port("ok", "bool", "Vrai si le bridge repond", "True when the bridge answers", True),
                    port("version", "str", "Version du logiciel", "Software version", "2024.2")],
           shelf=153, aliases=["ping", "connecte", "alive"],
           doc_fr="Le bridge du logiciel repond-il ? Lecture, ne leve pas d'erreur (ok faux).",
           doc_en="Does the software bridge answer? Read only, never fails (ok false).")
def bridge_ping(ctx, inputs, params):
    got = _run(_prim().ping, str(inputs.get("soft") or ""), _port(inputs.get("port")))
    return {"ok": bool(got.get("ok")), "version": got.get("version") or ""}


@flow_node("bridge.tcp_json_call", "TcpJsonCall", icon="Cable",
           inputs=[_EXEC, port("payload", "dict", "Requete JSON (une ligne)", "JSON request (one line)",
                               {"cmd": "ping"}, required=True)],
           outputs=[_THEN, _ERR, port("response", "dict", "Reponse JSON", "JSON answer", {"ok": True})],
           params=[port("host", "str", "Hote", "Host", "127.0.0.1", default="127.0.0.1"),
                   port("port", "int", "Port du bridge", "Bridge port", 7020, required=True), _TIMEOUT],
           effect=True, simulate=_sim_send("la requete TCP"), shelf=154, aliases=["tcp", "json", "socket"],
           doc_fr="Envoie une requete JSON (une ligne) a un bridge TCP et rend sa reponse.",
           doc_en="Sends a one line JSON request to a TCP bridge and returns its answer.")
def tcp_json_call(ctx, inputs, params):
    payload = inputs.get("payload")
    if not isinstance(payload, dict):
        raise NodeError("payload : dictionnaire attendu")
    return {"response": _run(_prim().tcp_json_call, _port(params.get("port")), payload,
                             host=str(params.get("host") or "127.0.0.1"),
                             timeout=float(params.get("timeout_s") or 60))}


@flow_node("bridge.http_call", "HttpCall", icon="Globe",
           inputs=[_EXEC, port("body", "dict", "Corps JSON (POST)", "JSON body (POST)", {"code": "result = hou.frame()"})],
           outputs=[_THEN, _ERR, port("response", "dict", "Reponse JSON", "JSON answer", {"ok": True})],
           params=[port("port", "int", "Port HTTP", "HTTP port", 48884, required=True),
                   port("path", "str", "Chemin (/run, /state, /ping)", "Path (/run, /state, /ping)", "/run",
                        required=True),
                   port("method", "str", "GET ou POST", "GET or POST", "POST", default="POST", choices=("POST", "GET")),
                   _TIMEOUT],
           effect=True, simulate=_sim_send("la requete HTTP"), shelf=155, aliases=["http", "houdini", "rest"],
           doc_fr="Requete HTTP JSON vers un bridge facon Houdini (127.0.0.1).",
           doc_en="JSON HTTP request to a Houdini style bridge (127.0.0.1).")
def http_call(ctx, inputs, params):
    return {"response": _run(_prim().http_call, _port(params.get("port")), str(params.get("path") or ""),
                             inputs.get("body") or {}, method=str(params.get("method") or "POST"),
                             timeout=float(params.get("timeout_s") or 60))}


@flow_node("bridge.command_port_call", "CommandPortCall", icon="SquareTerminal",
           inputs=[_EXEC, port("code", "str", "Code Python envoye a Maya", "Python code sent to Maya",
                               "cmds.ls(sl=True)", required=True)],
           outputs=[_THEN, _ERR, port("response", "str", "Reponse brute du commandPort", "Raw commandPort answer")],
           params=[port("port", "int", "Port du commandPort", "commandPort port", 7001, required=True), _TIMEOUT],
           effect=True, simulate=_sim_send("le code"), shelf=156, aliases=["maya", "commandport", "mel"],
           doc_fr="Envoie du code Python au commandPort de Maya et rend la reponse brute.",
           doc_en="Sends Python code to the Maya commandPort and returns the raw answer.")
def command_port_call(ctx, inputs, params):
    return {"response": _run(_prim().command_port_call, _port(params.get("port")), str(inputs.get("code") or ""),
                             timeout=float(params.get("timeout_s") or 60))}


@flow_node("bridge.file_mailbox_call", "FileMailboxCall", icon="Mailbox",
           inputs=[_EXEC, port("payload", "dict", "Requete JSON", "JSON request", {"action": "info"}, required=True)],
           outputs=[_THEN, _ERR, port("response", "dict", "Reponse JSON", "JSON answer", {"ok": True})],
           params=[port("mailbox_dir", "dir", "Dossier de la boite (vide = Marvelous)", "Mailbox folder (empty = Marvelous)",
                        ""), _TIMEOUT],
           effect=True, simulate=_sim_send("la requete par fichiers"), shelf=157,
           aliases=["marvelous", "fichiers", "mailbox", "boite"],
           doc_fr="Envoie une requete par une boite a fichiers (protocole Marvelous) et attend la reponse.",
           doc_en="Sends a request through a file mailbox (Marvelous protocol) and waits for the answer.")
def file_mailbox_call(ctx, inputs, params):
    payload = inputs.get("payload")
    if not isinstance(payload, dict):
        raise NodeError("payload : dictionnaire attendu")
    return {"response": _run(_prim().file_mailbox_call, payload, mailbox_dir=params.get("mailbox_dir") or None,
                             timeout=float(params.get("timeout_s") or 60))}


@flow_node("bridge.com_call", "ComCall", icon="Component",
           inputs=[_EXEC, port("args", "dict", "Arguments nommes de la methode", "Named arguments of the method", {})],
           outputs=[_THEN, _ERR, port("result", "any", "Valeur rendue", "Returned value")],
           params=[port("prog_id", "str", "Objet COM (Photoshop.Application)", "COM object", "Photoshop.Application",
                        required=True),
                   port("method", "str", "Methode ou propriete", "Method or property", "Version", required=True)],
           effect=True, simulate=_sim_send("l'appel COM"), shelf=158, aliases=["com", "photoshop", "windows"],
           doc_fr="Appelle une methode d'une application Windows deja ouverte par COM (ne la lance jamais).",
           doc_en="Calls a method of an already open Windows application through COM (never starts it).")
def com_call(ctx, inputs, params):
    result = _run(_prim().com_call, str(params.get("prog_id") or ""), str(params.get("method") or ""),
                  inputs.get("args") or {})
    try:
        import json

        json.dumps(result)
    except (TypeError, ValueError):
        result = str(result)
    return {"result": result}
