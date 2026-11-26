# CONTEXT - `backend/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee de mai 2026 retiree (lisible au tag `archive/pre-cleanup`).
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`.

Sidecar FastAPI (`main.py`, port `FLUX_PORT` defaut 8765, 12 routers, middleware jeton S1). Packages : `core/`, `features/`, `flux_core/`, `flux_actions/`, `flux_flows/` (Flows v2, publish par flow en v2 depuis P8, voir son CONTEXT.md), `dcc/`, `routers/`, `utils/`, `resources/`, `tests/`.

Tests : depuis `backend/`, `python tests/run_tests.py` (verdict PASS attendu).
