# CONTEXT - `backend/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/backend.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

Sidecar FastAPI (`main.py`, port `FLUX_PORT` defaut 8765, 12 routers, middleware jeton S1). Packages : `core/`, `features/`, `flux_core/`, `flux_actions/`, `flux_flows/` (Flows v2, voir son CONTEXT.md), `dcc/`, `routers/`, `utils/`, `resources/`, `tests/`.

Tests : depuis `backend/`, `python tests/run_tests.py` (verdict PASS attendu).
