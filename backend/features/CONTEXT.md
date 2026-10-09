# CONTEXT - `backend/features/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/backend__features.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

Metier par domaine : `folder_manager`, `production`, `publisher`, `importer`, `activity`, `launcher`, `shelf_manager`, `usd_assembler`, `usd_export`.

`usd_assembler/shot_stage.py` (A4, ADR 0020) : stage de shot genere depuis le casting Production et les departements du shot.
Version epinglee (ADR 0048) : champ optionnel `version` ("vNNN") sur un lien de casting, absent / "" = `LAST` ; le pin du
shot gagne sur celui de la sequence, un lien sans pin garde celui de la sequence ; `_asset_target` vise
`<NAME>_vNNN/<NAME>.usda` (introuvable = warning + `LAST`) ; toutes les instances `_NN` partagent la version ; le chemin
entre dans la signature (pin change = nouvelle version du stage) ; `shot_summary` rend `version` / `latest_version`.
`usd_assembler/extents.py` (R2, `docs/architecture/USD_STRATEGY.md`) : `extentsHint` ecrit sur l'entree du component et de l'assembly (bound visible payload decharge ; un decor utilise les hints de ses components, sans lire leur geometrie). `usd_assembler/validate/publish_check.py` (R3) : controle USD de chaque publish, appele en premier par `publisher/usd_publish_hooks.after_usd_publish` (cle `issues`), warn seulement, ligne "controle USD" dans `modif_logs.json`. `usd_assembler/inspect.py` (R4) : ouvert en `LoadNone`, seul le payload de la racine est charge.
`usd_assembler/component_recipe.py` + `component_auto.py` (ADR 0023) : component cree a la main (`create_component`), recette = departements (tokens TYPE d'asset, une fois chacun) + fichiers (publish ou chemin manuel, format par extension, nature, cibles, proxy de, dependances). Un variantSet `on`/`off` par fichier dans la couche du departement. Un publish ne cree jamais de component : `refresh_from_publish` re-compose seulement un component existant qui utilise ce departement. Les nouveaux publishs sont proposes (`proposed_files`), jamais ajoutes seuls. Anciens components (slots, ADR 0019) lus comme recette (`_legacy_recipe`), reecrits au format 0023 a la mise a jour suivante. ADR 0024 : les fichiers ("links") sont groupes en blocks a nom libre (`model` / `look` / `rig` a la creation) ; chaque link porte sa task (`department`), son arc (`reference` / `payload` / `sublayer` : ce dernier entre dans les sublayers du payload, toujours actif), une variante optionnelle (variantSet du block, un seul choix actif) et une case proxy (proxy des autres links du block). `departments` = tasks des links. Recette 0023 sans `blocks` : un block par task.

Metadonnees via `core.repository_factory.get_repository()`, octets via filesystem / `get_storage()`.

`review/keyframe.py` (ADR 0047) : client du protocole de l'API externe de Keyframe Pro (port 18181,
entete 10 caracteres + JSON), projet = une timeline dans l'ordre + autres videos du dossier ; repli
ligne de commande (premiere video) en mode Demo. `production/ref_media.py` : chaque depot `/ref` est
journalise dans `ref/modif_logs.json` (versions, auteur), `versions()` et `shot_previews()`.
Racine d'une tache de plan (`resolve_ref_root`, bug A5 2026-10-09) : TYPE_SHOT, puis CLASS (anciens
projets), puis `shot/{seq}/{shot}/<token>` ; un `/ref` deja present sous une ancienne resolution gagne.
`production/sync.py` (Production -> disque, create-only) : le resume renvoye/loggue compte ce qui est
vraiment cree (`assets`, `sequences`, `shots`, `tasks`, `subtasks`, 0 partout si rien) ; le token
d'une tache de plan = `type_tokens[0]` s'il est connu des maps, sinon `name`.
