# CONTEXT - `backend/core/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/backend__core.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

Socle : `config.py`, `paths.py` (FLUX_ROOT, mode frozen, `$FLUX`), `constants.py` (plages de ports DCC), `api_auth.py` (S1), `logger.py`, `dcc_instances.py`, `socket_manager.py`, frontiere metadonnees (`json_repository`, `sqlite_repository`, `remote_repository` squelette, `repository_factory` avec garde-fou SQLite hors OneDrive/reseau, `migrate_json_to_sqlite`, `export_sqlite_to_json`, `doc_keys` = cles logiques + wrapper SQLite/remote, ADR 0016), stockage (`local_storage`, `object_storage` squelette), `json_manager.py` (I/O atomiques bas niveau).

Repertoires FLUX connus du poste : `config.json` cle `workspaces` (`get_flux_roots` / `add_flux_root` / `remove_flux_root`), un seul actif = cle `workspace` (`set_flux_root` l'ajoute a la liste ; l'actif ne peut pas etre retire).

Sous-dossiers de FLUX_ROOT (`constants.FLUX_ROOT_DIRS`, crees au premier lancement et au changement de workspace) :
`USER`, `DOSSIER_PROJETS`, `CONFIG`, `FLUX_UPDATE` (installeurs, `get_update_dir`), `FLUX_DOC` (manuel, `get_doc_dir`, ADR 0049).
Patterns de detection des exe DCC : `DCC_EXE_PATTERN_GROUPS` (groupes de priorite, toutes les racines Program Files) et sa vue
plate `DCC_EXE_PATTERNS`.

Zone a risque : `paths.py` et bootstrap `config.py`. Les stores passent par `get_repository()`, pas par `json_manager` (`backend/.importlinter`).
