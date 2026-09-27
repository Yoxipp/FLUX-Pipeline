# CONTEXT - `backend/features/activity/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/backend__features__activity.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

Fil d'activite, chat, @mentions : `activity_writer.py`, `activity_reader.py`, `chat_manager.py`, `history.py` (JSONL append-only sous lock inter-process, rotation vers `CONFIG/archive/`), `read_state.py`. Routes : `routers/activity.py` (ETag via `repository.version_token`).

L'ancienne fiche reste juste pour JSONL/rotation, mais son ETag base sur `stat` est remplace par `version_token`.

Chat par projet (2026-09-27) : `DOSSIER_PROJETS/<projet>/teamChat.json` (`paths.get_project_chat_path`), plus de chat commun. `GET /activity/chat?project=` (sans projet ou projet inconnu : messages vides), `POST /activity/chat {project, message}` (400 nom invalide, 404 projet inconnu). `resolve_chat_path` refuse separateurs et `..`. Les @mentions restent globales par utilisateur et portent un champ `project`. L'ancien `CONFIG/teamChat.json` n'est plus lu (pas de migration : impossible de savoir a quel projet appartient chaque message) ; la migration SQLite prend les chats de chaque projet.
