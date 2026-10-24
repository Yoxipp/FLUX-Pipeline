# CONTEXT - `backend/routers/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/backend__routers.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

Couche HTTP, 12 routers : `actions`, `activity`, `dcc` (1770 l., logique metier a extraire), `files`, `folder_manager`, `logs`, `production`, `project`, `publish`, `settings`, `shelf`, `usd_assembler`.

Nouvelle logique = dans `features/`, le router reste mince.

Ajouts : `review` (ADR 0047, `features/review/keyframe.py`) : `GET /review/keyframe/status`,
`POST /review/keyframe/open` (echecs attendus renvoyes en `mode: none` + `code`, pas en HTTP 4xx).
`production` : `GET /{p}/ref/versions` (versions d'une zone `/ref` depuis son modif log) et
`POST /{p}/shot-previews` (LAST des zones `/ref` des taches des shots, apercu Timeline ; repli sur le dernier publish image/video de la tache). `GET /{p}/ref/file?scope=publish` streame ce publish. `POST /{p}/montage/export` exporte le montage (ADR 0053).
`GET /production/{p}` (2026-10-22) passe par `features/production/scan_cache.py` : un seul calcul a la fois par projet
(single-flight), resultat garde 1 s, ETag + 304 ; `main.py` vide ce cache apres toute requete non-GET hors
`/activity`, `/logs`, `/calendar`. Le calcul tourne dans `core/executors.HEAVY` (pool borne, separe des feeds).
`GET /publish/queue` : copies de publish actives / en attente (`features/publisher/copy_limits.py`).

## flows.py (2026-10-22, Flows P1)

Prefixe `/flows` : routes statiques (`catalog`, `rights`, `migrate`) avant `/{name}` ; lecture pour tous, chaque mutation
verifie d'abord les cases TD / Team TD (`flux_flows.rights`, garde-fou, pas une securite). Detail : `backend/flux_flows/CONTEXT.md`.
P2 : `POST /{name}/run` (brouillon de l'editeur, essai a blanc du fichier enregistre, version active), `GET /runs`,
`GET /runs/{run_id}`, `POST /runs/{run_id}/cancel` (TD ou lanceur), `WS /ws` (messages de run, file de 500 par client ;
`ApiAuthMiddleware` le couvre comme `/dcc/ws/status`). Les runs sont des taches asyncio du backend (`flux_flows.engine`).
P3 : `POST /preview` (apercu resolve | pattern, aucun node lance), `GET /nodes/template` (modele de node d'equipe), statiques.
P4 : `POST /validate {flow, scope, project?}` -> `{issues, valid}` (statique, n'ecrit rien). PUT et `increment` revalident
(`valid` dans `state.json`, enregistrer avec erreurs reste permis) et refusent en 409 `{code: E_DESTRUCTIVE_UNCONFIRMED, issues}`
un node `!` ajoute sans figurer dans `confirmed_destructive` ; `revert` revalide ; `activate` refuse une version figee en
erreur (409 `{gate}`) ; le run est refuse (409 `refused`) si la validation trouve une erreur.
P7 (pages TOOL, ADR 0066) : `GET /pages` -> `{pages, templates, can_edit}`, `POST /pages/validate`, `GET /pages/{id}`
(`scope` absent = project > team, `scope=shipped` = un modele), `PUT /pages/{id} {scope, page, base_rev, force}` et
`DELETE /pages/{id}` (Team TD), `GET /pages/{id}/history`. Statiques (avant `/{name}`) ; WS `page_changed` apres une ecriture.
P5 : `GET /host` (detenteur du verrou, surveillants de ce poste), `POST /events/scene_opened {soft, scene, port?, pid?}`
(script cote logiciel), `GET /{name}/activation` (3 voyants : erreurs, avertissements `acked`, `dry_run`) ; `activate
{scope, acked}` exige 0 erreur, avertissements lus et essai a blanc reussi sur `current` (409 `{gate}` sinon), note le dernier
creneau `Schedule` ; `run {dry_run, version?}` ecrit `dry_run_ok` dans `state.json` a la fin d'un essai `ok` de `current` ;
WS `host`, `activation`, `flow_changed` (save, increment, revert). `dcc.py` : `instance_context` vit dans `core/dcc_context.py`.
P4 (editeur) : `POST /nodes {name, code}` (Team TD) ecrit `CONFIG/extensions/nodes/<name>.py` (marqueur `@flow_node` requis,
fichier garde meme s'il ne charge pas, `error` = erreur de chargement de ce fichier) ; `GET /{name}/versions` rend aussi
`user` par version et `history` (lignes `history.jsonl` du flow, recentes d'abord).
