# CONTEXT - `backend/features/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/backend__features.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

Metier par domaine : `folder_manager`, `production`, `publisher`, `importer`, `activity`, `launcher`, `shelf_manager`, `usd_assembler`, `usd_export`.

`usd_assembler/shot_stage.py` (A4, ADR 0020) : stage de shot genere depuis le casting Production et les departements du shot.
`usd_assembler/component_recipe.py` + `component_auto.py` (ADR 0023) : component cree a la main (`create_component`), recette = departements (tokens TYPE d'asset, une fois chacun) + fichiers (publish ou chemin manuel, format par extension, nature, cibles, proxy de, dependances). Un variantSet `on`/`off` par fichier dans la couche du departement. Un publish ne cree jamais de component : `refresh_from_publish` re-compose seulement un component existant qui utilise ce departement. Les nouveaux publishs sont proposes (`proposed_files`), jamais ajoutes seuls. Anciens components (slots, ADR 0019) lus comme recette (`_legacy_recipe`), reecrits au format 0023 a la mise a jour suivante. ADR 0024 : les fichiers ("links") sont groupes en blocks a nom libre (`model` / `look` / `rig` a la creation) ; chaque link porte sa task (`department`), son arc (`reference` / `payload` / `sublayer` : ce dernier entre dans les sublayers du payload, toujours actif), une variante optionnelle (variantSet du block, un seul choix actif) et une case proxy (proxy des autres links du block). `departments` = tasks des links. Recette 0023 sans `blocks` : un block par task.

Metadonnees via `core.repository_factory.get_repository()`, octets via filesystem / `get_storage()`.
