# features/team — chat d'equipe du widget TOOL `chat` (ADR 0077, 0091)

Autour du chat d'equipe existant (`features/activity/chat_manager.py`, `teamChat.json` du projet), sans serveur.
ADR 0091 : la page Team (`/team`), la presence, les liens d'appel et le pont Discord sont retires ; le chat vit dans
le widget TOOL `chat` (`app/src/pages/tool_pages/ChatWidget.tsx`). Les journaux `_flux_setup/team/` restent.

| Fichier | Role |
|---|---|
| `team_meta.py` | Canaux (lead : nom, sujet, archive, `access` JSON qui voit le canal, ADR 0080 : `parse_access`, `hidden_channels` ; leads / sups voient tout, `#general` ouvert), reactions (une par auteur, retiree par son auteur) et messages epingles (lead), en journaux par auteur `_flux_setup/team/<AUTEUR>.jsonl` (moteur `flux_flows/page_data.py`). Groupes de canaux (ADR 0084) : `kind: group` (`name`, `order`), canal `type` text / voice / forum / announcement, `group` = rid du groupe, `order` ; leads. Le champ `call_link` reste accepte (anciens journaux) mais n'est plus affiche. |
| `files.py` | Fichiers joints COPIES par le backend dans `_flux_setup/team_files/<hash>.<ext>` (200 Mo max, programmes et scripts refuses). `store_bytes` : meme regle pour des octets recus. |
| `mutes.py` | `USER/<artiste>/team_mutes.json` (`GET` / `PUT /team/{project}/mutes`), canaux / groupes en sourdine : pas de notification pour "Prevenir l'equipe" (`send_message(quiet=...)`), une @mention passe. |

Edition / suppression (ADR 0084) : `chat_manager.edit_message` (auteur) et `delete_message` (auteur ou lead) ajoutent
un enregistrement `{"op": "edit" | "delete", "target"}` au journal ; `get_messages` les fusionne (`edited`, supprime =
absent). Routes `PATCH` / `DELETE /activity/chat/{id}`. Un ancien message copie depuis Discord garde son champ `discord`.

Routes : `routers/team.py` (`/team/{project}/meta`, `/team/{project}/files`, `/team/{project}/mutes`). Les messages passent par
`POST /activity/chat` (champs optionnels `channel`, `reply_to`, `attachments`, `notify_all`). Tests : `tests/team/`.

Options (P5, ADR 0084 ajout 2026-10-31) : canal `title` (renommer), `topic`, `read_only` (envoi 403 aux non-leads dans
`POST /activity/chat`), types `text voice forum announcement` (annonces = lecture seule), vocal `user_limit` (0 a 99) et
`voice_status` ; `#general` ne se renomme pas et reste texte ouvert. Groupe `access` herite par ses canaux sans acces
propre (`effective_access`, utilise par `hidden_channels`).
