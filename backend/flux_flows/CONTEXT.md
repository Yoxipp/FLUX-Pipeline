# backend/flux_flows - Flows v2 (format, stockage, droits, migration)

Chantier Flows (ADR 0057, 0058 ; specs `docs/yaml_update_refonte/`). Package neuf : `flux_core` et `flux_actions`
ne sont pas modifies ; depuis P8 le publish passe par les flows quand le projet est en v2 (`switch.py`), sinon v1. Etat au 2026-10-22 : P1 fait
(prompt P1, retire au menage 2026-11 : tag `archive/pre-cleanup`). P2 fait (prompt `P2_moteur_runs.md`) :
moteur, runs, essai a blanc, WS, 11 types de node. P4 (backend, 2026-10-23) : validation complete (`validate.py`).
P5 (2026-10-23) : scheduler, verrou entre postes, evenements actifs, activation (voir "Evenements et flows actifs").
P6a (2026-10-23) : socle DCC, Houdini et Maya (voir "DCC (P6a)"). P6b (2026-10-23) : Nuke, Painter, Designer, Marvelous,
ZBrush, Mari (voir "Autres logiciels"). P6c (2026-10-23) : bridges d'extension, un logiciel ajoute sans recompiler (voir
"Bridges d'extension").

## Fichiers

| Fichier | Role |
|---|---|
| `model.py` | Schema v2 strict (pydantic `extra="forbid"`), `parse_flow`, `load_flow_text`, `dump_flow` (emission YAML stable, sert aussi de forme canonique), `to_document`, `v1_limit_issues`. Nom `^[a-z][a-z0-9_]{1,40}$`, noms reserves (routes statiques + `rights`), 1 Mo, 500 nodes. Node `subnet` (ses `nodes` / `links`), flag `bypass`. `origin` d'un flow migre : `kind`, `name`, `shelf`, `thumbnail`, `extends`, `params`. |
| `types.py` | Types de ports, `can_connect` -> ok / implicite / incompatible + raison fr / en (ADR 0058 : un lien incompatible est accepte par le modele, la validation P4 le signale). |
| `nodes/registry.py` | Tout node FLUX ajoute ici doit avoir sa section dans `docs/user/flows/03_INDEX_NODES.md` (bouton (i) de l'editeur, test `test_nodes_doc.py`). `@flow_node` (doc fr / en, exemple par port, shelf, alias, `effect`), 10 familles, chargeur des nodes d'equipe (`CONFIG/extensions/nodes/`, seulement les fichiers qui contiennent `@flow_node`, portee team seulement). P3 : rechargement **par fichier** (mtime + taille ; seul le fichier change est reimporte, un fichier supprime retire ses nodes), builtins charges avant (un fichier d'equipe ne peut pas prendre un type FLUX : erreur du fichier), fichier casse = `node_errors` du catalogue, les autres marchent. Le moteur recharge l'equipe avant de refuser un type inconnu. Modele : `shipped/team_node_template.py` (`GET /flows/nodes/template`). Un node a effet (`effect=True` ou destructif) sans `simulate` est refuse. `ensure_builtin()` importe les modules FLUX (`BUILTIN_MODULES`). |
| `resolver.py` | Resolveur de texte unique (01 §11) : `{token}`, `{date:%Y%m%d}`, `${var}`, `$FLUX` en tete d'un champ path / dir, `{{ }}`. Token inconnu = `E_UNKNOWN_TOKEN` + suggestion Levenshtein <= 2 ; `tokens_in` pour le validateur (P4). Applique par le moteur aux params et litteraux non lies (`spec.raw` les exclut), jamais a une valeur arrivee par un lien. |
| `patterns.py` | Motifs facon Houdini (01 §11) : `*`, `**`, `?`, `[abc]`, `^` / `!`, gauche a droite ; motif vide = ne garde rien. |
| `nodes/common.py` | `as_path`, `in_project`, `check_destructive_target` (erase / overwrite seulement sous FLUX_ROOT, jamais une racine ni un dossier projet), archive projet partagee (`archive_preview`, `archive_into_project`, via `archive_folder`). |
| `nodes/contract.py` | Contrat d'un corps de node : `body(ctx, inputs, params) -> {port: valeur}`, `simulate(...) -> {lines, outputs}`, `NodeError` (message affiche sur le node), `NodeContext` (`context`, `interface`, `cancelled`, `log`, `notify`, variables), `EXEC_KEY` (`_exec`) pour choisir la sortie exec. |
| `nodes/event.py`, `data.py`, `logic.py`, `operator.py`, `action.py`, `flux.py`, `subflow.py` | Nodes P2 + P3 (02 §11, liste exacte). P3 : data (path, python_value lu par AST sans executer, json_value, template, context), logic (8), operator (26, dont sequence, for, while au plafond 1000, break_loop), action (12, logique partagee avec les commandes v1 de `flux_actions/commands/utility.py` ; `delete` archive par defaut, `erase` destructif), flux (19 : `find_publishes` deduit soft / type / version du nom et de l'extension, une capture sans soft connu passe le filtre soft ; `publish_file` appelle `run_publish_action`, `publish_core` non modifie ; `call_function` v2 reutilise la garde v1 `features`, `core`, `dcc` ; `ping` = message de chat), subflow (`flow_call` profondeur 8 + cycle, `flow_output`). Chaque node a effet a un `simulate` qui n'ecrit rien. |
| `validate.py` | P4 : validation (01 §8), fait foi a l'enregistrement, au lancement, a l'activation et pour `POST /flows/validate`. `validate(flow, Env)` -> `Issue {level, code, node, port, message_fr/en, why_fr/en, fix {kind, args}, link}` ; tous les codes de 01 §8 ; `unconfirmed_destructive` (E_DESTRUCTIVE_UNCONFIRMED, compare au fichier de travail) ; `errors(issues, dry_run)` (un E_TYPE_MISMATCH ne bloque pas l'essai a blanc, ADR 0058). Voir "Validation" ci-dessous. |
| `engine.py` | Moteur exec + data (01 §4), `Run` (un run) et `RunManager` (admission, un par boucle asyncio : `engine.manager()`). |
| `runs.py` | Enregistrements de run (01 §6) : id, ecriture atomique, liste, retention, `interrupted`. |
| `events.py` | Bus interne thread-safe, feuille stdlib (01 §1) : `subscribe` / `emit`, file bornee par abonne. P5 : ecouteurs locaux `listen` / `signal` (jamais vers le WS) et `publish_done` (appele par `log_publish`, switch `FLUX_FLOWS_HOOKS`, ne leve jamais). |
| `scheduler.py` | P5 : tache de fond (lifespan), election, relecture des flows actifs, surveillants `schedule` / `new_file` / `when` / `scene_opened`, ecoute de `publish_done`. Voir plus bas. |
| `team_commands.py` | ADR 0081 : commandes du chat Team. `parse` (`/nom args`, `"..."` garde les antislashs, slash final retire), `commands` (TeamCommand des flows actifs perso / equipe / projet, filtre `channels`), `listeners`. Node `event.team_command` (`nodes/event.py`, dans `START_EVENTS`) et `flux.team_reply` (`nodes/flux.py`, message `FLUX` dans le fil, `via`). Routes `GET /flows/team-commands`, `POST /flows/team-commands/run` : poste le message de l'artiste (`chat_manager.post_message`), lance les runs sur ce backend, repond seul dans le fil si un run ne finit pas `ok`. Exemple `shipped/example_team_zip.flow.yml`. |
| `hosts.py` | P5 : verrou `CONFIG/extensions/runs/host.lock` entre postes (`HostLock.tick` toutes les 20 s). |
| `hooks.py` | P5 : `event.on_publish` : publish -> enregistrement `publish` (soft / type deduits) + `infos` (R1 : `flux.publish_infos`, tokens du nom FLUX), filtres (soft, type, name ; R1 : mode, task, class, asset, seq, shot, project) evalues avant tout run, flows qui le veulent. |
| `bridges/` | P6a : `softs.py` (registre des logiciels), `primitives.py` (transports qui enveloppent les clients `dcc/`), `session.py` (valeur `session[<soft>]`, `connect_live`), `headless.py` (worker `hython` / `mayapy`). |
| `dcc_nodes.py` | P6a : nodes DCC livres en sous-flows verrouilles (`shipped/dcc/<soft>/*.flow.yml`, `node_type`) et leurs copies d'equipe. |
| `locations.py` | Dossier de chaque portee ; `roots_for(user, project)` construit le dict `{portee: dossier ou None}` du store (nom de projet = un nom de dossier, jamais un chemin). |
| `store.py` | Portees, fichier de travail, versions figees, `state.json`, `history.jsonl`, `_trash/`, verrou, ecriture atomique, conflit 409. P4 : `read_history` (lignes du flow, recentes d'abord) et `list_versions` rend `user` par version + `history` (dialogue Versions). ADR 0069 : `EXAMPLE_PREFIX` (`example_*` livres = categorie Exemples), `copy_flow` d'un exemple retire "Exemple :" du libelle, `relocate_flow` (Renommer / Changer de portee : versions renommees, `state.json` et fichiers du dossier suivent, arrive desactive, l'ancien a `_trash/`, historique des deux cotes ; route `POST /flows/{name}/relocate`). La copie d'un exemple cree ses pages TOOL manquantes depuis `shipped/pages/` (`routers/flows._example_pages`). |
| `pages.py` | P7 (ADR 0066) : format strict des pages TOOL (`page: 1`, `layout` folder > row > widget, `data:` collections), props par kind (formulaire `button float int text path dir toggle select list`, decor `separator label`, donnees `feed table cards calendar members board`), `dump_page` stable, `suggest_id`, `validate_page(page, PageEnv)` -> `PageIssue` (codes `P_*` de 04 §8 + donnees : `P_SOURCE_*`, `P_FIELD_*`, `P_BOARD_ROW`, `P_OUTPUT_NOT_FOUND`, `P_FIELDS_EMPTY`, `P_DATA_UNUSED`). Ids reserves : `validate links templates data media`. ADR 0078 : `access` optionnel (`Access`, `page_for`), `GET /flows/pages` ajoute `access` / `for_me`. |
| `page_store.py` | P7 : pages par portee (`locations.page_roots` : `shipped/pages/` modeles, `CONFIG/extensions/pages/`, `<projet>/_flux_setup/pages/`), un fichier par page, `rev` (hash du texte) et 409 "page modifiee par X", copie dans `_history/` (20), `_trash/` (2026-10-30 : la suppression deplace aussi `pages_data/<id>/` de chaque base utilisee, team et projet ouvert, dans `<pages>/_trash/<id>_<stamp>_data/` ; dossier projet partage avec une page team du meme id : seules les collections que l'autre page ne declare pas partent ; fichier occupe = 409 et rien ne bouge). `list_trash` / `restore_page` (routes `GET /flows/pages/trash`, `POST /flows/pages/trash/{file}/restore`, UI Nouvelle page > Corbeille > Restaurer) remettent la page ET ses donnees ensemble ; refus 409 si une page du meme id existe ou si une de ses collections a de nouveau des donnees (rien n'est ecrase ni fusionne), ligne `page_save` / `page_delete` dans le `history.jsonl` des flows de la portee ; `flow_lookup` (version active si le flow est actif) pour la validation. |
| `page_links.py` | Seul lien page -> flow restant (ADR 0068) : widget de donnees `source: {flow, output}`. `page_links(page)`, index inverse (`GET /flows/pages/links`), `broken_by` (`W_PAGE_LINK_BROKEN` de `validate.py` quand la sortie disparait, via `Env.page_links`). |
| `page_inputs.py` | ADR 0068 : node `event.page_inputs` (InputsPageReader), le flow choisit sa page. `ports_of(page)` (une sortie exec par bouton, une sortie typee par champ, `params.ports` comme FlowCall), `defaults_of`, `load_page` (project > team, modele livre en dernier), `node_outputs` (valeurs du clic ou defauts de la page), `broken_links`, `listeners` (flows actifs perso / equipe / projet dont la version active relie ce bouton), `uses` (fichiers de travail, pour l'editeur de page). Le moteur demarre sur le node (`START_EVENTS`), choisit la sortie du bouton (`EXEC_KEY`) et donne les defauts de la page si le run part d'ailleurs ; `validate.py` : `E_PAGE_NOT_FOUND`, `W_PAGE_LINK_BROKEN`, lecture permise depuis un autre depart. Le format de page n'a plus `on_click` / `bind` (`pages._strip_flow_links` les retire des anciens fichiers). |
| `page_data.py` | P7 (ADR 0066 n°3, 4) : collections partagees des pages, **un journal par auteur** `<base>/pages_data/<page>/<collection>/<AUTEUR>.jsonl` (`<base>` = `_flux_setup/` du projet, ou `CONFIG/extensions/` si `per: team`), operations `put` (fusion par champ, la derniere gagne) / `del`, ordre `(at, user, seq)` (horloge de chaque poste), auteur = nom du fichier, ligne coupee ignoree, `etag` (tailles + dates : `unchanged` sans rien lire), champs types contre la collection (board : champs fixes), images **copiees** par le backend dans `media/<hash>.<ext>` (ADR 0005), lues par une route d'affichage. P3 board (ADR 0071) : schema v2 a champs plats (`BOARD_FIELDS`, `BOARD_CHOICES`, `schema: 2` a la lecture), `put` avec `restore: true` (undo d'une suppression), compaction par l'auteur de son propre journal au-dela de `COMPACT_BYTES` (`compact_ops` garde `at` / `seq`, fusion identique). Lot B (ADR 0074) : schema v3 (`frame ink flux`, `points` verifies par regex, `stroke_width`, `highlight`, `ref` = `asset:<classe>/<nom>` / `shot:<seq>/<shot>` / `publish:...:<tache>`). |
| (schema v5) | ADR 0083 : `page_data.py` / `pages.py` : `text_locked` (verrou du texte ; `locked` = deplacement, `text_locked` absent suit `locked` pour les anciens boards), types `shotboard` (grille lue en direct dans Production par le front) et `shot` (case : `target` = shotboard, `ref` = `shot:<seq>/<shot>`, `frame_at` / `frame_at2` entre 0 et 1, `text`). |
| `board_mentions.py` | P3 lot C (ADR 0075) : `@nom` dans un NOUVEAU commentaire de board -> `features.notify.hooks.on_mentions` (memes regles que le chat : vrais artistes, alias, jamais soi) ; appele par `POST /flows/pages/{id}/data/{collection}` pour une collection board. Schema v4 : `comment reaction timer`, `target emoji ends_at seconds`. |
| `board_templates.py` | P3 lot B (ADR 0074) : modeles de board livres `shipped/boards/*.yml` (moodboard, retro, storyboard, planning, shotboard ; objets a cles locales, `text_en`), valides par `check_fields`, servis par `GET /flows/board_templates`. ADR 0083 : aucun verrou par defaut ; un YAML peut poser `locked` / `text_locked`, gardes a l'insertion. |
| `nodes/page_nodes.py` | P7 (ADR 0066 n°6) : `event.page_data` (un enregistrement ajoute / modifie dans une collection de page, tous postes confondus), `flux.page_data_read`, `flux.page_data_write` (journal de l'utilisateur du run, `simulate` n'ecrit rien). Surveillant dans `scheduler.py` (evenement global, poste titulaire du verrou) : relecture quand l'etag bouge, premiere lecture = base (`seen_<node>.json`), un run par enregistrement, **l'un apres l'autre** (sinon `skip_if_running` perdrait un message), 20 par lecture ; un flow d'equipe sur une collection `per: project` surveille chaque projet (`page_data_folders`). `page_data.locate` sert aussi au router. |
| `shipped/pages/` | P7 : modeles de pages (menu "Depart" de Nouvelle page) : `daily_render` (champ dossier + bouton, flow `example_daily_render`), `board` (board facon Miro), exemples T1. Plus de modele `team` ni de flows `team_message_notify` / `team_reminders` : le chat d'equipe est la page integree `/team` (ADR 0080). |
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
409 aussi si `refused` / `skipped` (`detail.issues`). `button` (T1) : le run joue un clic sur ce bouton d'un
InputsPageReader du flow, avec `values` comme valeurs des champs (400 si aucun node n'a ce bouton) ; sans lui, un flow de
page part par son premier bouton avec les defauts de la page. L'editeur l'envoie depuis `PageRunDialog` (Run / Essai : bouton + valeurs) et le dialogue Activer (bouton, defauts).
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
* **Params du catalogue** (2026-10-23) : `port(..., choices=(..), wirable=True, tokens=None)`, serialises
  `"choices": [..] | null`, `"wirable": bool`, `"tokens": "CLASS" | null` (section de tokens du projet proposee en menu par
  l'editeur). Un lien vers un param `wirable=False` (constante, ex. `data.path.value`) = E_LINK_INVALID ; une valeur saisie
  hors de `choices` (texte non templatise, comparaison exacte) = E_PARAM_INVALID (remplace le controle propre a Value.type).
* **Dispatcher (ADR 0067)** : famille `dispatcher` (`nodes/dispatcher.py` : Submit, JobStatus, WaitJob, CancelJob,
  RenderShot) sur `features/dispatcher` ; ForEach `mode: dispatch` : `ctx.dispatch_batch()` (engine `_dispatch`) recoit les
  taches des Submit du corps, ForEachEnd envoie un job (`job_id`). Mode `farm` des Instance supprime.
* **R1 (2026-10-24)** : `port(..., labels={valeur: (fr, en)}, reserved=(..), when={param: (valeurs,)})`, serialises
  `"choice_labels"`, `"reserved"`, `"when": {"param", "in"}`. `labels` = texte du menu (la valeur stockee ne change pas) ;
  `reserved` = option visible mais desactivee (valeur saisie = E_PARAM_INVALID) ; `when` = port montre seulement pour ces
  valeurs du param (`registry.port_visible`), un lien vers un port masque = W_PORT_HIDDEN (rien n'est supprime). Un port
  `exec` sans doc recoit celle de `registry.EXEC_DOCS`. Un node DCC (sous-flow) herite doc / labels / reserved du param de
  meme nom de son core. Tout port FLUX doit avoir `doc_fr` et `doc_en` (`test_nodes_doc.PortsDoc`) : c'est le tooltip.
  Un param promu (relie) arrive dans `inputs`, pas dans `params` : les nodes recents lisent `{**params, **inputs}`
  (`action._values`). `data.token_path` reproduit la resolution de dossier de `resolve_publish_path` sans toucher
  publish_core (layout plat : `level: last` = fichier `<base>_LAST.<ext>`, pas de dossier LAST).

## Evenements et flows actifs (P5, 01 §9)

* **Scheduler** (`scheduler.start()` dans le `lifespan`, `stop()` apres le `yield`, `FLUX_FLOWS_SCHEDULER=0` = rien) : un
  battement toutes les 20 s ; inactif sans utilisateur ou sans FLUX_ROOT (reteste a chaque battement). Flows actifs relus
  toutes les 60 s et a chaque (de)activation (`request_refresh`) : team, chaque `DOSSIER_PROJETS/*/_flux_setup/flows`,
  perso de l'utilisateur local ; chacun tourne sa `active_version`. Un run d'evenement est un `engine.Run` normal
  (`payload` lu par le node evenement via `ctx.payload`, garde en apercu dans `trigger.payload` du record).
* **Verrou** (`hosts.py`) : `{host, user, pid, nonce, expires, beat}`. Mon nonce : renouveler + relire. Libre (absent, vide,
  illisible, `expires: 0` apres un arret propre) ou perime (`expires < now` ET `beat` inchange depuis 60 s de MON horloge
  monotone) : ecrire, attendre 1 a 3 s, relire, confirmer 2 s plus tard. 2 lectures ratees de suite = perdu. Perte :
  surveillants globaux desarmes, leurs runs `interrupted` (`Run.interrupt`). `GET /flows/host`, WS `host`.
* **Classes** : globaux (schedule, new_file, when) armes chez le detenteur pour team / project, toujours pour perso ;
  locaux (on_publish, scene_opened) sur chaque poste. Plafond 50 surveillants (`over_cap` dans `/flows/host`).
* **schedule** : toutes les 15 s, dernier creneau echu ; note dans `state.json.last_schedule[<node>] {slot, ran_at}` sous le
  verrou du flow AVANT le run (deja note = pas de tir, deux postes = un tir). Creneau en retard de plus de 2 min = rattrapage
  (`missed: true`, une fois) ou `skip` (note sans tirer). L'activation note le dernier creneau echu.
* **new_file** : dossier et reglages evalues comme des entrees pures (`Run.evaluate_inputs`, Run sonde `checked=False`),
  scan `os.scandir` dans `HEAVY`, 1er scan = base (`runs/<flow>/seen_<node>.json`, cle dossier + motif + recursif) ;
  fichier nouveau tire quand sa taille est stable sur 2 scans (`wait_stable`) ; un run par fichier.
* **when** : `condition` evaluee toutes les `every_s` ; tir sur faux -> vrai ; 1re valeur = base ; erreur = notee, pas de tir.
* **scene_opened** : un scruteur par logiciel (`scan_instances` + `core/dcc_context.instance_context`), periode = le plus
  petit `every_s` (min 2 s) ; 1re scrutation = base ; scene changee ou nouvelle instance avec scene = tir. `session` =
  `{soft, port, pid}` jusqu'a P6. `POST /flows/events/scene_opened` pour un script du logiciel.
* **on_publish** : `log_publish` -> `events.publish_done` -> `Scheduler._on_publish` -> `hooks.matching` (filtres soft, type,
  name ; un flow projet n'entend que son projet).
* **Activation** (`routers/flows.py`, `_gate`) : version `current` sans erreur, avertissements acquittes (`state.json.acked
  {version, items}`), essai a blanc reussi sur `current` (`dry_run_ok {version, run_id, nodes_simulated}`, ecrit a la fin d'un
  `POST /run {dry_run, version}` `ok`, ou d'un essai du fichier de travail identique a `current`). W_DESTRUCTIVE_UNTESTED lit
  `nodes_simulated`. Validation : `every_s` min 2 s pour `scene_opened` (pas d'avertissement reseau), `days` / `time` /
  `missed` de Schedule (E_PARAM_INVALID).

## DCC (P6a, 01 §12, 02 §8 / §9, 03 §8)

* **Session** (`bridges/session.py`) : contrat `run(code, timeout) -> {ok, result | error}` + `close()` (seul un worker est
  ferme ; FLUX ne ferme jamais un logiciel Live). `HoudiniLiveSession` (HoudiniClient du port), `MayaLiveSession` (commandPort :
  le code tourne dans un espace avec `cmds`, aller en base64 sur une ligne, retour par un fichier JSON), `TcpJsonSession`
  (`{"cmd": "run"}`, P6b), `headless.WorkerSession`. `find_instance` (pick `active` = `resolve_port`, `scene` par
  `core/dcc_context.instance_context`, `pid`), `connect_live` (sans instance : `live_connect_only` echoue,
  `live_connect_or_open` lance puis `wait_ready` sur toute la plage).
* **Worker headless** (`bridges/headless.py`) : script stdlib `WORKER_SOURCE` ecrit dans le temp (rien a ajouter au bundle),
  lance par `hython` (`_find_hython`) ou `mayapy` (a cote de `maya.exe`), env nettoye (`launcher_core._child_env` : pas de
  `PYTHONPATH`, le `usd-core` de FLUX n'atteint pas Houdini). Une ligne JSON par requete, prints vers un journal, timeout =
  worker tue (session morte). Ferme par `Run.add_cleanup` a la fin du run (partage avec les sous-flows).
* **Nodes** : `bridge.*` (9, `nodes/bridge.py`), `dcc_common.py` (Instance, helpers : `need_session`, `skip_read`, `sim`),
  `dcc_houdini.py` (13 + coeur Instance), `dcc_maya.py` (11 + coeur), `dcc_publish.py` (coeurs des publishs),
  `headless.py` (`action.run_headless`, `action.batch`), `event.publish_request`. Les nodes reutilisent `houdini_export` /
  `houdini_import` (`client=session`), `maya_export_client._build_command` + enveloppe, `dcc/maya/maya_hub.py`,
  `dcc/maya/maya_playblast.py` (nouveau, Live). Les noms de nodes Houdini / Maya sont compares sensibles a la casse.
* **Essai a blanc** : aucun logiciel ni worker lance. Une Instance sans instance ouverte rend une session nulle (le moteur
  laisse passer une entree `session[...]` vide en essai) ; les nodes a effet ecrivent "saute", les lecteurs rendent du vide.
  Une instance deja ouverte sert aux lectures (`se connecterait a ...`), jamais aux effets.
* **Publish boite noire** : `dcc.may_publish_core` / `dcc.hou_publish_core` appellent `run_maya_publish_action` /
  `run_houdini_publish_action` dans le pool (asyncio.run dedans), Live seulement ; Houdini refuse une session sur une autre
  instance que celle choisie dans FLUX (le runner cuit dans le singleton). Essai : destination (`resolve_publish_path`,
  lecture) + version suivante. Flows livres `publish_maya` / `publish_houdini` (`event.publish_request` -> Instance
  `live_connect_only` -> publish -> `FlowOutput`).
* **Bascule P8 (ADR 0070)** : `switch.py` (`publish_engine` v1 / v2 du `project.json`, lu a chaque publish) ;
  `publish_runner.py` `run_publish(soft, project, values, user)` lance `publish_<soft>` (version active d'une copie, sinon
  son fichier de travail, sinon le livre) et rend un `Outcome` : `ok` (sorties `path`, `version`, `files`, `warnings`),
  `refused` (`flux.refuse_publish`, message tel quel, jamais de repli), `fallback` (echec AVANT le coeur : la route publie
  en v1 + `warning()`), `error` (APRES le coeur : jamais v1). Avant / apres = sonde `dcc_publish.PROBE_KEY` du contexte
  du run, posee par `core_starting()` juste avant la fonction du Publisher. Coeurs : pas de timeout moteur (n°1), logger
  du run (n°3), utilisateur du run sinon FLUX sinon unknown (n°5), version jamais 0 (n°6, `None` = inconnue), sortie
  `warnings` (n°8), `name` Houdini obligatoire (n°11), plage Maya complete pas flottant (n°12), `port` Maya (n°14),
  entree `options: dict` des flows (n°4 ; Painter / Designer / Mari : `extra`). Type d'interface `dict` (aucun widget de
  page). Les routes `/dcc/<soft>/publish` l'appellent (Maya, Houdini, Nuke, Painter, Designer, Mari, Marvelous, ZBrush ;
  `routers/CONTEXT.md`). Sorties ajoutees : `rop_node` (houPublish), `tx` (sp / sd / mariPublish) ; entree `node` de
  `publish_nuke`. Parite v1 / v2 : `tests/test_flux_flows/test_publish_flows.py`. Retour arriere :
  `docs/development/PUBLISH_ROLLBACK.md`.
* **Nodes livres verrouilles** (`dcc_nodes.py`, decisions 18 / 19) : `HoudiniInstance`, `MayaInstance`, `houPublish`,
  `mayPublish` = flows `shipped/dcc/<soft>/*.flow.yml` avec `node_type` ; spec du catalogue tiree de l'interface (entrees
  `select` = reglages a choix, constantes), drapeaux du coeur Python `<type>_core` (`internal`, hors Tab / Shelf). Le moteur
  les execute en ligne comme un FlowCall (fichier de travail, essai a blanc compris, timeout des nodes internes). Une copie
  d'equipe du meme nom (`POST /flows/{name}/unlock`, Team TD) les remplace pour tous ; la supprimer = Revenir au defaut.
  Index relu au plus toutes les 2 s (le dossier d'equipe est sur le partage). L'interface d'un flow accepte `session[<soft>]`,
  `dcc_node`, `publish` (entrees reliees seulement, jamais dans un formulaire de page). Un `FlowOutput` relie rend une
  valeur vide sans erreur.

## Autres logiciels (P6b, 02 §8.3 a §8.8)

| Logiciel | Transport (session) | Nodes (P6b) | Publish boite noire | Reportes ("bridge+", accord du mainteneur + live) | Live |
|---|---|---|---|---|---|
| Nuke (`nk`) | TCP JSON `{"cmd"}`, `run(code)` | Instance, OpenScene, SaveScene, SaveAs, RunScript, Export (Write temporaire), Import (Read), Render (Write existant), FindNodes ; SceneOpened | `publish_from_nuke` | aucun (headless `nuke -t` non offert) | a verifier par le mainteneur |
| Substance Painter (`sp`) | TCP JSON `{"action"}`, `run` protege par le secret du poste | Instance, Export, Info ; bridge+ (2026-10-24) : OpenScene (.spp ou mesh), SaveScene, SaveAs, Import (mesh ou ressource), RunScript | `publish_painter` | aucun (bridge a reinstaller) | bridge+ valide live 2026-10-24 ; export / publish a verifier |
| Substance Designer (`sd`) | TCP JSON `{"action"}`, `run` protege par le secret du poste | Instance, Export, Info, Cook (`sbscooker` cote hub, sans session) ; bridge+ (2026-10-24) : OpenScene (charge un .sbs de plus), SaveScene / SaveAs (package du graphe courant), Import (bitmap, mesh lies), RunScript | `publish_designer` | aucun (bridge a reinstaller) | a verifier par le mainteneur |
| Marvelous (`mvd`) | boite a fichiers (une instance), `run` protege par le secret du poste (lu dans `%APPDATA%`) | Instance, Export, Import, Info ; bridge+ (2026-10-24) : OpenScene (.zprj avec discard_changes), SaveScene, SaveAs (.zprj), RunScript | `publish_marvelous` | aucun (script a reinstaller et relancer dans Marvelous) | a verifier par le mainteneur |
| ZBrush (`zb`) | TCP `{"action"}`, `run` protege par le secret du poste (lu dans `%APPDATA%`) | Instance, Export (ztl, obj, fbx), MeshInfo ; bridge+ (2026-10-24) : OpenScene (.zpr avec discard_changes, ou .ztl), SaveScene, SaveAs (.zpr ou .ztl), Import (mesh, tool), RunScript. Tout ne marche que pendant Export FLUX (gel) ; relache a la fin du run et sur erreur | `publish_zbrush` | aucun (bridge a reinstaller) | a verifier par le mainteneur |
| Mari (`mari`) | TCP JSON `{"action"}`, `run` protege par le secret du poste | Instance, Export (un a la fois), Info ; bridge+ (2026-10-24) : OpenScene (nom de projet, .mra ou mesh), SaveScene, SaveAs (archive .mra), Import (image, object, version), RunScript | `publish_mari` | aucun (bridge a reinstaller) | a verifier par le mainteneur |

* `nodes/dcc_softs.py` : Instances (`dc.instance_node(..., headless=False)`), nodes ci-dessus, `client_for(session, soft)`
  (client existant sur le port de la session, refactor `port=` de Nuke, Painter, Designer, Mari ; ZBrush prenait deja `port`).
  `session.ClientSession` = bridge sans execution de code (`run` refuse, jamais simule). Nuke execute le code avec
  `exec(code, {"nuke"}, locals)` : pas de comprehension sur un nom local dans le code envoye.
* Publish (`nodes/dcc_publish.py`, coeurs `dcc.<p>_publish_core`) : la fonction de publish du Publisher dans un thread ;
  elles parlent au client singleton sur le port de BASE : une session sur un autre port est refusee. Flows livres
  `shipped/dcc/<dossier>/{<p>_instance,<p>_publish}.flow.yml` (generes depuis les specs des coeurs : entrees reliees par
  `data.flow_input` ; `dict` hors interface) et `shipped/publish_<soft>.flow.yml`.
* ZBrush : `release` apres chaque export (finally) ET en fin de run (`ctx.add_cleanup`), meme en erreur ou annulation.

## Bridges d'extension (P6c, 01 §12, 00_LOGIQUE n°18)

Un logiciel que FLUX ne livre pas : `CONFIG/extensions/bridges/<soft>/` = `bridge.yml` + `dcc_side/` (+ `flows/` optionnel).
Exemple documente, NON TESTE : `docs/development/FLOWS_BRIDGE_3DSMAX.md`.

* `bridges/extension.py` : manifeste strict (pydantic `extra=forbid` : soft, label, icon, prefix `^[a-z]{2,4}$`, exe_hints,
  port_range [base, nombre <= 16], transport `tcp_json` | `file_mailbox` | `http`, mailbox, install {target, files relatifs}),
  `load_all()` (cache 2 s, erreurs isolees par bridge), refus avec la raison : soft livre, nom de dossier different, prefixe
  livre / reserve (ps, ue) / double, ports qui chevauchent `DCC_PORT_RANGES` ou une autre extension. `get(soft)` = valide seulement.
* `softs.get` retombe sur les extensions valides (`Soft.extension`, `dcc_key` `ext:<soft>`) : `scan_ports` pingue chaque port
  de la plage, `launch` passe par `launch_exe` + `exe_hints`, sessions `TcpJsonSession` / `MailboxSession` / `HttpRunSession`,
  `find_instance` prend la premiere instance (pas d'instance "active" choisie dans FLUX).
* `bridges/templates/` : `tcp_json_server.py` et `file_mailbox_server.py` (stdlib, Python 3.7+, 127.0.0.1, `ping` / `run`),
  lus a cote d'eux `<nom du script>.json` (ecrit a l'installation). Embarques par `backend.spec` (`*_server.py`). Le script
  execute le code recu : meme confiance que les nodes Python d'equipe.
* `bridges/installer.py` : copie `install.files` + `<script>.json` dans `install.target` (`~`, `%VAR%`, `$VAR`, `{exe_dir}`),
  recu `.flux_bridge_<soft>.install.json` (sha256). Jamais d'ecrasement silencieux (conflit ; `overwrite` = sauvegarde
  `.flux_backup_<date>` d'abord) ; desinstallation = fichiers de FLUX seulement + restauration des sauvegardes, un fichier
  modifie depuis est garde ; chemins confines. `install_all_entries()` branche les extensions dans "Installer tous les bridges".
* Nodes (`nodes/dcc_extension.py`) : `session.ext_instance_core` (interne, reglage `soft`, Live seulement) et
  `dcc.ext_run_script` (`session[*]`, `args["path"]` = `path` ou fichier temporaire `temp_ext` supprime en fin de run).
  `bridges/flow_templates.py` ecrit `<prefix>_instance` (`session.<prefix>_instance`) et `<prefix>_publish`
  (`dcc.<prefix>_publish` : ExtRunScript enregistre, puis `flux.publish_file`) dans le scope equipe (ou les
  `flows/session.flow.yml` / `publish.flow.yml` du bridge). Noeuds d'equipe sans coeur propre : icone / rang Shelf du coeur
  interne, sinon du dernier node a effet (`dcc_nodes._inner_look`).
* Routes : `GET /flows/bridges`, `POST /flows/bridges/{soft}/install | uninstall` (ce poste, sans droit),
  `POST /flows/bridges/{soft}/flows` (Team TD). Nom de flow `bridges` reserve.
* Tests : bridge_manifest, bridge_templates (modeles sur port libre / boite temporaire), bridge_installer, extension_session
  (faux logiciel = modele TCP dans un thread). Prouvent le protocole et le cote FLUX, pas un vrai logiciel.

## Tests

`backend/tests/test_flux_flows/` (model, types, store, rights, migrate_v1, flows_router ; P2 : engine, dry_run, runs, events_bus,
flows_ws, legacy_command ; P6b : nodes_softs (faux bridges TCP, boite a fichiers temporaire, faux `sbscooker`) ; P6a : bridge_primitives, dcc_session, nodes_houdini, nodes_maya, headless, publish_black_box, dcc_subflows (faux bridges `_fake_bridges.py`, faux `hou` / `maya.cmds` `_fake_dcc.py` : prouvent les appels, jamais le logiciel) ; P5 : host_lock, scheduler, event_schedule, event_new_file, event_when, activation (`_sched_helpers.py`), `tests/publisher/test_publish_hooks.py` ; P3 : patterns, resolver, nodes_data / logic / operator / action / flux, engine_control, team_nodes ; P4 : validate (un test par code), validate_router, catalog_types (miroir `portTypes.ts`), team_node_router ; nodes de test dans `_flow_helpers.py`, registre restaure apres chaque module ; `run_flow(checked=False)` contourne la validation pour tester les gardes du moteur), dossiers temporaires, jamais le vrai FLUX_ROOT ;
`tests/system/test_frozen_bundle.py` verifie que chaque `shipped/*.flow.yml` est embarque.
