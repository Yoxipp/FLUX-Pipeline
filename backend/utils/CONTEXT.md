# CONTEXT - `backend/utils/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/backend__utils.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

`project_utils.py`, `user_utils.py` : helpers projet/utilisateur.

`user_utils.get_enabled_dccs` / `set_enabled_dccs` (V8 U10) : liste `enabled_dccs` dans `User.json` ; absente = toutes les DCC (compat). Cles validees contre `launcher_core.DCC_FRONTEND_KEYS`. Routes `GET/PUT /settings/enabled-dccs`.
