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

Routes : `routers/team.py` (`/team/presence`, `/team/{project}/meta`, `/team/{project}/files`, `/team/{project}/discord`). Les messages passent par
`POST /activity/chat` (champs optionnels `channel`, `reply_to`, `attachments`, `notify_all`). Tests : `tests/team/`.
