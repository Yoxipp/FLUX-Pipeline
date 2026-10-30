# features/team — page Team facon Teams (ADR 0077)

Autour du chat d'equipe existant (`features/activity/chat_manager.py`, `teamChat.json` du projet), sans serveur.

| Fichier | Role |
|---|---|
| `team_meta.py` | Canaux (lead : nom, sujet, lien d'appel https, archive, `access` JSON qui voit le canal, ADR 0080 : `parse_access`, `hidden_channels` ; leads / sups voient tout, `#general` ouvert), reactions (une par auteur, retiree par son auteur) et messages epingles (lead), en journaux par auteur `_flux_setup/team/<AUTEUR>.jsonl` (moteur `flux_flows/page_data.py`). |
| `presence.py` | `USER/<artiste>/presence.json` reecrit par son seul auteur (`status` available / away / meeting / dnd, `text`, `at`) ; en ligne si moins de 150 s. |
| `files.py` | Fichiers joints COPIES par le backend dans `_flux_setup/team_files/<hash>.<ext>` (200 Mo max, programmes et scripts refuses). |

Routes : `routers/team.py` (`/team/presence`, `/team/{project}/meta`, `/team/{project}/files`). Les messages passent par
`POST /activity/chat` (champs optionnels `channel`, `reply_to`, `attachments`, `notify_all`). Tests : `tests/team/`.
