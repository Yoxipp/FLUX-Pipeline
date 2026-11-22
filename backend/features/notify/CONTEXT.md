# features/notify - notifications Discord (ADR 0062, 0073, 0091)

Zero serveur : le FLUX **de celui qui agit** met l'evenement en file ; la notification part en message prive (DM)
du bot Discord du projet pour un compte lie par `/link`, ou par le webhook du projet (salon partage, mention) quand
le bot est hors ligne (repli garde par ADR 0091). Un relais absent ou en erreur ne bloque jamais une action.
ADR 0091 : ntfy, le pont Team <-> Discord (`discord_sync`, `discord_map`) et la commande `/chat` sont retires.

## Modules

| Fichier | Role |
|---|---|
| `events.py` | Format d'evenement stable (`type`, `project`, `author`, `entity`, `detail`, `recipients`, `at`, `text`, `ref` = id d'entite + cle de tache pour tache / retake), texte, resume, diff de `production.json` (tache assignee ; nouveau retake = enregistrement `retakes` ou commentaire `kind: retake`, envoye aux assignes de la tache ou, sur une tache parente sans assigne, a ceux de ses sous-taches). Pur, sans I/O. |
| `hooks.py` | Les seuls points d'entree appeles ailleurs : `on_mentions` (`chat_manager._record_mentions`, aussi les pings du calendrier), `on_production` (`routers/production.put_production`), `on_publish` (`activity_writer.log_publish`). Rendent la main tout de suite (thread), ne levent jamais. |
| `dispatch.py` | `enqueue` (alias resolus, auteur retire, types coupes par la personne retires, delai selon le type), `flush` (un message par personne et par passage, boutons de `dm_actions` si un seul evenement et compte lie), worker a la demande, `send_test`. `FLUX_NOTIFY=0` coupe tout. |
| `outbox.py` | File locale `%APPDATA%/FluxPipeline/notify_queue.jsonl` (un fichier par poste), ecriture atomique, backoff 30 s a 1 h, abandon apres 24 h. La cible est relue a l'envoi. |
| `store.py` | Reglages projet `_flux_setup/collab.json` (webhook, delai, `include_project`, `include_text`, bot public) et personne `User.json` `notify` (canal `none` / `discord`, Discord ID, lien). Un ancien canal `ntfy` se lit `none`. `muted` = types coupes (opt-out par type, ADR 0091 ; `wants`). Sorties publiques masquees. |
| `relay_secrets.py` | Masquage `****` + 4 caracteres, `redact`. |
| `channels/` | `discord.py` (webhook) : HTTP stdlib (`urllib`), `SendResult` (ok, status, retry_after, permanent). `request_json` (toute methode + en-tetes) pour le bot. |
| `bot_secret.py` | Jeton du bot sur le PC hebergeur seulement : `%APPDATA%/FluxPipeline/discord_bot_tokens.json`, chiffre DPAPI (compte Windows). Jamais dans le partage. |
| `discord_bot.py` | Bot Discord (ADR 0073) : Gateway sortant (`websockets`, intents 0), `/link`, `/mentions`, `/calendar` en reponse ephemere ; tout sauf `/link` exige un compte lie par `/link` (`store.user_for_discord`) ; DM des notifs, envoi de la file partagee, fichier de presence du bot. `FLUX_DISCORD_BOT=0` le coupe (et `FLUX_NOTIFY=0`). ADR 0082 : chaque PC qui a le jeton fait tourner `BotRunner._life` ; seul le titulaire du verrou de projet `_flux_setup/discord_bot_host.lock` (`core.host_lock`) ouvre le Gateway, les autres attendent (`discord_bot_candidates.json`) et reprennent environ 1 min apres le depart de l'hebergeur, sans retour automatique ; `hosted_token` seulement en ligne (sinon la DM va dans la file). Lien d'invitation : `permissions=0` (DM, commandes et boutons n'en demandent aucune). |
| `dm_actions.py` | Boutons et menus sous un DM (ADR 0091) : tache / retake = Valider (statut `APPROVED`), Refuser (`RTK`), menu Donner a (assigne) ; proposition du calendrier = Valider (`accept`), Refuser (`decline`), menu Decaler (+1, +2, +7, +14 jours, `postpone`). Etats existants seulement. `components_for` (poste qui envoie ; l'element du calendrier est retrouve par auteur, personne, dates et titre) ; `handle` (hebergeur du bot, clic = INTERACTION_CREATE type 3, aucun intent) ecrit avec `production_store` / `calendar_store` au nom du compte FLUX lie par `/link`, puis `hooks.on_production` ou le ping de retour a l'auteur du calendrier. `custom_id` = `fx|op|hash projet|a|b` (100 car. max, sinon pas de bouton). Reussi : le DM perd ses boutons et affiche le resultat ; refuse : reponse ephemere, boutons gardes. |
| `bot_host.py` | Un seul hebergeur par PC (ADR 0076) : verrou local `%APPDATA%/FluxPipeline/discord_bot.lock` (pid, `app` / `headless`, repris si le process est mort). Mode sans fenetre `main.py --discord-bot` (aucun port, aucune API), lance a l'ouverture de session par un raccourci du dossier Demarrage utilisateur ; attend tant que FLUX tient les bots, reprend quand FLUX se ferme, relit les jetons chaque minute. |

Bot, fichiers du partage (`_flux_setup/`, aucun jeton) : `collab.json` `notify.discord_bot` (`app_id`, `name`, `host`),
`discord_bot_alive.json` (presence du bot, ecrite par l'hebergeur toutes les 30 s, en ligne si < 120 s), `discord_links.json`
(codes `/link` hashes sha256, 10 min, retires une fois utilises), `notify_bot/<AUTEUR>.json` (DM deposes par les autres
postes, 24 h). Envoi pour un compte lie : ce PC heberge -> DM direct ; bot en ligne ailleurs -> file partagee ;
bot hors ligne -> webhook s'il existe (sans boutons), sinon nouvel essai. Les boutons voyagent avec la DM dans la file partagee (`components`). Bot hors ligne au moment du clic : Discord affiche "l'application n'a pas repondu" (limite acceptee, 0073 / 0082). Un identifiant tape a la main n'est jamais lie (`discord_linked_at` vide).
Anciens fichiers du pont (`discord_map.json`, `discord_webhooks_<projet>.json`) : plus lus, laisses en place.

Router : `routers/notify.py` (`/notify/me`, `/notify/me/test`, `/notify/me/discord_link`, `/notify/project/{p}` (PUT = role
`project_settings`), `/notify/project/{p}/bot` (PUT jeton = heberger ici, DELETE, role `project_settings`), `/notify/project/{p}/bot/background` (PUT, PC qui a le jeton : raccourci Demarrage + lancement / arret du mode sans fenetre), `/notify/status`).
Demarrage : `main.py` lifespan `discord_bot.start_all()` (projets dont le jeton est sur ce PC), `stop_all()` a l'arret.
Front : `app/src/api/notify.ts`, `app/src/pages/settings/DiscordSettings.tsx` (Parametres > User : Discord oui / non, lien,
test ; > Projet : bot, webhook de repli, regroupement), `DiscordLink.tsx` (etat lie / code `/link`, aussi dans l'accueil
`components/shared/WelcomeDialog.tsx`). Le code `/link` porte le nom Discord affiche (`discord_name` des prefs, vide si tape a la main).

## Regles

* Contenu : type + entite + auteur, plus le message du chat (mention) ou le titre du calendrier si `include_text` (defaut actif,
  ADR 0072), sur une ligne, 300 caracteres max. Jamais de chemin. Nom du projet seulement si coche.
  Webhook = salon partage : le message est lu par tout le salon.
* Immediat : mention, tache, retake. Regroupe (delai du projet, 5 min par defaut) : publish, calendrier.
* Destinataires d'un publish = filtre du fil personnel (ADR 0045, `notifications.reason_for`), seulement les comptes qui ont un canal.
* Logs : type + canal + statut. Jamais l'URL du webhook.
* Secrets dans le partage (2026-10-30) : lisibles par l'equipe, regenerables.

## Tests

`backend/tests/notify/` : relais = serveur HTTP local (`_relay.py`), aucun appel reseau reel. `run_tests.py` met `FLUX_NOTIFY=0`
pour que les autres suites n'ecrivent jamais dans la vraie file.

## Futur (plugin officiel sur le graph)

`events.make_event` + `dispatch.enqueue` = futur node `Notify` ; les `hooks` = futurs `event.*`. Les reglages sont du JSON lisible par un flow.
