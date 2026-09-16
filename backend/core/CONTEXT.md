# CONTEXT - `backend/core/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/backend__core.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

Socle : `config.py`, `paths.py` (FLUX_ROOT, mode frozen, `$FLUX`), `constants.py` (plages de ports DCC), `api_auth.py` (S1), `logger.py`, `dcc_instances.py`, `socket_manager.py`, frontiere metadonnees (`json_repository`, `sqlite_repository`, `remote_repository` squelette, `repository_factory` avec garde-fou SQLite hors OneDrive/reseau, `migrate_json_to_sqlite`, `export_sqlite_to_json`, `doc_keys` = cles logiques + wrapper SQLite/remote, ADR 0016), stockage (`local_storage`, `object_storage` squelette), `json_manager.py` (I/O atomiques bas niveau).

Zone a risque : `paths.py` et bootstrap `config.py`. Les stores passent par `get_repository()`, pas par `json_manager` (`backend/.importlinter`).
