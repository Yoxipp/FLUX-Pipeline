# CONTEXT - `backend/features/dispatcher/`

> Decision : ADR 0067 (complete 0015 et 0057).

Le dispatcher du pipe : envoyer un job (des taches) sans nommer le gestionnaire de farm. Les nodes de la famille
`dispatcher` des Flows (`flux_flows/nodes/dispatcher.py`) et le mode `dispatch` de ForEach passent par `api.py`.

* `config.py` : `CONFIG/dispatcher.json` (pipe) surcharge cle par cle par `<projet>/_flux_setup/dispatcher.json`.
  Pas de fichier = `{"backend": "local"}` + defauts. Cles stables (ADR 0004) :

  ```json
  {"schema_version": 1, "backend": "local", "local": {"max_parallel": 2},
   "programs": {"husk": {"local": "husk", "tractor": "husk"}, "hython": {"local": "hython", "tractor": "hython"}},
   "priority": 100, "chunk_size": 5}
  ```

  `programs` = liste blanche : une tache ne lance qu'un programme declare, pour le backend courant (chemin complet
  conseille en local). Les reglages de connexion Tractor restent dans `render.json` du projet (`features/render`).
* `jobs.py` : `DispatchJob` / `DispatchTask` (programme + liste d'arguments, jamais de shell), etats communs
  `waiting active done error cancelled simulated`, `job_id` = `<backend>:<id>` (le backend suit le job meme si la config
  change ensuite).
* `local_backend.py` : sous-process sur ce poste, `max_parallel` taches a la fois sur tout le backend, depart differe
  (`start_after`), annulation (arrete les taches en cours). Jobs en memoire : perdus au redemarrage du backend FLUX.
* `tractor_backend.py` : job Alfred generique (une Task / RemoteCmd par tache) avec les gardes de `render/job_builder`
  (mots Tcl surs, pas de lettre de lecteur en spool reel), pont `render/tractor_bridge`. `render.json` `dry_run: true`
  = `.alf` + `.json` ecrits (dans `record_dir` ou `_flux_setup/dispatch/<date>`), rien n'est spoole, etat `simulated`.
  Annuler = `kill` du pont (refuse sur un job d'un autre utilisateur FLUX).
* `render_shot.py` : job RenderShot (husk Karma / RenderMan) comme l'onglet Render : gel LAST -> vNNN, plage du plan
  ou du USD, une tache par paquet de frames, `render/vNNN`. `plan(dry=True)` n'ecrit rien.
* `api.py` : `submit`, `status`, `cancel`, `farm_path`, `effective_config`.

Dette : `/render/submit` (onglet Render, HDA Houdini) garde son chemin Tractor direct ; le faire passer par
`render_shot` + `api.submit`. Spool reel Tractor jamais execute (phase 0 de la farm, ADR 0015).

Tests : `backend/tests/dispatcher/` (config, backend local avec de vrais sous-process Python, Alfred, simulation,
plan RenderShot) et `tests/test_flux_flows/test_dispatcher_nodes.py` (nodes et ForEach dispatch dans le moteur).
