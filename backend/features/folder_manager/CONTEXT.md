# CONTEXT - `backend/features/folder_manager/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee de mai 2026 retiree (lisible au tag `archive/pre-cleanup`).
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

Creation projet / assets / seq / shots : `project_init.py`, `asset_creator.py`, `seq_shot_creator.py`, `tokens.py` + `naming_validator.py` (nommage par tokens), `preset_manager.py`, `locks.py`, `sequence_template.py` (USD seq/shot), `houdini_render_scene.py` (ADR 0036 / 0037 : scene de rendu de sequence `<SEQ>_render.hip` = template du mainteneur `resources/scenes/houdini/flux_template_sequence_render.hip` + FLUX Sequence + une chaine CRYPTO / RENDER_SETTINGS / FLUX Render / ROP par bloc, au moins 3 blocs, hython isole, jamais ecrasee ; preset livre "Rendu <SEQ>" via `builtin_presets` / `open_builtin_preset`, `GET presets?builtin=1`), `houdini_scene_template.py` (scene lighting).

`project_config.py` (V8 U1, ADR 0006/0011) : `<projet>/_flux_setup/project.json` (ADR 0054 : tous les fichiers FLUX du projet vivent dans `_flux_setup/`, resolus par `core/project_setup.setup_path`, migration a l'ouverture ; `locks.py` verrouille toujours `_flux_setup`) = `project_id` stable, `schema_version`, fps, resolution, `usd` (1.0 / Y), `ocio_config`, `env`, `storage`. Cree par `create_project` et automatiquement a la premiere ouverture (`PUT /project/current`, `GET /folder/projects/{p}/tokens`, `GET /folder/projects/{p}/config`). Creation exclusive `O_EXCL` puis relecture ; auto-heal des cles manquantes sans toucher aux valeurs ; fichier illisible deplace en `project.corrupt-<stamp>.json` ; copies de conflit OneDrive `project-*.json` : le `project_id` au `created_at` le plus ancien gagne (warning, copies jamais supprimees). Fenetre "Parametres avances" a la creation d'un projet (front `ProjectSettingsDialog.tsx`, Enregistrer / Passer) : generee depuis `PROJECT_SCHEMA` renvoye par `GET .../config` (`title` = libelle, `x-flux-hidden` = masque ; une cle de project.json absente du schema s'affiche quand meme, champ deduit de la valeur) ; ecrite par `PUT /folder/projects/{p}/config` -> `write_project_settings` (fusion des cles de premier niveau, identite protegee, refus 400 si schema invalide). Nouvelle option = propriete + `title` dans `PROJECT_SCHEMA` + defaut dans `default_project_config`. Schema JSON en ligne, erreurs = warnings (jamais bloquant).

Les cles de `locks.py` sont des chemins absolus (ADR 0004 proposee).

`update_sequence` (appele par la sync Production) : dossier d'une tache de plan = TYPE_SHOT (ADR 0019),
repli CLASS pour les anciens projets, puis `shot/{seq}/{shot}/<token>` (`shot_task_template`). Un template
avec un placeholder inconnu ne cree rien. Avec `counts=`, il ajoute ce qu'il a vraiment cree
(`sequences`, `shots`, `tasks` dont dossiers de departement de la base, `subtasks`). Create-only : un
dossier deja cree a l'ancien emplacement n'est ni deplace ni supprime.

Tokens : `load_tokens` fusionne toujours les defauts (`core/constants.py` : CLASS, TYPE, TYPE_SHOT, INSTANCE) sous les valeurs du projet. Departements de plan par defaut : LAYOUT, ANIM, FX, CFX, CROWD, LIGHT (`lighting`), COMP (`comp`), RENDER (`render`) dans `shot/{seq}/{shot}` (ADR 0055). Un `tokens.json` existant sans LIGHT / COMP / RENDER recoit les anciens chemins (`lighting/{seq}`, `comp/{seq}/{shot}`, `render/{seq}/{shot}`, `LEGACY_SHOT_ROOT_TOKENS`). `GET /folder/projects/{p}/sequences` renvoie aussi `padding` (`SEQ_SHOT_PADDING`) pour que le Publisher numerote les nouveaux SEQ/SHOT comme le backend.

`asset_cleanup.py` (ADR 0033) : nettoyage d'un asset / du projet et clone propre. Les regles viennent du code
courant (`resolve_publish_path`, parseur de noms, `MAP_ALIASES`), jamais d'une liste d'anciens formats : ne pas
en ajouter. Seul ce qui est sur se fait (remise a sa place, doublon identique retire), annulable par le journal
`.flux_cleanup/` ; le reste est un avertissement.
