# backend/flux_flows - Flows v2 (format, stockage, droits, migration)

Chantier Flows (ADR 0057, 0058 ; specs `docs/yaml_update_refonte/`). Package neuf : `flux_core` et `flux_actions`
ne sont pas modifies, le publish tourne encore sur les actions v1 jusqu'a P8. Etat au 2026-10-22 : P1 fait
(prompt `docs/yaml_update_refonte/prompts/P1_format_v2_stockage.md`). P2 fait (prompt `P2_moteur_runs.md`) :
moteur, runs, essai a blanc, WS, 11 types de node. P4 (backend, 2026-10-23) : validation complete (`validate.py`).
Pas encore d'evenement automatique (P5).

## Fichiers

| Fichier | Role |
|---|---|
| `model.py` | Schema v2 strict (pydantic `extra="forbid"`), `parse_flow`, `load_flow_text`, `dump_flow` (emission YAML stable, sert aussi de forme canonique), `to_document`, `v1_limit_issues`. Nom `^[a-z][a-z0-9_]{1,40}$`, noms reserves (routes statiques + `rights`), 1 Mo, 500 nodes. Node `subnet` (ses `nodes` / `links`), flag `bypass`. `origin` d'un flow migre : `kind`, `name`, `shelf`, `thumbnail`, `extends`, `params`. |
| `types.py` | Types de ports, `can_connect` -> ok / implicite / incompatible + raison fr / en (ADR 0058 : un lien incompatible est accepte par le modele, la validation P4 le signale). |
| `nodes/registry.py` | `@flow_node` (doc fr / en, exemple par port, shelf, alias, `effect`), 10 familles, chargeur des nodes d'equipe (`CONFIG/extensions/nodes/`, seulement les fichiers qui contiennent `@flow_node`, portee team seulement). P3 : rechargement **par fichier** (mtime + taille ; seul le fichier change est reimporte, un fichier supprime retire ses nodes), builtins charges avant (un fichier d'equipe ne peut pas prendre un type FLUX : erreur du fichier), fichier casse = `node_errors` du catalogue, les autres marchent. Le moteur recharge l'equipe avant de refuser un type inconnu. Modele : `shipped/team_node_template.py` (`GET /flows/nodes/template`). Un node a effet (`effect=True` ou destructif) sans `simulate` est refuse. `ensure_builtin()` importe les modules FLUX (`BUILTIN_MODULES`). |
| `resolver.py` | Resolveur de texte unique (01 §11) : `{token}`, `{date:%Y%m%d}`, `${var}`, `$FLUX` en tete d'un champ path / dir, `{{ }}`. Token inconnu = `E_UNKNOWN_TOKEN` + suggestion Levenshtein <= 2 ; `tokens_in` pour le validateur (P4). Applique par le moteur aux params et litteraux non lies (`spec.raw` les exclut), jamais a une valeur arrivee par un lien. |
| `patterns.py` | Motifs facon Houdini (01 §11) : `*`, `**`, `?`, `[abc]`, `^` / `!`, gauche a droite ; motif vide = ne garde rien. |
| `nodes/common.py` | `as_path`, `in_project`, `check_destructive_target` (erase / overwrite seulement sous FLUX_ROOT, jamais une racine ni un dossier projet), archive projet partagee (`archive_preview`, `archive_into_project`, via `archive_folder`). |
| `nodes/contract.py` | Contrat d'un corps de node : `body(ctx, inputs, params) -> {port: valeur}`, `simulate(...) -> {lines, outputs}`, `NodeError` (message affiche sur le node), `NodeContext` (`context`, `interface`, `cancelled`, `log`, `notify`, variables), `EXEC_KEY` (`_exec`) pour choisir la sortie exec. |
| `nodes/event.py`, `data.py`, `logic.py`, `operator.py`, `action.py`, `flux.py`, `subflow.py` | Nodes P2 + P3 (02 §11, liste exacte). P3 : data (path, python_value lu par AST sans executer, json_value, template, context), logic (8), operator (26, dont sequence, for, while au plafond 1000, break_loop), action (12, logique partagee avec les commandes v1 de `flux_actions/commands/utility.py` ; `delete` archive par defaut, `erase` destructif), flux (19 : `find_publishes` deduit soft / type / version du nom et de l'extension, une capture sans soft connu passe le filtre soft ; `publish_file` appelle `run_publish_action`, `publish_core` non modifie ; `call_function` v2 reutilise la garde v1 `features`, `core`, `dcc` ; `ping` = message de chat), subflow (`flow_call` profondeur 8 + cycle, `flow_output`). Chaque node a effet a un `simulate` qui n'ecrit rien. |
| `validate.py` | P4 : validation (01 §8), fait foi a l'enregistrement, au lancement, a l'activation et pour `POST /flows/validate`. `validate(flow, Env)` -> `Issue {level, code, node, port, message_fr/en, why_fr/en, fix {kind, args}, link}` ; tous les codes de 01 §8 ; `unconfirmed_destructive` (E_DESTRUCTIVE_UNCONFIRMED, compare au fichier de travail) ; `errors(issues, dry_run)` (un E_TYPE_MISMATCH ne bloque pas l'essai a blanc, ADR 0058). Voir "Validation" ci-dessous. |
| `engine.py` | Moteur exec + data (01 §4), `Run` (un run) et `RunManager` (admission, un par boucle asyncio : `engine.manager()`). |
| `runs.py` | Enregistrements de run (01 §6) : id, ecriture atomique, liste, retention, `interrupted`. |
| `events.py` | Bus interne thread-safe, feuille stdlib (01 §1) : `subscribe` / `emit`, file bornee par abonne. |
| `locations.py` | Dossier de chaque portee ; `roots_for(user, project)` construit le dict `{portee: dossier ou None}` du store (nom de projet = un nom de dossier, jamais un chemin). |
| `store.py` | Portees, fichier de travail, versions figees, `state.json`, `history.jsonl`, `_trash/`, verrou, ecriture atomique, conflit 409. |
| `rights.py` | Cases TD / Team TD, table de 01 §7, 403. |
| `migrate_v1.py` | Actions v1 -> flows (script de dev pour `shipped/`, `POST /flows/migrate` pour l'equipe). |
| `shipped/` | Flows livres, lecture seule, dans l'exe (`scripts/backend.spec`, dossier copie recursivement). Les 5 `legacy_*`, 2 exemples P2 (`example_foreach`, `example_error`) et l'exemple P3 `example_daily_render` (bouton `daily_render` ; le Schedule viendra en P5), a la racine pour etre ouvrables : le store ne liste que ce niveau. `team_node_template.py` : modele de node d'equipe (ignore par le store). |

## Stockage (ADR 0058, prime sur 01 §6)

| Portee | Dossier | Ecrit par |
|---|---|---|
| shipped | `backend/flux_flows/shipped/` | personne (copie d'equipe = "unlock") |
| team | `<FLUX_ROOT>/CONFIG/extensions/flows/` + `../history.jsonl` | Team TD |
| project | `<projet>/_flux_setup/flows/` + `history.jsonl` (verrouille dans le Folder Manager avec tout `_flux_setup/`) | Team TD |
| perso | `<FLUX_ROOT>/USER/<NOM>/flows/` (pas d'historique) | TD proprietaire |

* `D/<nom>.flow.yml` = fichier de travail (Enregistrer l'ecrase, ligne `save`). `D/<nom>/versions/<nom>_vNNN.flow.yml` = version figee
  (Enregistrer et incrementer, seulement si le contenu canonique change, ligne `increment`). `D/<nom>/state.json` =
  `{current, active_version, active, revision, saved_by, saved_at}` ; `current` = derniere version figee (0 = aucune).
* Conflit (proposition) : l'editeur renvoie `base_revision` (la `revision` lue) ; autre ecriture depuis = 409 `{revision, by, at}` ;
  `force` = ecraser. `base_revision` absent = nouveau flow : 409 si le nom existe.
* Revenir a vN : le fichier de travail devient vN puis est fige en v(max+1) (rien n'est perdu). Supprimer : `D/_trash/<nom>_<date>/`.
* Resolution d'un nom : perso > project > team > shipped (`resolve`, `shadowed` dans la liste).
* Activation : refusee pour un `legacy_*` et sans version figee ; validation et essai a blanc viendront en P4 / P5.
* Ecriture : `append_lock` sur `state.json` (verrou inter-postes), temporaire + `os.replace`, YAML d'abord puis `state.json` ;
  `history.jsonl` ecrit apres le verrou (`append_jsonl` prend le meme verrou de process, non reentrant).

## Droits (01 §7) : garde-fou, PAS une securite

`flows_td`, `flows_team_td` a la racine de `USER/<NOM>/UserSettings/User.json` (pas dans `work_profile`), cochees dans
Parametres > User > Flows. Team TD implique TD. Utilisateur = celui de la config locale. N'importe qui peut cocher les cases ;
la seule vraie barriere sont les droits NTFS de `CONFIG/extensions/` sur le partage.

| Action (`rights.py`) | perso | team | project | shipped |
|---|---|---|---|---|
| `READ` (lire, lister, lancer un flow actif) | tous | tous | tous | tous |
| `WRITE` (enregistrer, incrementer, revenir, supprimer, activer) | td | team_td | team_td | team_td (via la copie) |
| `DRAFT` (essai a blanc, run brouillon, annuler) | td | td | td | td |
| `ADMIN` (nodes Python, pages, bridges, unlock, migrate) | team_td | team_td | team_td | team_td |

Le store ne verifie aucun droit : le router appelle `rights.check` avant chaque mutation (`FlowRightsError`, 403
"Case TD requise" / "Case Team TD requise", `detail.required`).

## Migration v1 (01 §15)

* `python -m flux_flows.migrate_v1 --shipped [--check]` (depuis `backend/`) regenere `shipped/legacy_*.flow.yml` depuis
  `flux_actions/config/*.yml`. A relancer si une action v1 change (le test `test_shipped_files_are_up_to_date` le rappelle), relire le diff.
* `POST /flows/migrate {dry_run}` (Team TD) : `CONFIG/actions/*.yml` -> flows d'equipe (copie d'une action livree = `legacy_<nom>`,
  action creee par l'equipe = meme nom), sauvegarde + v001 inactive + ligne `migrate`. Jamais d'ecrasement (`unchanged` / `exists`).
  Copie `CONFIG/nodes/*.py` vers `CONFIG/extensions/nodes/` (inertes pour v2). `_backup/` et `history.jsonl` v1 ne sont pas convertis.
  Jamais au demarrage ; originaux intacts.
* Conversion : `event.manual`, puis un node par commande (etapes par `(index, nom)`, commandes dans l'ordre du fichier), chaine exec.
  `call_function` -> `flux.call_function` (`{function, args?}`), autre -> `flux.legacy_command` (`{command, params?}`).
  Ports dynamiques (proposition) : entrees = parametres v1, sorties = cles de sortie v1, types dans `params.ports {inputs, outputs}`
  (une sortie prend le type de l'entree qui la lit). Litteraux gardes s'ils different du defaut de la commande. `ask_user` ->
  entree d'interface `<cmd>_<param>` + `data.flow_input` `inN`. Commentaires du fichier -> note `k1`, bloc `FR:` -> `description`.
  Disposition : une colonne par etape (320 px), commande puis ses entrees empilees avec la hauteur des nodes de l'editeur.

## API (`backend/routers/flows.py`, prefixe `/flows`)

Statiques d'abord : `GET /catalog`, `GET /rights`, `POST /migrate`. Puis `GET ""` (liste, `category` pipe / project / perso),
`GET /{name}` (`scope?`, `project?`, `version?` ; sans portee = celle qui gagne), `GET /{name}/versions`, `PUT /{name}` (Enregistrer),
`POST /{name}/increment`, `/revert`, `/activate`, `/deactivate`, `/copy` (Enregistrer sous ailleurs ; shipped -> team = unlock, Team TD),
`DELETE /{name}`. Erreurs : `{detail: {message, ...}}`. Pas encore de push WS `flow_changed` (P4 / P5).
P2 : `GET /runs`, `GET /runs/{run_id}`, `POST /runs/{run_id}/cancel` (TD ou lanceur), `WS /ws` (statiques, avant `/{name}`),
`POST /{name}/run {scope, project?, event?, values, dry_run, draft?, base_revision?}` : `draft` = document de l'editeur (TD,
aucune version), `dry_run` = fichier enregistre (TD), sinon `active_version` d'un flow actif (409 "flow non actif") ;
409 aussi si `refused` / `skipped` (`detail.issues`).
P3 : `POST /preview {kind: resolve | pattern, text, names?, variables?, path_field?, scope, project?}` -> `{result, error, code?,
suggestion?}` (apercu dans l'editeur, ne lance aucun node) ; `GET /nodes/template` (modele de node d'equipe + dossier cible).

## Moteur et runs (P2, 01 §4 a §6, §10)

* **Exec + data** : un curseur exec suit les liens dont le port cible est `exec` (une sortie exec = un lien). Une entree data
  liee est **tiree** quand son node s'execute : source pure (aucun lien exec entrant) = evaluee a la demande et memoisee ;
  source deja executee = ses dernieres sorties ; source de la chaine pas encore executee = erreur "donnee lue avant d'etre
  produite" ; node du corps d'une boucle lu apres son End = refuse ("utilise results de End"). Entree non liee = litteral de
  `params`, sinon defaut du port ; entree obligatoire vide = erreur du node.
* **Memo** : par node, valide tant que les tours de boucle dont la valeur depend sont les memes (et que le compteur
  d'ecritures de variables n'a pas bouge si une variable a ete lue). Rien ne survit au run.
* **Blocs** : ForEach (End apparie par `params.begin`, liste vide = corps saute, `results` = valeurs de `collect`) ; If et tout
  node qui branche rendent `_exec` (`then` par defaut). Boucle exec hors bloc = arret en erreur. Subnet : pas encore execute (P3).
* **Erreurs** : exception ou `NodeError` = node `error` (message + valeurs recues dans le record) ; `on_error` relie =
  `error_handled`, sortie `error`, le flux suit ce lien ; sinon le run s'arrete en `error`. Erreur d'un node pur = attribuee
  a lui et fait echouer le lecteur. `bypass` = node `skipped`, suite par `then`.
* **Timeout** `params.timeout_s` (120 s, 600 s pour `session` / `dcc`) ; un thread depasse est abandonne (dit dans le log).
  **Annulation** : drapeau `cancelled` lu entre deux nodes + `CancelledError` sur l'attente en cours.
* **Threads** : corps `async def` sur la boucle (courts), corps synchrones dans le pool `FLOWS` (8 threads,
  `core/executors.py`), jamais sur la boucle. `flux.legacy_command` lance la commande v1 dans son propre `asyncio.run`
  dans ce pool (les commandes v1 bloquent dans leur `run`), avec un objet `.buffer.context` ; `flux_core` n'est pas modifie.
* **Admission** (`RunManager.submit`) : precheck minimal (node inconnu, evenement absent, limites V1 ; validation complete en
  P4) -> `refused` ; `run_policy` `skip_if_running` -> `skipped`, `queue` -> FIFO (20 max par flow) ; 4 runs a la fois.
  Statuts et etats : ceux de 01 §4.
* **Essai a blanc** (`mode: dry`) : un node a effet appelle `simulate` (lignes du rapport + sorties simulees), les autres
  tournent pour de vrai ; seul l'enregistrement du run est ecrit. Premiere ligne du rapport = limites de l'essai.
* **Runs** : `runs/<flow>/<run_id>.json` (team et shipped : `CONFIG/extensions/runs/`, projet : `_flux_setup/flows/_runs/`,
  perso : `USER/<NOM>/flows/_runs/`), reecrit 1 fois par seconde au plus, purge a la cloture (200 runs, 20 essais par flow,
  200 logs par node, 1 Ko par valeur de lien). Un run `running` d'un backend precedent du meme poste se lit `interrupted`.
* **Push** (`events.py` -> WS `/flows/ws`) : `run_started`, `node_state` et `link_value` regroupes (dernier etat par node /
  lien toutes les 100 ms), `log`, `notify` (toast de `flux.notify`, proposition : absent de la table 01 §10), `run_finished`.

## Validation (P4, 01 §8)

* **Types** : la sortie `any` est propagee quand c'est possible (GetVariable / SetVariable = type de la variable, FlowInput =
  type de l'interface, Value = param `type`, ForEach `item` = element de la liste, End `results`, Null, Select, List*).
  Une sortie encore `any` n'est pas controlee (proposition : pas de faux positif ; 01 §3 refusait `any -> T`).
* **Exec** (reseau du haut seulement, le subnet n'est pas execute) : dominance sur le graph exec + arete implicite Begin -> End
  (liste vide = corps saute) pour E_DATA_BEFORE_PRODUCED ; End.collect et la condition du While lisent leur corps ; corps de bloc
  = ce que `loop` atteint avant le End (blocs imbriques compris), chaine qui rejoint l'apres-End = E_BLOCK_UNBALANCED ;
  un cul-de-sac dans le corps est permis.
* **Variables** : E_VAR_NEVER_SET si la variable n'a pas de defaut et qu'aucun SetVariable ne l'ecrit dans le flow (proposition).
* **DCC** (nodes en P6) : `@flow_node(session="houdini", live_only=True, licence=...)` ; E_NO_SESSION = entree `session`
  non reliee ; E_LIVE_ONLY = session venant d'un `session.*_instance` en `mode: headless` ; W_LICENCE = drapeau `licence` vrai.
* **Destructif** : `!` = drapeau `destructive` vrai pour les params (`registry.flag_on`), bypass exclu. W_DESTRUCTIVE_UNTESTED
  lit `state.json.dry_run_ok {version, nodes_simulated}` (ecrit en P5) : d'ici la, chaque `!` l'affiche. Enregistrer sous / nouveau
  fichier : tous les `!` sont "ajoutes".
* W_SHIPPED_CHANGED : l'unlock garde `shipped_hash` dans `state.json`, compare au flow livre courant.

## Tests

`backend/tests/test_flux_flows/` (model, types, store, rights, migrate_v1, flows_router ; P2 : engine, dry_run, runs, events_bus,
flows_ws, legacy_command ; P3 : patterns, resolver, nodes_data / logic / operator / action / flux, engine_control, team_nodes ; P4 : validate (un test par code), validate_router ; nodes de test dans `_flow_helpers.py`, registre restaure apres chaque module ; `run_flow(checked=False)` contourne la validation pour tester les gardes du moteur), dossiers temporaires, jamais le vrai FLUX_ROOT ;
`tests/system/test_frozen_bundle.py` verifie que chaque `shipped/*.flow.yml` est embarque.
