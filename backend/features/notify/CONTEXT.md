# features/notify - notifications telephone (ADR 0062, P1 du chantier miro_teams_portal_mobile)

Zero serveur : le FLUX **de celui qui agit** pousse vers les destinataires par un relais tiers optionnel.
Discord (webhook par projet, `<@id>` par personne) ou ntfy (sujet aleatoire par personne, `https://ntfy.sh`
par defaut, URL remplacable). Un relais absent ou en erreur ne bloque jamais une action.

## Modules

| Fichier | Role |
|---|---|
| `events.py` | Format d'evenement stable (`type`, `project`, `author`, `entity`, `detail`, `recipients`, `at`, `text`), texte, resume, diff de `production.json` (tache assignee, nouveau retake). Pur, sans I/O. |
| `hooks.py` | Les seuls points d'entree appeles ailleurs : `on_mentions` (`chat_manager._record_mentions`, aussi les pings du calendrier), `on_production` (`routers/production.put_production`), `on_publish` (`activity_writer.log_publish`). Rendent la main tout de suite (thread), ne levent jamais. |
| `dispatch.py` | `enqueue` (alias resolus, auteur retire, delai selon le type), `flush` (un message par personne et par passage), quota ntfy, worker a la demande, `send_test`. `FLUX_NOTIFY=0` coupe tout. |
| `outbox.py` | File locale `%APPDATA%/FluxPipeline/notify_queue.jsonl` (un fichier par poste), ecriture atomique, backoff 30 s a 1 h, abandon apres 24 h. La cible (webhook, sujet) est relue a l'envoi. |
| `store.py` | Reglages projet `_flux_setup/collab.json` (webhook, serveur ntfy, delai, nom du projet, `include_text`) et personne `User.json` `notify` (canal, Discord ID, sujet). Sorties publiques masquees. |
| `relay_secrets.py` | Masquage `****` + 4 caracteres, sujet aleatoire, `redact`. |
| `channels/` | `discord.py`, `ntfy.py` : HTTP stdlib (`urllib`), `SendResult` (ok, status, retry_after, permanent). `request_json` (toute methode + en-tetes) pour le bot. |
| `bot_secret.py` | Jeton du bot sur le PC hebergeur seulement : `%APPDATA%/FluxPipeline/discord_bot_tokens.json`, chiffre DPAPI (compte Windows). Jamais dans le partage. |
| `discord_bot.py` | Bot Discord (ADR 0073 etapes 1 et 2) : Gateway sortant (`websockets`, intents 0), `/link`, `/mentions`, `/chat [n]` (10 par defaut, 20 max, les plus recents gardes si > 2000 car.) et `/calendar` (propositions a valider + mes elements non finis, retard marque) en reponse ephemere ; tout sauf `/link` exige un compte lie par `/link` (`store.user_for_discord`) ; DM des notifs, envoi de la file partagee, fichier de presence. `FLUX_DISCORD_BOT=0` le coupe (et `FLUX_NOTIFY=0`). ADR 0082 : chaque PC qui a le jeton fait tourner `BotRunner._life` ; seul le titulaire du verrou de projet `_flux_setup/discord_bot_host.lock` (`core.host_lock`) ouvre le Gateway, les autres attendent (`discord_bot_candidates.json`) et reprennent environ 1 min apres le depart de l'hebergeur, sans retour automatique ; verrou perdu = Gateway ferme ; `hosted_token` seulement en ligne (sinon la DM va dans la file). Routes : un 2e PC colle le jeton du meme bot = candidat (409 si autre bot), `DELETE ...?this_pc_only=true` retire ce PC seul. |

| `discord_sync.py` | Pont Team <-> serveur Discord du projet (ADR 0084 lots 2 a 6), dans l'hebergeur seulement, si `collab.json` `notify.discord_sync` (opt-in) : `Bridge.tick` (toutes les 5 s via `_chores`) = passe de structure (`reconcile` : salons, categories, ordre, archive, sujet, roles "FLUX <role>", overwrites des canaux restreints ; FLUX maitre ; salon / categorie cree dans Discord -> importe dans FLUX (journal `DISCORD.jsonl`) ; supprime dans Discord -> archive dans FLUX, `#general` refait), rattrapage une fois par connexion (`catch_up`), puis `push` (messages FLUX -> webhook par salon, nom + avatar Discord de l'artiste lie, `@NOM` -> `<@id>`, fichiers joints <= 10 Mo). `on_message` : Discord -> `chat_manager.post_message(..., discord=<id>)`, pieces jointes copiees dans `team_files/` (`files.store_bytes`). Anti-boucle : message avec `discord` jamais renvoye, messages de webhook / bot ignores, passe idempotente (les evenements du bot ne changent rien). Jetons des webhooks : `%APPDATA%/FluxPipeline/discord_webhooks_<projet>.json` chiffre DPAPI, jamais sur le partage. |
| `discord_map.py` | `_flux_setup/discord_map.json`, ecrit par l'hebergeur seul : serveur, `since` (messages FLUX plus anciens jamais envoyes), groupes / canaux (rid ou `general`) <-> ids Discord, categorie d'archives, roles, membres lies, paires de messages (20000 dernieres), `last_seen` par salon (rattrapage), `voice` (qui est en vocal), `status` (dernier passage, erreur). `public()` pour la page Team. |
| `bot_host.py` | Un seul hebergeur par PC (ADR 0076) : verrou local `%APPDATA%/FluxPipeline/discord_bot.lock` (pid, `app` / `headless`, repris si le process est mort). Mode sans fenetre `main.py --discord-bot` (aucun port, aucune API), lance a l'ouverture de session par un raccourci du dossier Demarrage utilisateur ; attend tant que FLUX tient les bots, reprend quand FLUX se ferme, relit les jetons chaque minute. |

Pont Team (ADR 0084) : intents GUILDS + GUILD_MESSAGES + MESSAGE_CONTENT + GUILD_VOICE_STATES seulement si le projet
l'active (sinon 0) ; jamais DIRECT_MESSAGES (aucun DM lu). Code de fermeture 4014 (intent non coche dans le portail) :
le bot revient sans intents, le pont s'arrete, l'erreur s'affiche dans Parametres > Projet ; nouvel essai 15 min apres. Le lien d'invitation demande
Manage Channels, Manage Roles, Manage Webhooks, View / Send / Embed / Attach / History (jamais Administrator). Pas de
fils (threads), pas d'edition ni de suppression de message reportees, pas d'historique Discord copie a la premiere
liaison. Tests : `tests/notify/test_discord_sync.py` contre `tests/notify/_fake_discord.py` (REST en memoire) et un
Gateway websocket local.

Bot, fichiers du partage (`_flux_setup/`, aucun jeton) : `collab.json` `notify.discord_bot` (`app_id`, `name`, `host`),
`discord_bot_alive.json` (presence, ecrite par l'hebergeur toutes les 30 s, en ligne si < 120 s), `discord_links.json`
(codes `/link` hashes sha256, 10 min, retires une fois utilises), `notify_bot/<AUTEUR>.json` (DM deposes par les autres
postes, 24 h). Envoi Discord pour un compte lie : ce PC heberge -> DM direct ; bot en ligne ailleurs -> file partagee ;
bot hors ligne -> webhook s'il existe, sinon nouvel essai. Un identifiant tape a la main n'est jamais lie (`discord_linked_at` vide).

Router : `routers/notify.py` (`/notify/me`, `/notify/me/test`, `/notify/me/discord_link`, `/notify/project/{p}` (PUT = role
`project_settings`), `/notify/project/{p}/bot` (PUT jeton = heberger ici, DELETE, role `project_settings`), `/notify/project/{p}/bot/background` (PUT, PC qui a le jeton : raccourci Demarrage + lancement / arret du mode sans fenetre), `/notify/status`).
Demarrage : `main.py` lifespan `discord_bot.start_all()` (projets dont le jeton est sur ce PC), `stop_all()` a l'arret.
Front : `app/src/api/notify.ts`, `app/src/pages/settings/NotifySettings.tsx` (Parametres > User et > Projet, QR code `qrcode` MIT).

## Regles

* Contenu : type + entite + auteur, plus le message du chat (mention) ou le titre du calendrier si `include_text` (defaut actif,
  ADR 0072), sur une ligne, 300 caracteres max. Jamais de chemin. Nom du projet seulement si coche.
  Webhook = salon partage : le message est lu par tout le salon. Version privee (bot) : ADR 0073, proposee.
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
