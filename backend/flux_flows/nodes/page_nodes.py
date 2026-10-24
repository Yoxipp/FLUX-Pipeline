# page_nodes.py — the TOOL page data on the graph side (ADR 0066 n°6, P7): read and write a
# collection of a page, and start a flow when a record arrives. "Quand un message arrive ->
# Notify" or "Schedule -> PageDataRead -> ForEach -> Notify" (reminders) are then built with
# the existing nodes, nothing else. A write goes to the journal of the user of the run.

from __future__ import annotations

from flux_flows.nodes.contract import NodeError
from flux_flows.nodes.registry import flow_node, port

_PAGE = port("page", "str", "Id de la page TOOL", "TOOL page id", "team", required=True)
_COLL = port("collection", "str", "Id de la collection de la page", "Collection id of the page", "messages",
             required=True)
_RECORD = {"rid": "ADAM_18c2_ab12", "text": "Salut", "channel": "general", "_by": "ADAM", "_at": "2026-10-24T10:00:00"}


def _project(ctx, inputs) -> str:
    return str(inputs.get("project") or (ctx.context or {}).get("project") or "")


def _locate(ctx, inputs):
    from flux_flows import page_data
    from flux_flows.store import FlowStoreError

    page, coll = str(inputs.get("page") or ""), str(inputs.get("collection") or "")
    try:
        return page_data.locate(page, coll, _project(ctx, inputs) or None)
    except (FlowStoreError, ValueError) as exc:
        raise NodeError(str(exc)) from None


@flow_node("event.page_data", "PageData", icon="Database",
           outputs=[port("then", "exec", "Suite du flow", "Next step"),
                    port("record", "dict", "L'enregistrement ajoute ou modifie", "The record added or changed", _RECORD),
                    port("user", "str", "Qui l'a ecrit", "Who wrote it", "ADAM"),
                    port("project", "str", "Projet des donnees (vide = equipe)", "Project of the data (empty = team)",
                         "MYPROJ")],
           params=[port("page", "str", "Id de la page TOOL", "TOOL page id", "team", required=True, wirable=False),
                   port("collection", "str", "Id de la collection", "Collection id", "messages", required=True,
                        wirable=False),
                   port("on", "str", "added (nouveau), changed (modifie) ou any", "added, changed or any", "added",
                        default="added", choices=("added", "changed", "any"), wirable=False),
                   port("every_s", "int", "Frequence de lecture en secondes (min 5)", "Read frequency in seconds (min 5)",
                        10, default=10, wirable=False)],
           shelf=6, aliases=["donnees", "message", "page", "data", "nouveau"],
           doc_fr="Part pour chaque enregistrement ajoute (ou modifie) dans une collection d'une page TOOL, quel que "
                  "soit le poste qui l'a ecrit. La premiere lecture sert de base.",
           doc_en="Starts for each record added (or changed) in a collection of a TOOL page, whatever the computer "
                  "that wrote it. The first read is a baseline.")
async def page_data_event(ctx, inputs, params):
    p = ctx.payload
    record = p.get("record") or dict(_RECORD)
    return {"record": record, "user": p.get("user") or record.get("_by") or "",
            "project": p.get("project") or (ctx.context or {}).get("project") or ""}


@flow_node("flux.page_data_read", "PageDataRead", icon="Database",
           inputs=[port("exec", "exec", required=True), _PAGE, _COLL,
                   port("project", "str", "Projet (vide = celui du run)", "Project (empty = the run's)", "MYPROJ")],
           outputs=[port("then", "exec"), port("on_error", "exec"),
                    port("records", "list[dict]", "Les enregistrements, du plus ancien au plus recent",
                         "The records, oldest first", [_RECORD]),
                    port("count", "int", "Nombre d'enregistrements", "Number of records", 1)],
           shelf=60, aliases=["lire", "donnees", "page", "read", "collection"],
           doc_fr="Lit les enregistrements d'une collection d'une page TOOL (fusion des journaux de tous les auteurs).",
           doc_en="Reads the records of a collection of a TOOL page (every author's journal merged).")
async def page_data_read(ctx, inputs, params):
    import asyncio

    from flux_flows import page_data

    folder, _, _ = await asyncio.to_thread(_locate, ctx, inputs)
    records = (await asyncio.to_thread(page_data.read_records, folder))["records"]
    return {"records": records, "count": len(records)}


def _simulate_write(ctx, inputs, params):
    op = str(params.get("op") or "put")
    target = f"{inputs.get('page')}/{inputs.get('collection')}"
    what = f"supprimerait {inputs.get('rid')}" if op == "del" else \
        (f"modifierait {inputs.get('rid')}" if inputs.get("rid") else "ajouterait un enregistrement")
    text = f"{target} : {what} {inputs.get('fields') or ''}".strip()
    return {"lines": [{"kind": "page_data", "text_fr": text}], "outputs": {"rid": inputs.get("rid") or "nouveau"}}


@flow_node("flux.page_data_write", "PageDataWrite", icon="PenLine",
           inputs=[port("exec", "exec", required=True), _PAGE, _COLL,
                   port("fields", "dict", "Champs a ecrire", "Fields to write", {"text": "Rendu fini"}),
                   port("rid", "str", "Enregistrement a modifier (vide = un nouveau)", "Record to change (empty = a new one)"),
                   port("project", "str", "Projet (vide = celui du run)", "Project (empty = the run's)", "MYPROJ")],
           outputs=[port("then", "exec"), port("on_error", "exec"),
                    port("rid", "str", "Id de l'enregistrement ecrit", "Id of the record written", "ADAM_18c2_ab12")],
           params=[port("op", "str", "put (ajouter / modifier) ou del (supprimer)", "put (add / change) or del (delete)",
                        "put", default="put", choices=("put", "del"), wirable=False)],
           effect=True, simulate=_simulate_write, shelf=61, aliases=["ecrire", "poster", "message", "write", "ajouter"],
           doc_fr="Ajoute, modifie ou supprime un enregistrement d'une collection d'une page TOOL (journal de "
                  "l'utilisateur du run).",
           doc_en="Adds, changes or deletes a record of a collection of a TOOL page (journal of the run's user).")
async def page_data_write(ctx, inputs, params):
    import asyncio

    from flux_flows import page_data
    from flux_flows.store import FlowStoreError

    folder, spec, _ = await asyncio.to_thread(_locate, ctx, inputs)
    rid = str(inputs.get("rid") or "") or None
    op = str(params.get("op") or "put")
    if op == "del" and not rid:
        raise NodeError("del sans rid : relie l'id de l'enregistrement a supprimer")
    fields = inputs.get("fields") or {}
    if not isinstance(fields, dict):
        raise NodeError("fields doit etre un dict (ex. JsonValue)")
    one = {"op": "del", "rid": rid} if op == "del" else ({"op": "put", "rid": rid, "fields": fields} if rid
                                                         else {"op": "put", "fields": fields})
    user = str((ctx.context or {}).get("user") or "")
    try:
        done = await asyncio.to_thread(page_data.write_ops, folder, spec, [one], user=user)
    except FlowStoreError as exc:
        raise NodeError(str(exc)) from None
    return {"rid": done["rids"][0]}
