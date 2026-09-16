# CONTEXT - `backend/routers/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/backend__routers.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

Couche HTTP, 12 routers : `actions`, `activity`, `dcc` (1770 l., logique metier a extraire), `files`, `folder_manager`, `logs`, `production`, `project`, `publish`, `settings`, `shelf`, `usd_assembler`.

Nouvelle logique = dans `features/`, le router reste mince.
