# event.py — nodes that start a flow (02_NODES §2). P2: button and manual.
#
# An event has no incoming exec. Its outputs are the trigger payload: ``values``
# (the interface values) plus one port per interface id (01 §9).

from __future__ import annotations

from flux_flows.nodes.registry import flow_node, port

_THEN = port("then", "exec", "Suite du flow", "Next step")
_VALUES = port("values", "dict", "Valeurs de l'interface du flow", "Values of the flow interface",
               {"dest_folder": "$FLUX/DAILY"})


def _payload(ctx, inputs, params):
    values = dict(ctx.interface)
    return {**values, "values": values}


@flow_node("event.button", "Button", icon="MousePointerClick", outputs=[_THEN, _VALUES],
           params=[port("button_id", "str", "Bouton de page qui lance ce flow", "Page button that starts this flow",
                        "daily_render")],
           shelf=1, aliases=["bouton", "page", "start"],
           doc_fr="Part quand on clique le bouton d'une page TOOL, ou avec Run dans l'editeur.",
           doc_en="Starts when a TOOL page button is clicked, or with Run in the editor.")
async def button(ctx, inputs, params):
    return _payload(ctx, inputs, params)


@flow_node("event.manual", "Manual", icon="Play", outputs=[_THEN, _VALUES], shelf=0,
           aliases=["start", "depart", "run"],
           doc_fr="Depart a la main (Run de l'editeur) ou par un autre flow.",
           doc_en="Manual start (editor Run) or from another flow.")
async def manual(ctx, inputs, params):
    return _payload(ctx, inputs, params)


# -- P5: events armed by the scheduler (01 §9) ---------------------------------------
# Global (schedule, new_file, when): run by the host lock holder (perso flows: locally).
# Local (on_publish, scene_opened): run on the backend where they happen.
# Their settings are constants (wirable=False): the flow has no run while it waits (02 §2).
# The body hands the payload of the trigger on; a run started by hand (editor Run, dry
# run) gets example values so the rest of the flow can be tried.

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MISSED = ("catch_up_once", "skip")
SCENE_SOFTS = ("maya", "houdini")


@flow_node("event.schedule", "Schedule", icon="CalendarClock",
           outputs=[_THEN, port("fired_at", "str", "Creneau qui a declenche (ISO)", "Slot that fired (ISO)",
                                "2026-10-23T08:00:00"),
                    port("missed", "bool", "Vrai pour un rattrapage (FLUX etait ferme a l'heure)",
                         "True for a catch up (FLUX was closed at the time)", False)],
           params=[port("days", "str", "daily, ou jours separes par des virgules (mon,tue,...)",
                        "daily, or days separated by commas (mon,tue,...)", "mon,tue,wed,thu,fri", default="daily",
                        wirable=False),
                   port("time", "str", "Heure HH:MM (heure du poste qui execute)", "Time HH:MM (executing host)",
                        "08:00", default="08:00", wirable=False),
                   port("missed", "str", "Creneau manque : catch_up_once (rattrape une fois) ou skip",
                        "Missed slot: catch_up_once or skip", "catch_up_once", default="catch_up_once",
                        choices=MISSED, wirable=False)],
           shelf=2, aliases=["horaire", "cron", "planifier", "heure"],
           doc_fr="Part a heure fixe, tous les jours ou certains jours. Un creneau manque (FLUX ferme) est "
                  "rattrape une fois au prochain lancement par defaut. Le run prend les defauts de l'interface.",
           doc_en="Starts at a fixed time, every day or on some days. A missed slot (FLUX closed) is caught up "
                  "once at the next start by default. The run takes the interface defaults.")
async def schedule(ctx, inputs, params):
    from datetime import datetime

    p = ctx.payload
    return {"fired_at": p.get("fired_at") or datetime.now().isoformat(timespec="seconds"),
            "missed": bool(p.get("missed", False))}


@flow_node("event.new_file", "NewFile", icon="FilePlus",
           inputs=[port("folder", "dir", "Dossier surveille", "Watched folder", "$FLUX/DROP", required=True)],
           outputs=[_THEN, port("path", "path", "Fichier arrive", "New file", "$FLUX/DROP/ref.jpg"),
                    port("name", "str", "Nom du fichier", "File name", "ref.jpg"),
                    port("dir", "dir", "Dossier du fichier", "Folder of the file", "$FLUX/DROP")],
           params=[port("pattern", "pattern", "Motif sur le nom", "Pattern on the name", "*.jpg *.png", default="*",
                        wirable=False),
                   port("recursive", "bool", "Sous-dossiers compris", "Subfolders included", False, default=False,
                        wirable=False),
                   port("every_s", "int", "Frequence du scan en secondes (min 5)", "Scan frequency in seconds (min 5)",
                        30, default=30, wirable=False),
                   port("wait_stable", "bool", "Attendre une taille stable sur 2 scans", "Wait for a stable size on 2 scans",
                        True, default=True, wirable=False)],
           shelf=3, aliases=["fichier", "dossier", "surveiller", "watch", "drop"],
           doc_fr="Part pour chaque nouveau fichier qui arrive dans un dossier. Le premier scan sert de base : les "
                  "fichiers deja la ne declenchent rien.",
           doc_en="Starts for each new file that arrives in a folder. The first scan is a baseline: files already "
                  "there trigger nothing.")
async def new_file(ctx, inputs, params):
    from pathlib import Path

    p = ctx.payload
    path = p.get("path")
    if not path:
        folder = str(inputs.get("folder") or "")
        return {"path": str(Path(folder) / "exemple.txt") if folder else "", "name": "exemple.txt", "dir": folder}
    return {"path": str(path), "name": Path(str(path)).name, "dir": str(Path(str(path)).parent)}


@flow_node("event.when", "When", icon="Zap",
           inputs=[port("condition", "bool", "Condition (nodes purs : Exists, Compare...)",
                        "Condition (pure nodes: Exists, Compare...)", True, required=True)],
           outputs=[_THEN],
           params=[port("every_s", "int", "Frequence de l'evaluation en secondes (min 5)",
                        "Evaluation frequency in seconds (min 5)", 30, default=30, wirable=False)],
           shelf=4, aliases=["quand", "condition", "si", "trigger"],
           doc_fr="Part quand la condition passe de faux a vrai. La premiere evaluation sert de base ; une erreur "
                  "est notee dans le journal sans declencher.",
           doc_en="Starts when the condition goes from false to true. The first evaluation is a baseline; an error "
                  "is logged without firing.")
async def when(ctx, inputs, params):
    return {}


@flow_node("event.on_publish", "OnPublish", icon="PackageCheck",
           outputs=[_THEN, port("publish", "publish", "Le publish qui vient de reussir", "The publish that just succeeded"),
                    port("project", "str", "Projet du publish", "Project of the publish", "MYPROJ")],
           params=[port("soft", "pattern", "Logiciels (maya, houdini...), vide = tous", "Softs, empty = all", "maya",
                        wirable=False),
                   port("type", "pattern", "Types (scene, usd, cache, texture, image...), vide = tous",
                        "Types, empty = all", "usd", wirable=False),
                   port("name", "pattern", "Motif sur le nom du fichier, vide = tous", "Pattern on the file name",
                        "*_model_*", wirable=False)],
           shelf=5, aliases=["publish", "apres publish", "after publish", "publie"],
           doc_fr="Part apres chaque publish reussi sur ce poste (tous les logiciels), filtre par logiciel, type ou "
                  "nom. Soft et type sont deduits du nom et de l'extension.",
           doc_en="Starts after each successful publish on this workstation (every soft), filtered by soft, type "
                  "or name. Soft and type come from the name and the extension.")
async def on_publish(ctx, inputs, params):
    from flux_flows.nodes.flux import publish_record

    p = ctx.payload
    record = p.get("publish") or publish_record("exemple_v001.usd")
    return {"publish": record, "project": p.get("project") or (ctx.context or {}).get("project") or ""}


@flow_node("event.scene_opened", "SceneOpened", icon="FolderOpen",
           outputs=[_THEN, port("scene", "path", "Scene ouverte", "Opened scene", "$FLUX/PROJ/shot010_anim_v003.ma"),
                    port("soft", "str", "Logiciel", "Software", "maya"),
                    port("session", "session[*]", "Session de l'instance (nodes DCC, P6)",
                         "Session of the instance (DCC nodes, P6)")],
           params=[port("soft", "str", "maya ou houdini (autres logiciels en P6b)", "maya or houdini (other softs in P6b)",
                        "maya", default="maya", choices=SCENE_SOFTS, wirable=False),
                   port("every_s", "int", "Frequence de scrutation en secondes (min 2)",
                        "Polling frequency in seconds (min 2)", 5, default=5, wirable=False)],
           shelf=6, aliases=["scene", "ouverture", "open", "maya", "houdini"],
           doc_fr="Part quand une autre scene est ouverte dans Maya ou Houdini sur ce poste (scrutation de "
                  "l'instance, toutes les 5 s par defaut).",
           doc_en="Starts when another scene is opened in Maya or Houdini on this workstation (instance polling, "
                  "every 5 s by default).")
async def scene_opened(ctx, inputs, params):
    p = ctx.payload
    return {"scene": p.get("scene") or "", "soft": p.get("soft") or params.get("soft") or "maya",
            "session": p.get("session")}


# -- P6a: the start of the shipped publish_<soft> flows (01 §13) ----------------------------

@flow_node("event.publish_request", "PublishRequest", icon="Upload",
           outputs=[_THEN, _VALUES, port("soft", "str", "Logiciel qui demande le publish", "Software asking for the "
                                         "publish", "maya")],
           params=[port("soft", "str", "Logiciel du formulaire de publish", "Software of the publish form", "maya",
                        default="maya", wirable=False)],
           shelf=7, aliases=["publish", "publier", "formulaire", "publisher"],
           doc_fr="Part quand le Publisher d'un logiciel envoie son formulaire (valeurs de l'interface du flow). "
                  "Depart des flows publish_<soft> ; d'ici P8 on les lance avec Run.",
           doc_en="Starts when the Publisher of a software sends its form (values of the flow interface). Start of "
                  "the publish_<soft> flows; until P8 they are started with Run.")
async def publish_request(ctx, inputs, params):
    values = dict(ctx.interface)
    return {**values, "values": values, "soft": ctx.payload.get("soft") or params.get("soft") or ""}
