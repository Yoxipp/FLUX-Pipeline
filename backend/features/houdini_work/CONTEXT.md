# CONTEXT - `backend/features/houdini_work/`

> Architecture : `docs/architecture/HOUDINI_WORK.md`, ADR 0051 puis ADR 0090 (un travail = une scene `.hip`).
> Suivi : `docs/notes/prompts/houdini_work/PROMPT_START.md`.

FLUX Work (travail Houdini versionne par tache). `work_store.py` (fonctions pures sur disque) :
* `work_dir(project, seq, shot, task)` : dossier departement du token `TYPE_SHOT` + `work/houdini/<TASK>/`. Template sans
  `{shot}` (LIGHT = `lighting/{seq}` d'un projet d'avant ADR 0055) : le shot est ajoute. `shot` vide = tache de sequence,
  template sans le niveau shot (`shot/<SEQ>/lighting/work/houdini/LIGHT`).
* Versions `wNNN.json` + `wNNN.hip|.hiplc|.hipnc` (w000 = template ; extension selon la licence qui a sauve,
  `hip_ext_for_license`). `reserve_version` prend le numero par creation exclusive (`O_EXCL`, etat `writing`), jamais
  reutilise, et donne le chemin `hip` ; `commit_version` exige la scene sur disque (pas de hash : deux saves identiques
  d'un .hip different, ADR 0090) ; `abort_version` ne retire jamais une version `ok`. Une reservation `writing` de plus
  de 15 min est `stale` (sauvegarde plantee). Le manifeste porte `project`, `seq`, `shot`, `task`.
* `start_work` : scene a ouvrir pour une tache (derniere version `ok`) ; tache vide = template copie en `w000`
  (jamais par-dessus un fichier). Houdini ouvre w000, pose le contexte et sauve `w001` tout de suite.
* `identify(path)` : tache d'une scene ouverte `.../wNNN.<ext>` depuis son manifeste (None = scene libre).
* `lock.json` indicatif : `take_lock` (refus si tenu par un autre, `force` = reprise tracee `taken_from`),
  `release_lock` (seul le detenteur). `task_status` : versions, `latest`, `read_only`, `diverged` (`based_on` != derniere).
* Templates : `template_hip` (projet `template/houdini_work/<TASK>.hip*` > FLUX `<TASK>.hip` > FLUX
  `DEFAULT_SOP.hip` / `DEFAULT_LOP.hip` selon `TASK_CATEGORY`). FLUX livre `resources/scenes/houdini/work/`
  (`RENDER.hip`, `DEFAULT_SOP.hip`, `DEFAULT_LOP.hip`), construits par `dcc/houdini/work_template_build.py` (hython).

Les manifestes vivent avec les scenes dans le dossier de travail (comme les fichiers publies), pas dans le
MetadataRepository : ils decrivent des octets ecrits par Houdini (ADR 0005).

`render_sync.py` (addendum ADR 0051, suivi en direct via `dcc/houdini/shot_sync.py` -> `follow_timeline_from_flux`) :
Work RENDER <-> Timeline Production, comparaison a trois scene / `render_blocks` de la version chargee / Production
(`plan` : push, pull, conflicts, create, missing ; `apply` : plages + shots crees, verrous respectes).

`backup_cleaner.py` (ADR 0090 point 8, ADR 0092) : `scan` / `apply` des backups Houdini des dossiers FLUX Work
(`backup/`, `*_bak*`, jamais `wNNN`) et des copies d'autosave du projet sur ce poste, plus vieux que `keep_days()`
(reglage `houdini_backup_keep_days`, defaut 14, 0 = coupe), le plus recent de chaque scene garde. `apply` ne supprime que
les ids d'un nouveau scan, journal `.flux_cleanup/houdini_backups/`. Routes dans `routers/folder_manager.py`
(`/folder/projects/{p}/cleanup/houdini-backups`) ; UI : onglet Disque et panneau des Supervisors a 13h / 18h.

Routes : `routers/houdini_work.py`, montees sous `/dcc/houdini/work` (`tasks`, `status`, `reserve`, `commit`, `abort`,
`start`, `identify`, `open`, `launch`, `lock`, `unlock`, `module`, `shots`, `template`, `render-sync/plan`,
`render-sync/apply`). `open` = menu clic droit d'une tache CFX / FX / LIGHT / RENDER dans Production
(`dcc/houdini/work_open.py` : envoi par `/run` au Houdini deja sur la scene, sinon vierge, sinon le premier ; sinon
lancement). `launch` n'accepte qu'une scene FLUX Work. Auteur par defaut = utilisateur courant du backend.
Tests : `tests/houdini_work/`.
