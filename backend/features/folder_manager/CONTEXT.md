# CONTEXT - `backend/features/folder_manager/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/backend__features__folder_manager.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

Creation projet / assets / seq / shots : `project_init.py`, `asset_creator.py`, `seq_shot_creator.py`, `tokens.py` + `naming_validator.py` (nommage par tokens), `preset_manager.py`, `locks.py`, `sequence_template.py` (USD seq/shot), `houdini_render_scene.py` (ADR 0036 : scene de rendu de sequence `<SEQ>_render.hip`, un FLUX Shot + Karma + ROP par shot, hython isole, jamais ecrasee), `houdini_scene_template.py` (scene lighting).

`project_config.py` (V8 U1, ADR 0006/0011) : `<projet>/project.json` = `project_id` stable, `schema_version`, fps, resolution, `usd` (1.0 / Y), `ocio_config`, `env`, `storage`. Cree par `create_project` et automatiquement a la premiere ouverture (`PUT /project/current`, `GET /folder/projects/{p}/tokens`, `GET /folder/projects/{p}/config`). Creation exclusive `O_EXCL` puis relecture ; auto-heal des cles manquantes sans toucher aux valeurs ; fichier illisible deplace en `project.corrupt-<stamp>.json` ; copies de conflit OneDrive `project-*.json` : le `project_id` au `created_at` le plus ancien gagne (warning, copies jamais supprimees). Schema JSON en ligne, erreurs = warnings (jamais bloquant).

Les cles de `locks.py` sont des chemins absolus (ADR 0004 proposee).

`asset_cleanup.py` (ADR 0033) : nettoyage d'un asset / du projet et clone propre. Les regles viennent du code
courant (`resolve_publish_path`, parseur de noms, `MAP_ALIASES`), jamais d'une liste d'anciens formats : ne pas
en ajouter. Seul ce qui est sur se fait (remise a sa place, doublon identique retire), annulable par le journal
`.flux_cleanup/` ; le reste est un avertissement.
