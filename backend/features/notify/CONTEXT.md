# features/notify - notifications telephone (ADR 0062, P1 du chantier miro_teams_portal_mobile)

Zero serveur : le FLUX **de celui qui agit** pousse vers les destinataires par un relais tiers optionnel.
Discord (webhook par projet, `<@id>` par personne) ou ntfy (sujet aleatoire par personne, `https://ntfy.sh`
par defaut, URL remplacable). Un relais absent ou en erreur ne bloque jamais une action.

## Modules

| Fichier | Role |
|---|---|
| `events.py` | Format d'evenement stable (`type`, `project`, `author`, `entity`, `detail`, `recipients`, `at`), texte minimal, resume, diff de `production.json` (tache assignee, nouveau retake). Pur, sans I/O. |
| `hooks.py` | Les seuls points d'entree appeles ailleurs : `on_mentions` (`chat_manager._record_mentions`, aussi les pings du calendrier), `on_production` (`routers/production.put_production`), `on_publish` (`activity_writer.log_publish`). Rendent la main tout de suite (thread), ne levent jamais. |
| `dispatch.py` | `enqueue` (alias resolus, auteur retire, delai selon le type), `flush` (un message par personne et par passage), quota ntfy, worker a la demande, `send_test`. `FLUX_NOTIFY=0` coupe tout. |
| `outbox.py` | File locale `%APPDATA%/FluxPipeline/notify_queue.jsonl` (un fichier par poste), ecriture atomique, backoff 30 s a 1 h, abandon apres 24 h. La cible (webhook, sujet) est relue a l'envoi. |
| `store.py` | Reglages projet `_flux_setup/collab.json` (webhook, serveur ntfy, delai, nom du projet) et personne `User.json` `notify` (canal, Discord ID, sujet). Sorties publiques masquees. |
| `relay_secrets.py` | Masquage `****` + 4 caracteres, sujet aleatoire, `redact`. |
| `channels/` | `discord.py`, `ntfy.py` : HTTP stdlib (`urllib`), `SendResult` (ok, status, retry_after, permanent). |

Router : `routers/notify.py` (`/notify/me`, `/notify/me/test`, `/notify/project/{p}` (PUT = role `project_settings`), `/notify/status`).
Front : `app/src/api/notify.ts`, `app/src/pages/settings/NotifySettings.tsx` (Parametres > User et > Projet, QR code `qrcode` MIT).

## Regles

* Contenu : type + entite + auteur. Jamais de chemin, jamais le texte du chat, pas de titre de calendrier, nom du projet seulement si coche.
* Immediat : mention, tache, retake. Regroupe (delai du projet, 5 min par defaut) : publish, calendrier.
* Destinataires d'un publish = filtre du fil personnel (ADR 0045, `notifications.reason_for`), seulement les comptes qui ont un canal.
* Quota ntfy.sh 250 / jour par IP : compteur local `notify_counter.json` ; a partir de 200 tout est regroupe, a 250 attente du lendemain.
* Logs : type + canal + statut. Jamais l'URL du webhook ni le sujet.
* Secrets dans le partage (2026-10-30) : lisibles par l'equipe, regenerables. Un sujet ntfy est prive par son nom seulement.

## Tests

`backend/tests/notify/` : relais = serveur HTTP local (`_relay.py`), aucun appel reseau reel. `run_tests.py` met `FLUX_NOTIFY=0`
pour que les autres suites n'ecrivent jamais dans la vraie file.

## Futur (plugin officiel sur le graph)

`events.make_event` + `dispatch.enqueue` = futur node `Notify` ; les `hooks` = futurs `event.*`. Les reglages sont du JSON lisible par un flow.
