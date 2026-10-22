# backend/flux_flows - Flows v2 (format, stockage, droits, migration)

Chantier Flows (ADR 0057, 0058 ; specs `docs/yaml_update_refonte/`). Package neuf : `flux_core` et `flux_actions`
ne sont pas modifies, le publish tourne encore sur les actions v1 jusqu'a P8. Etat au 2026-10-22 : P1 fait
(prompt `docs/yaml_update_refonte/prompts/P1_format_v2_stockage.md`). Pas de moteur ni de run (P2).

## Fichiers

| Fichier | Role |
|---|---|
| `model.py` | Schema v2 strict (pydantic `extra="forbid"`), `parse_flow`, `load_flow_text`, `dump_flow` (emission YAML stable, sert aussi de forme canonique), `to_document`, `v1_limit_issues`. Nom `^[a-z][a-z0-9_]{1,40}$`, noms reserves (routes statiques + `rights`), 1 Mo, 500 nodes. Node `subnet` (ses `nodes` / `links`), flag `bypass`. `origin` d'un flow migre : `kind`, `name`, `shelf`, `thumbnail`, `extends`, `params`. |
| `types.py` | Types de ports, `can_connect` -> ok / implicite / incompatible + raison fr / en (ADR 0058 : un lien incompatible est accepte par le modele, la validation P4 le signale). |
| `nodes/registry.py` | `@flow_node` (doc fr / en, exemple par port, shelf, alias), 10 familles, chargeur des nodes d'equipe (`CONFIG/extensions/nodes/`, seulement les fichiers qui contiennent `@flow_node`). Vide en P1 : les nodes arrivent en P2 / P3. |
| `locations.py` | Dossier de chaque portee ; `roots_for(user, project)` construit le dict `{portee: dossier ou None}` du store (nom de projet = un nom de dossier, jamais un chemin). |
| `store.py` | Portees, fichier de travail, versions figees, `state.json`, `history.jsonl`, `_trash/`, verrou, ecriture atomique, conflit 409. |
| `rights.py` | Cases TD / Team TD, table de 01 §7, 403. |
| `migrate_v1.py` | Actions v1 -> flows (script de dev pour `shipped/`, `POST /flows/migrate` pour l'equipe). |
| `shipped/` | Flows livres, lecture seule, dans l'exe (`scripts/backend.spec`, dossier copie recursivement). Aujourd'hui les 5 `legacy_*`. |

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
`DELETE /{name}`. Erreurs : `{detail: {message, ...}}`. Pas encore de push WS `flow_changed` (P2).

## Tests

`backend/tests/test_flux_flows/` (model, types, store, rights, migrate_v1, flows_router), dossiers temporaires, jamais le vrai FLUX_ROOT ;
`tests/system/test_frozen_bundle.py` verifie que chaque `shipped/*.flow.yml` est embarque.
