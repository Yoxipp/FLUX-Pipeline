# CONTEXT - `backend/features/houdini_work/`

> Architecture : `docs/architecture/HOUDINI_WORK.md`, ADR 0051. Suivi : `docs/houdini_work/PROMPT_START.md`.

FLUX Work (travail Houdini versionne par tache, E2 du 2026-10-10). `work_store.py` (fonctions pures sur disque) :
* `work_dir(project, seq, shot, task)` : dossier departement du token `TYPE_SHOT` + `work/houdini/<TASK>/`. Template sans
  `{shot}` (LIGHT = `lighting/{seq}`) : le shot est ajoute. `shot` vide = tache de sequence (`<SEQ>/<dept>/work/houdini/<TASK>`).
* Versions `wNNN.json` + `wNNN.cpio` (w000 = template). `reserve_version` prend le numero par creation exclusive
  (`O_EXCL`, etat `writing`), jamais reutilise ; `commit_version` exige le `.cpio` et recalcule son hash
  (`dcc/houdini/hda/flux_work_io.normalized_hash`) ; `abort_version` ne retire jamais une version `ok`. Une reservation
  `writing` de plus de 15 min est `stale` (sauvegarde plantee).
* `lock.json` indicatif : `take_lock` (refus si tenu par un autre, `force` = reprise tracee `taken_from`),
  `release_lock` (seul le detenteur). `task_status` : versions, `latest`, `read_only`, `diverged` (`based_on` != derniere).

Les manifestes vivent avec les `.cpio` dans le dossier de travail (comme les fichiers publies), pas dans le
MetadataRepository : ils decrivent des octets ecrits par Houdini (ADR 0005).

Routes : `routers/houdini_work.py`, montees sous `/dcc/houdini/work` (`tasks`, `status`, `reserve`, `commit`, `abort`,
`lock`, `unlock`). Auteur par defaut = utilisateur courant du backend. Tests : `tests/houdini_work/`.
