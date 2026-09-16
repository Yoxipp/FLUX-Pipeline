# CONTEXT - `backend/features/folder_manager/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/backend__features__folder_manager.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

Creation projet / assets / seq / shots : `project_init.py`, `asset_creator.py`, `seq_shot_creator.py`, `tokens.py` + `naming_validator.py` (nommage par tokens), `preset_manager.py`, `locks.py`, `sequence_template.py` (USD seq/shot), `houdini_scene_template.py` (scene lighting).

Les cles de `locks.py` sont des chemins absolus (ADR 0004 proposee).
