# features/team — page Team facon Teams (ADR 0077)

Autour du chat d'equipe existant (`features/activity/chat_manager.py`, `teamChat.json` du projet), sans serveur.

| Fichier | Role |
|---|---|
| `team_meta.py` | Canaux (lead : nom, sujet, lien d'appel https, archive, `access` JSON qui voit le canal, ADR 0080 : `parse_access`, `hidden_channels` ; leads / sups voient tout, `#general` ouvert), reactions (une par auteur, retiree par son auteur) et messages epingles (lead), en journaux par auteur `_flux_setup/team/<AUTEUR>.jsonl` (moteur `flux_flows/page_data.py`). Groupes de canaux et canaux vocaux (ADR 0084) : `kind: group` (`name`, `order`), canal `type` text / voice, `group` = rid du groupe, `order` ; leads. |
| `presence.py` | `USER/<artiste>/presence.json` reecrit par son seul auteur (`status` available / away / meeting / dnd, `text`, `at`) ; en ligne si moins de 150 s. |
| `files.py` | Fichiers joints COPIES par le backend dans `_flux_setup/team_files/<hash>.<ext>` (200 Mo max, programmes et scripts refuses). `store_bytes` : meme regle pour une piece jointe Discord recue par le pont. |

Pont Discord (ADR 0084, `features/notify/discord_sync.py`, sur l'hebergeur du bot) : un message copie depuis Discord
porte `discord` (id du message) et un auteur FLUX lie par `/link`, sinon `Discord : <pseudo>`. `GET /team/{project}/discord`
lit `_flux_setup/discord_map.json` : lien Discord et personnes en vocal par canal (cles = rid, ou `general`), canaux
caches retires comme dans `/meta`. `ChatWidget` : bouton "Rejoindre sur Discord" d'un canal vocal sans lien d'appel,
"En vocal : ...", compteur dans la liste.

Edition / suppression (ADR 0084) : `chat_manager.edit_message` (auteur) et `delete_message` (auteur ou lead) ajoutent
un enregistrement `{"op": "edit" | "delete", "target"}` au journal ; `get_messages` les fusionne (`edited`, supprime =
absent) ; `read_chat` donne le brut au pont Discord. Routes `PATCH` / `DELETE /activity/chat/{id}`. `ChatWidget` :
crayon (auteur), corbeille avec confirmation (auteur, lead), "(modifie)".

Routes : `routers/team.py` (`/team/presence`, `/team/{project}/meta`, `/team/{project}/files`, `/team/{project}/discord`). Les messages passent par
`POST /activity/chat` (champs optionnels `channel`, `reply_to`, `attachments`, `notify_all`). Tests : `tests/team/`.

Options facon Discord (P5, ADR 0084 ajout 2026-10-31) : canal `title` (renommer), `topic`, `read_only` (envoi 403 aux
non-leads dans `POST /activity/chat`), types `text voice forum announcement` (annonces = lecture seule), vocal
`user_limit` (0 a 99) et `voice_status` (FLUX seulement) ; `#general` ne se renomme pas et reste texte ouvert. Groupe
`access` herite par ses canaux sans acces propre (`effective_access`, utilise par `hidden_channels`). `mutes.py` :
`USER/<artiste>/team_mutes.json` (`GET` / `PUT /team/{project}/mutes`), canaux / groupes en sourdine : pas de telephone
pour "Prevenir l'equipe" (`send_message(quiet=...)`), une @mention passe. `ChatWidget` : clic droit pour tous (marquer
comme lu, sourdine, copier le lien `/team?channel=..&message=..` que `pages/Team.tsx` ouvre), leads en plus (renommer,
sujet, lecture seule, type, limite / statut du vocal, dupliquer, qui voit, lien d'appel, archiver) ; groupe : nouveau
canal / vocal, qui voit ce groupe. Sujet sous l'en-tete, panneau epingles + fils actifs, vue forum (titre = premiere
ligne du message racine).
