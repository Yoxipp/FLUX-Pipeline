# CONTEXT - `backend/features/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/backend__features.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

Metier par domaine : `folder_manager`, `production`, `publisher`, `importer`, `activity`, `launcher`, `shelf_manager`, `usd_assembler`, `usd_export`.

`usd_assembler/shot_stage.py` (A4, ADR 0020) : stage de shot genere depuis le casting Production et les departements du shot.

Metadonnees via `core.repository_factory.get_repository()`, octets via filesystem / `get_storage()`.
