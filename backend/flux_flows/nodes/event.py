# event.py — nodes that start a flow (02_NODES §2). P2: button and manual.
#
# An event has no incoming exec. Its outputs are the trigger payload: ``values``
# (the interface values) plus one port per interface id (01 §9).

from __future__ import annotations

from pathlib import Path, PureWindowsPath as PurePath

from flux_flows.nodes.registry import flow_node, port

_THEN = port("then", "exec", "Suite du flow", "Next step")
_VALUES = port("values", "dict", "Valeurs de l'interface du flow", "Values of the flow interface",
               {"dest_folder": "$FLUX/DAILY"})
# R1 retakes 3 and 10: the infos of the publish, split by data.publish_infos (PublishInfos).
_INFOS = port("infos", "dict", "Infos du publish (mode, task, asset ou seq / shot, instance, soft...) : relie "
              "PublishInfos pour les lire une par une", "Publish infos (mode, task, asset or seq / shot, instance, "
              "soft...): link PublishInfos to read them one by one",
              {"mode": "asset", "task": "RIG", "class": "CHAR", "asset": "HERO", "soft": "maya"})
MODE_FILTER = ("any", "asset", "shot")


def _payload(ctx, inputs, params):
    values = dict(ctx.interface)
    return {**values, "values": values}


@flow_node("event.button", "Button", icon="MousePointerClick", outputs=[_THEN, _VALUES],
           params=[port("button_id", "str", "Bouton de page qui lance ce flow", "Page button that starts this flow",
                        "daily_render")],
           aliases=["bouton"],
           doc_fr="Ancien depart de page (ADR 0068) : remplace par InputsPageReader. Ne part plus que par Run dans "
                  "l'editeur.",
           doc_en="Old page start (ADR 0068): replaced by InputsPageReader. Only starts with Run in the editor.")
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
SCENE_SOFTS = ("maya", "houdini", "nuke")   # nuke: P6b (its bridge gives the open script)


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


def _filter(name, fr, en, example):
    return port(name, "pattern", f"{fr}, vide = tous", f"{en}, empty = all", example, wirable=False)


@flow_node("event.on_publish", "OnPublish", icon="PackageCheck",
           outputs=[_THEN, port("publish", "publish", "Le publish qui vient de reussir", "The publish that just succeeded"),
                    port("project", "str", "Projet du publish", "Project of the publish", "MYPROJ"), _INFOS],
           params=[port("mode", "str", "Asset, shot ou les deux (any)", "Asset, shot or both (any)", "asset",
                        default="any", choices=MODE_FILTER, wirable=False,
                        labels={"any": ("Asset et shot", "Asset and shot"), "asset": ("Asset seulement", "Asset only"),
                                "shot": ("Shot seulement", "Shot only")}),
                   _filter("task", "Task / departement (token TYPE : RIG, MOD, ANIM...)",
                           "Task / department (TYPE token: RIG, MOD, ANIM...)", "RIG MOD"),
                   _filter("class", "Classe de l'asset (CHAR, PROPS...)", "Asset class (CHAR, PROPS...)", "CHAR"),
                   _filter("asset", "Nom de l'asset (HERO...)", "Asset name (HERO...)", "HERO"),
                   _filter("seq", "Sequence (SEQ010...)", "Sequence (SEQ010...)", "SEQ010"),
                   _filter("shot", "Plan (SHOT010...)", "Shot (SHOT010...)", "SHOT0*"),
                   _filter("project", "Projet", "Project", "DEMO"),
                   _filter("soft", "Logiciels (maya, houdini...) qui ont publie, envoye par le Publisher (un .abc "
                           "publie depuis Maya compte pour maya)", "Softs (maya, houdini...) that published, sent by "
                           "the Publisher (an .abc published from Maya counts as maya)",
                           "maya"),
                   _filter("type", "Types de fichier (scene, usd, cache, texture, image, video, capture...)",
                           "File types (scene, usd, cache, texture, image, video, capture...)", "usd"),
                   _filter("name", "Motif sur le nom du fichier", "Pattern on the file name", "*_model_*")],
           shelf=5, aliases=["publish", "apres publish", "after publish", "publie"],
           doc_fr="Part apres chaque publish reussi sur ce poste, si FLUX y est ouvert (tous les logiciels). Les filtres (mode, task, "
                  "asset, plan, projet, logiciel, type, nom) choisissent les publishs qui le declenchent ; vide = tout. "
                  "Un publish filtre ne cree aucun run. Le logiciel est celui qui publie (envoye par le Publisher).",
           doc_en="Starts after each successful publish on this workstation, if FLUX is open there (every soft). The filters (mode, task, "
                  "asset, shot, project, soft, type, name) pick the publishes that fire it; empty = all. A filtered "
                  "publish creates no run. The soft is the one that publishes (sent by the Publisher).")
async def on_publish(ctx, inputs, params):
    from flux_flows.nodes.flux import publish_infos, publish_record

    p = ctx.payload
    # A run by hand: an example publish by the artist of the run (T1: an empty user broke {user}).
    record = p.get("publish") or publish_record("CHAR_RIG_HERO_null_v001.ma", user=(ctx.context or {}).get("user") or "")
    project = p.get("project") or (ctx.context or {}).get("project") or ""
    infos = p.get("infos") or publish_infos(record.get("file"), project=project, user=record.get("user") or "",
                                            path=record.get("path") or "", version=record.get("version"))
    if not p.get("publish"):
        # R1 audit F14: a run by hand uses an example publish; say when the filters would refuse it.
        from flux_flows.hooks import wants

        if not wants(params, record, infos):
            ctx.log(f"Publish d'exemple {record.get('file')} : tes filtres le refuseraient, un vrai publish de ce "
                    "type ne lancerait pas ce flow (le run continue pour essayer la suite)", "warn")
    return {"publish": record, "project": project, "infos": infos}


@flow_node("event.scene_opened", "SceneOpened", icon="FolderOpen",
           outputs=[_THEN, port("scene", "path", "Scene ouverte", "Opened scene", "$FLUX/PROJ/shot010_anim_v003.ma"),
                    port("soft", "str", "Logiciel", "Software", "maya"),
                    port("session", "session[*]", "Session de l'instance (nodes DCC, P6)",
                         "Session of the instance (DCC nodes, P6)")],
           params=[port("soft", "str", "maya, houdini ou nuke", "maya, houdini or nuke",
                        "maya", default="maya", choices=SCENE_SOFTS, wirable=False),
                   port("every_s", "int", "Frequence de scrutation en secondes (min 2)",
                        "Polling frequency in seconds (min 2)", 5, default=5, wirable=False)],
           shelf=6, aliases=["scene", "ouverture", "open", "maya", "houdini"],
           doc_fr="Part quand une autre scene est ouverte dans Maya, Houdini ou Nuke sur ce poste (scrutation de "
                  "l'instance, toutes les 5 s par defaut).",
           doc_en="Starts when another scene is opened in Maya, Houdini or Nuke on this workstation (instance polling, "
                  "every 5 s by default).")
async def scene_opened(ctx, inputs, params):
    p = ctx.payload
    return {"scene": p.get("scene") or "", "soft": p.get("soft") or params.get("soft") or "maya",
            "session": p.get("session")}


# -- P6a: the start of the shipped publish_<soft> flows (01 §13) ----------------------------

@flow_node("event.publish_request", "PublishRequest", icon="Upload",
           outputs=[_THEN, _VALUES, port("soft", "str", "Logiciel qui demande le publish", "Software asking for the "
                                         "publish", "maya"), _INFOS],
           params=[port("soft", "str", "Logiciel du formulaire de publish", "Software of the publish form", "maya",
                        default="maya", wirable=False)],
           shelf=7, aliases=["publish", "publier", "formulaire", "publisher"],
           doc_fr="Part quand le Publisher d'un logiciel envoie son formulaire (valeurs de l'interface du flow). "
                  "Depart des flows publish_<soft> ; d'ici P8 on les lance avec Run.",
           doc_en="Starts when the Publisher of a software sends its form (values of the flow interface). Start of "
                  "the publish_<soft> flows; until P8 they are started with Run.")
async def publish_request(ctx, inputs, params):
    from flux_flows.nodes.flux import publish_infos

    values = dict(ctx.interface)
    soft = ctx.payload.get("soft") or params.get("soft") or ""
    name, ext = str(values.get("name") or ""), str(values.get("format") or "")
    c = ctx.context or {}
    infos = publish_infos(name + ext if name and ext.startswith(".") else name, soft=soft,
                          project=c.get("project") or "", user=c.get("user") or "")
    return {**values, "values": values, "soft": soft, "infos": infos}


# -- ADR 0081: a command typed in the Team chat (`/zip "<folder>"`) ---------------------------

_COMMAND_EXAMPLE = {"command": "zip", "args": ["//server/proj/SEQ010"], "arg": "//server/proj/SEQ010",
                    "text": '"//server/proj/SEQ010"', "user": "ADAM", "channel": "general", "message_id": ""}


@flow_node("event.team_command", "TeamCommand", icon="SquareSlash",
           outputs=[_THEN,
                    port("arg", "str", "Premier argument (entre guillemets s'il a des espaces)",
                         "First argument (in quotes when it has spaces)", "//server/proj/SEQ010"),
                    port("path", "path", "Premier argument comme chemin (vide sans argument)",
                         "First argument as a path (empty without an argument)", "//server/proj/SEQ010"),
                    port("dir", "dir", "Le meme chemin si c'est un dossier existant, sinon vide (a zipper, a lister...)",
                         "The same path when it is an existing folder, else empty (to zip, to list...)",
                         "//server/proj/SEQ010"),
                    port("parent", "dir", "Dossier qui contient ce chemin (ex. ou poser le zip)",
                         "Folder that holds this path (e.g. where to put the zip)", "//server/proj"),
                    port("args", "list[str]", "Tous les arguments", "All the arguments", ["//server/proj/SEQ010"]),
                    port("text", "str", "Texte brut apres la commande", "Raw text after the command",
                         '"//server/proj/SEQ010"'),
                    port("user", "str", "Artiste qui a tape la commande", "Artist who typed the command", "ADAM"),
                    port("channel", "str", "Canal du message", "Channel of the message", "general"),
                    port("values", "dict", "Tout en un (pour Template : {arg}, {user}, {channel}...)",
                         "All in one (for Template: {arg}, {user}, {channel}...)", _COMMAND_EXAMPLE)],
           params=[port("name", "str", "Nom de la commande, sans / (minuscules, chiffres, - et _)",
                        "Command name, without / (lower case, digits, - and _)", "zip", required=True,
                        wirable=False),
                   port("help", "str", "Aide montree pendant la saisie", "Help shown while typing",
                        '"<dossier>" : zippe le dossier a cote de lui', wirable=False),
                   port("channels", "pattern", "Canaux ou elle marche (espaces ou virgules), vide = tous",
                        "Channels where it works (spaces or commas), empty = all", "general rendu", default="",
                        wirable=False),
                   port("confirm", "bool", "Demander une confirmation avant de lancer",
                        "Ask for a confirmation before running", False, default=False, wirable=False)],
           shelf=9, aliases=["commande", "chat", "team", "slash", "/"],
           doc_fr="Part quand un artiste tape /nom dans le chat de la page Team (ex. /zip \"//serveur/projet/SEQ010\"). "
                  "Le flow tourne sur le poste de l'artiste, s'il voit le canal ; flow perso = commande pour soi. "
                  "TeamReply repond dans le fil du message.",
           doc_en="Starts when an artist types /name in the chat of the Team page (e.g. /zip \"//server/proj/SEQ010\"). "
                  "The flow runs on the workstation of the artist, if they see the channel; perso flow = a command for "
                  "oneself. TeamReply answers in the thread of the message.")
async def team_command(ctx, inputs, params):
    p = ctx.payload
    if not p.get("command"):   # a run by hand: example values
        values = {**_COMMAND_EXAMPLE, "command": params.get("name") or "zip",
                  "user": (ctx.context or {}).get("user") or "ADAM"}
    else:
        args = [str(a) for a in p.get("args") or []]
        values = {"command": p.get("command"), "args": args, "arg": args[0] if args else "",
                  "text": p.get("text") or "", "user": p.get("user") or "", "channel": p.get("channel") or "general",
                  "message_id": p.get("message_id") or ""}
    first = str(values["arg"] or "")
    path = PurePath(first) if first else None
    return {**{k: values[k] for k in ("arg", "args", "text", "user", "channel")}, "values": values,
            "path": path.as_posix() if path else "", "dir": path.as_posix() if path and Path(first).is_dir() else "",
            "parent": path.parent.as_posix() if path and path.parent != path else ""}
