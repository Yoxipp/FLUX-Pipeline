# flow_templates.py — the flows of an extension bridge (P6c, 01 §12): its Instance node and
# its publish, written into the team scope (CONFIG/extensions/flows/) as team nodes
# (node_type, dcc_nodes.py), so they show in Tab / Shelf without rebuilding FLUX.
#
#   <prefix>_instance   node session.<prefix>_instance around session.ext_instance_core
#   <prefix>_publish    node dcc.<prefix>_publish: dcc.ext_run_script saves the scene into a
#                       temporary file (the save code is the team's: one line per soft), then
#                       flux.publish_file publishes it; checks go before the publish (01 §13)
# A bridge folder may ship its own flows/session.flow.yml and flows/publish.flow.yml: they
# are used instead of these templates. __SOFT__, __PREFIX__, __LABEL__, __EXT__ are replaced.
# Strings, not files: nothing more to bundle in backend.spec.

from __future__ import annotations

from typing import Dict, List, Optional

import yaml

from flux_flows.bridges.extension import Extension

INSTANCE = """\
flux_flow: 2
name: __PREFIX___instance
label: __LABELNS__Instance
description: "Session __LABEL__ (bridge d'extension) : se connecte a l'instance ouverte, sinon ouvre __LABEL__ et attend son bridge. Live seulement."
node_type: session.__PREFIX___instance
interface:
  inputs:
    - {id: mode, type: select, label: "Mode", default: live_connect_or_open, options: ["live_connect_or_open", "live_connect_only"]}
    - {id: pick, type: select, label: "Instance visee", default: active, options: ["active", "scene", "pid"]}
    - {id: scene, type: path, label: "Scene (ouverte au lancement, ou cherchee)", default: ""}
    - {id: pid, type: int, label: "Process (pick pid)"}
    - {id: wait_s, type: float, label: "Attente du bridge (s)", default: 60}
  outputs:
    - {id: session, type: "session[__SOFT__]", label: "Session __LABEL__"}
    - {id: scene, type: path, label: "Scene ouverte"}
    - {id: version, type: str, label: "Version du bridge"}
    - {id: state, type: str, label: "live ou skipped"}
nodes:
  ev: {type: event.manual, pos: [0, 160]}
  in_scene: {type: data.flow_input, pos: [0, 320], params: {id: scene}}
  in_pid: {type: data.flow_input, pos: [0, 440], params: {id: pid}}
  in_wait: {type: data.flow_input, pos: [0, 560], params: {id: wait_s}}
  core: {type: session.ext_instance_core, pos: [320, 160], params: {soft: __SOFT__, mode: "${mode}", pick: "${pick}"}}
  out_session: {type: subflow.flow_output, pos: [640, 160], params: {id: session}}
  out_scene: {type: subflow.flow_output, pos: [960, 160], params: {id: scene}}
  out_version: {type: subflow.flow_output, pos: [1280, 160], params: {id: version}}
  out_state: {type: subflow.flow_output, pos: [1600, 160], params: {id: state}}
links:
  - {from: ev.then, to: core.exec}
  - {from: in_scene.value, to: core.scene}
  - {from: in_pid.value, to: core.pid}
  - {from: in_wait.value, to: core.wait_s}
  - {from: core.then, to: out_session.exec}
  - {from: core.session, to: out_session.value}
  - {from: out_session.then, to: out_scene.exec}
  - {from: core.scene, to: out_scene.value}
  - {from: out_scene.then, to: out_version.exec}
  - {from: core.version, to: out_version.value}
  - {from: out_version.then, to: out_state.exec}
  - {from: core.state, to: out_state.value}
notes:
  - {id: k1, pos: [0, 720], text: "Node d'equipe cree depuis le bridge d'extension __SOFT__ (CONFIG/extensions/bridges/__SOFT__/bridge.yml)."}
"""

PUBLISH = """\
flux_flow: 2
name: __PREFIX___publish
label: __PREFIX__Publish
description: "Publish __LABEL__ (bridge d'extension) : enregistre la scene dans un fichier temporaire __EXT__ puis la publie (vNNN + LAST). Le code d'enregistrement est a adapter au logiciel (node save)."
node_type: dcc.__PREFIX___publish
interface:
  inputs:
    - {id: session, type: "session[__SOFT__]", label: "Session __LABEL__"}
    - {id: "name", type: "str", label: "Nom FLUX du publish (vide = nom du fichier)", default: ""}
    - {id: "description", type: "str", label: "Description du publish", default: ""}
  outputs:
    - {id: publish, type: publish, label: "Le publish"}
    - {id: path, type: path, label: "Fichier publie"}
nodes:
  ev: {type: event.manual, pos: [0, 160]}
  in_session: {type: data.flow_input, pos: [0, 320], params: {id: session}}
  save: {type: dcc.ext_run_script, pos: [320, 160], label: "Enregistrer une copie", params: {temp_ext: "__EXT__", code: "# A ADAPTER : enregistrer une copie de la scene dans args['path'] (API du logiciel).\\nraise RuntimeError('publish __LABEL__ : code d enregistrement a ecrire dans le node save')\\n"}}
  publish: {type: flux.publish_file, pos: [640, 160], params: {target_name: "${name}", description: "${description}"}}
  out_publish: {type: subflow.flow_output, pos: [960, 160], params: {id: publish}}
  out_path: {type: subflow.flow_output, pos: [1280, 160], params: {id: path}}
links:
  - {from: ev.then, to: save.exec}
  - {from: in_session.value, to: save.session}
  - {from: save.then, to: publish.exec}
  - {from: save.path, to: publish.source}
  - {from: publish.then, to: out_publish.exec}
  - {from: publish.publish, to: out_publish.value}
  - {from: out_publish.then, to: out_path.exec}
  - {from: publish.path, to: out_path.value}
notes:
  - {id: k1, pos: [0, 720], text: "Les verifications avant publish se placent entre save et publish. Le node save doit ecrire la scene dans args['path']."}
"""

KINDS = {"session": INSTANCE, "publish": PUBLISH}


def render(text: str, ext: Extension, scene_ext: str) -> str:
    m = ext.manifest
    return (text.replace("__LABELNS__", m.label.replace(" ", "")).replace("__LABEL__", m.label)
            .replace("__SOFT__", m.soft).replace("__PREFIX__", m.prefix).replace("__EXT__", scene_ext))


def flow_texts(ext: Extension, scene_ext: str) -> Dict[str, str]:
    """{kind: YAML} of the bridge: its flows/<kind>.flow.yml when the folder has one, else the
    template above."""
    out: Dict[str, str] = {}
    for kind, template in KINDS.items():
        own = ext.folder / "flows" / f"{kind}.flow.yml"
        text = own.read_text(encoding="utf-8") if own.is_file() else template
        out[kind] = render(text, ext, scene_ext)
    return out


def create_flows(ext: Extension, roots, *, user: str, scene_ext: str = ".scene",
                 overwrite: bool = False) -> List[Dict[str, Optional[str]]]:
    """Write the session and publish flows of *ext* into the team scope. An existing flow
    is kept unless *overwrite* (its revision is then bumped like any save)."""
    from flux_flows import dcc_nodes, store
    from flux_flows.model import parse_flow

    if not ext.ok:
        raise ValueError("; ".join(ext.errors) or "bridge invalide")
    if not scene_ext.startswith(".") or not scene_ext[1:].isalnum():
        raise ValueError(f"extension de scene `{scene_ext}` : attendu .max, .blend...")
    done: List[Dict[str, Optional[str]]] = []
    for kind, text in flow_texts(ext, scene_ext).items():
        flow = parse_flow(yaml.safe_load(text))
        exists = store.resolve(roots, flow.name) == "team"
        if exists and not overwrite:
            done.append({"kind": kind, "name": flow.name, "status": "kept"})
            continue
        store.save_flow(roots, "team", flow, user=user, force=True,
                        note=f"cree depuis le bridge d'extension {ext.soft}")
        done.append({"kind": kind, "name": flow.name, "status": "written"})
    dcc_nodes.reset_cache()
    return done
