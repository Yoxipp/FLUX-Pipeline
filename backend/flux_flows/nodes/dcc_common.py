# dcc_common.py — what every DCC node shares (02_NODES §8). P6a.
#
#   instance_node(soft)   registers session.<prefix>_instance (<Soft>Instance): modes
#                         live_connect_or_open (default), live_connect_only, headless, farm (V2)
#   need_session()        the session input, a NodeError when there is none
#   call()                session.run(code) -> `result`, a NodeError on failure
#   skip_read()           dry run without an open instance: a reader gives empty outputs
#   sim()                 simulate() of an effect node: one report line, simulated outputs
#
# The dry run never starts a soft nor a worker (01 §5): an Instance without an open
# instance gives a null session and the DCC nodes behind it are skipped (one line each);
# an open live instance serves the readers, never the effects.

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional

from flux_flows.nodes.contract import NodeError
from flux_flows.nodes.registry import flow_node, port

EXEC = port("exec", "exec", required=True)
EXEC_OPT = port("exec", "exec", "Optionnel : relie, la lecture se fait a cet endroit du flow",
                "Optional: linked, the read runs at this point of the flow")
THEN = port("then", "exec")
THEN_OPT = port("then", "exec", "Suite (si exec est relie)", "Next step (when exec is linked)")
ERR = port("on_error", "exec")
SKIPPED_FR = "saute (essai a blanc) : aucune instance ouverte"


def session_port(soft: str, label: str) -> Any:
    return port("session", f"session[{soft}]", f"Session {label} (node {label}Instance)",
                f"{label} session ({label}Instance node)", required=True)


def need_session(ctx, inputs: Dict[str, Any]):
    from flux_flows.bridges.session import Session

    s = inputs.get("session")
    if s is None:
        raise NodeError("Pas de session : l'Instance n'a rien ouvert" + (" (essai a blanc)" if ctx.dry else ""))
    if not isinstance(s, Session):
        raise NodeError("`session` n'est pas une session de logiciel (relie un node Instance)")
    return s


def call(session, code: str, timeout: float = 600.0) -> Any:
    from flux_flows.bridges.primitives import BridgeError

    try:
        return session.call(code, timeout)
    except BridgeError as exc:
        raise NodeError(str(exc)) from None


def bridge(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """A primitive / session call whose BridgeError becomes the node's message."""
    from flux_flows.bridges.primitives import BridgeError

    try:
        return fn(*args, **kwargs)
    except (BridgeError, ValueError) as exc:
        raise NodeError(str(exc)) from None


def skip_read(ctx, inputs: Dict[str, Any], empty: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Dry run without a session: *empty* (logged), else None (the reader runs)."""
    if inputs.get("session") is None and ctx.dry:
        ctx.log(SKIPPED_FR)
        return dict(empty)
    return None


def sim(text: Callable[[Dict[str, Any], Dict[str, Any]], str], outputs: Callable[..., Dict[str, Any]] = None,
        path_key: Optional[str] = None):
    """simulate() of an effect DCC node: "saute" without a session, else *text*."""
    def simulate(ctx, inputs, params):
        outs = outputs(inputs, params) if outputs else {}
        if inputs.get("session") is None:
            return {"lines": [{"kind": "skip", "text_fr": SKIPPED_FR}], "outputs": outs}
        line = {"kind": "dcc", "text_fr": text(inputs, params)}
        if path_key and inputs.get(path_key):
            line["path"] = str(inputs.get(path_key))
        return {"lines": [line], "outputs": outs}
    return simulate


def literal(value: Any) -> str:
    """A Python literal for code sent to a soft (JSON round trip: str, numbers, lists, dicts)."""
    return f"__import__('json').loads({json.dumps(json.dumps(value))})"


def text_param(ctx, value: Any, what: str, required: bool = True) -> str:
    text = "" if value is None else str(value).strip()
    if required and not text:
        raise NodeError(f"`{what}` vide")
    return text


def path_input(ctx, value: Any, what: str = "chemin", required: bool = True) -> str:
    """A path for the soft (forward slashes), $FLUX resolved on this workstation."""
    from flux_flows.nodes.common import as_path

    if value in (None, "") and not required:
        return ""
    return str(as_path(ctx, value, what)).replace("\\", "/")


def frame_range(value: Any) -> Optional[tuple]:
    """'1001-1050', '1001 1050 2', [1001, 1050] -> (start, end, step); empty = None."""
    if value in (None, "", []):
        return None
    if isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        parts = str(value).replace("-", " ").replace(",", " ").split()
    try:
        nums = [int(float(p)) for p in parts]
    except (TypeError, ValueError):
        raise NodeError(f"frame_range invalide `{value}` (ex. 1001-1050)") from None
    if len(nums) == 2:
        nums.append(1)
    if len(nums) != 3 or nums[2] == 0:
        raise NodeError(f"frame_range invalide `{value}` (ex. 1001-1050)")
    return tuple(nums)


# -- the Instance node of a soft ---------------------------------------------------------

def _scene(ctx, inputs) -> str:
    return path_input(ctx, inputs.get("scene"), "scene", required=False)


def instance_body(ctx, inputs, params, spec, modes):
    """Run of an Instance core (shipped softs and extension bridges, P6c)."""
    from flux_flows.bridges import headless as hl
    from flux_flows.bridges import session as sess

    mode = str(params.get("mode") or "live_connect_or_open")
    if mode == "farm":
        raise NodeError("mode farm : reserve a la V2 (Tractor)")
    if mode not in modes:
        raise NodeError(f"mode inconnu `{mode}` ({', '.join(modes)})")
    scene = _scene(ctx, inputs)
    if mode == "headless":
        template = path_input(ctx, inputs.get("template"), "template", required=False)
        s = bridge(hl.start_worker, spec.soft, scene or template, cancelled=ctx.cancelled)
        ctx.add_cleanup(s.close)
        ctx.log(f"{spec.headless} lance (pid {s.pid}) : une licence {spec.label} pour la duree du run")
        state = "headless"
    else:
        s = bridge(sess.connect_live, spec.soft, mode=mode, pick=str(params.get("pick") or "active"),
                   scene=scene, pid=params.get("pid"), wait_s=float(params.get("wait_s") or 60),
                   cancelled=ctx.cancelled, log=ctx.log)
        state = "live"
    return {"session": s, "scene": s.scene, "version": s.version, "state": state}


def instance_simulate(ctx, inputs, params, spec):
    """Dry run of an Instance core: never opens a soft, connects to an open one for the readers."""
    from flux_flows.bridges import session as sess

    mode = str(params.get("mode") or "live_connect_or_open")
    scene = _scene(ctx, inputs)
    empty = {"session": None, "scene": scene, "version": "", "state": "skipped"}
    if mode == "headless":
        return {"lines": [{"kind": "licence", "text_fr": f"lancerait {spec.headless} (1 licence {spec.label}), "
                           "saute en essai a blanc"}], "outputs": empty}
    try:
        inst = sess.find_instance(spec.soft, pick=str(params.get("pick") or "active"), scene=scene,
                                  pid=params.get("pid"))
    except Exception as exc:  # noqa: BLE001 - a dry run reports, never fails on a scan
        inst, why = None, str(exc)
    else:
        why = ""
    if inst is not None:
        try:
            s = sess.live_session(spec.soft, inst.get("port"), inst.get("pid"))
            s.scene = sess.scene_of(spec.soft, s.port) if s.port else ""
            return {"lines": [{"kind": "dcc", "text_fr": f"se connecterait a {s.label} (lectures seulement "
                               "en essai a blanc)"}],
                    "outputs": {"session": s, "scene": s.scene, "version": "", "state": "live"}}
        except Exception as exc:  # noqa: BLE001
            why = str(exc)
    text = (f"aucune instance {spec.label} : le run echouerait (live_connect_only)" if mode == "live_connect_only"
            else f"ouvrirait {spec.label}" + (f" avec {scene}" if scene else "") + ", saute en essai a blanc")
    return {"lines": [{"kind": "dcc", "text_fr": text + (f" ({why})" if why else ""), "path": scene or None}],
            "outputs": empty}


def mode_labels(spec, modes) -> dict:
    """Readable menu entries of the Instance modes (R1 retake 4), in MODES order."""
    worker = spec.headless or "worker"
    labels = {
        "live_connect_or_open": ("Se connecter ou ouvrir (defaut)", "Connect or open (default)"),
        "live_connect_only": ("Se connecter seulement", "Connect only"),
        "headless": (f"Sans interface ({worker}, 1 licence)", f"No UI ({worker}, 1 licence)"),
        "farm": ("Farm (V2, indisponible)", "Farm (V2, unavailable)"),
    }
    return {m: labels[m] for m in modes if m in labels}


PICK_LABELS = {
    "active": ("Instance active (choisie dans FLUX)", "Active instance (chosen in FLUX)"),
    "scene": ("Celle qui a la scene ouverte", "The one with the scene open"),
    "pid": ("Par process (pid)", "By process (pid)"),
}


def instance_node(soft: str, *, icon: str, shelf: int, headless: bool = True) -> None:
    """Register session.<prefix>_instance_core for *soft* (decision 24, 02 §8): the Python core of
    the <Soft>Instance node, which is the locked subflow around it."""
    from flux_flows.bridges import softs
    from flux_flows.bridges.session import MODES, PICKS

    spec = softs.get(soft)
    label = spec.label.replace(" ", "")
    modes = MODES if headless else tuple(m for m in MODES if m != "headless")

    def body(ctx, inputs, params):
        return instance_body(ctx, inputs, params, spec, modes)

    def simulate(ctx, inputs, params):
        return instance_simulate(ctx, inputs, params, spec)

    # The core leaf of the shipped locked subflow shipped/dcc/<soft>/<prefix>_instance.flow.yml
    # (node_type session.<prefix>_instance, dcc_nodes.py): hidden from Tab / Shelf.
    flow_node(f"session.{spec.prefix}_instance_core", f"{label}InstanceCore", icon=icon, internal=True,
              inputs=[EXEC, port("scene", "path", "Scene : ouverte au lancement, ou cherchee avec pick scene",
                                 "Scene: opened at start, or looked for with pick scene", "$FLUX/PROJ/shot010_v003"),
                      *([port("template", "path", "Headless : scene de depart si pas de scene",
                              "Headless: starting scene when no scene", "$FLUX/CONFIG/templates/lookdev.hip")]
                        if headless else [])],
              outputs=[THEN, ERR, port("session", f"session[{spec.soft}]", f"Session {spec.label}",
                                       f"{spec.label} session"),
                       port("scene", "path", "Scene ouverte", "Open scene"),
                       port("version", "str", "Version du logiciel", "Software version"),
                       port("state", "str", "live, headless, ou skipped en essai a blanc",
                            "live, headless, or skipped in a dry run", "live")],
              params=[port("mode", "str", "live_connect_or_open : se connecte, sinon ouvre ; live_connect_only ; "
                                          "headless : sans interface (licence) ; farm : V2",
                           "live_connect_or_open: connect, else open; live_connect_only; headless: no UI "
                           "(licence); farm: V2", "live_connect_or_open", default="live_connect_or_open",
                           choices=modes, wirable=False, labels=mode_labels(spec, modes),
                           reserved=[m for m in modes if m == "farm"]),
                      port("pick", "str", "Quelle instance : active (choisie dans FLUX), scene, pid",
                           "Which instance: active (chosen in FLUX), scene, pid", "active", default="active",
                           choices=PICKS, wirable=False, labels=PICK_LABELS),
                      port("pid", "int", "Process vise (pick pid)", "Target process (pick pid)", 12345),
                      port("wait_s", "float", "Attente du bridge apres ouverture (s)", "Wait for the bridge after "
                           "opening (s)", 60, default=60)],
              shelf=shelf, aliases=["session", "instance", spec.soft, spec.label.lower(), "connecter", "ouvrir"],
              effect=True, simulate=simulate, session=None,
              licence={"param": "mode", "equals": "headless"} if headless else None,
              doc_fr=f"Session {spec.label} : se connecte a l'instance ouverte (choisie dans FLUX, par scene ou "
                     f"par process), sinon ouvre {spec.label} et attend son bridge ; en headless, lance "
                     f"{spec.headless or 'un worker'} sans interface (une licence pour tout le run, ferme a la fin).",
              doc_en=f"{spec.label} session: connects to the open instance (chosen in FLUX, by scene or by "
                     f"process), else opens {spec.label} and waits for its bridge; headless starts "
                     f"{spec.headless or 'a worker'} without UI (one licence for the whole run, closed at the end).",
              )(body)
