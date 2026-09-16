# CONTEXT - `backend/features/activity/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/backend__features__activity.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

Fil d'activite, chat, @mentions : `activity_writer.py`, `activity_reader.py`, `chat_manager.py`, `history.py` (JSONL append-only sous lock inter-process, rotation vers `CONFIG/archive/`), `read_state.py`. Routes : `routers/activity.py` (ETag via `repository.version_token`).

L'ancienne fiche reste juste pour JSONL/rotation, mais son ETag base sur `stat` est remplace par `version_token`.
