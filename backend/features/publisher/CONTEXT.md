# CONTEXT - `backend/features/publisher/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/backend__features__publisher.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

`publish_core.py` (`resolve_publish_path`, briques legacy reutilisees par le moteur), `publish_layout.py` (dossier plat `<base>_LAST` + `<base>_vNNN`), `last_pointer.py` (ADR 0017 : `vNNN` immuable ecrit d'abord, LAST derive en layer USD / copie + `.flux.json` / `.link`), `destination_preview.py` (lecture seule : carte Destination du publisher, `GET /publish/destination`), `version_resolver.py`, `modif_log.py`, `texture_conform.py` (.tx OpenImageIO ; option "Export .tx seulement" (`tx_only`, fichier local + Painter / Mari / Designer) : `dcc/texture_publish.convert_to_tx` convertit dans un dossier temp puis publie le .tx a la place de l'image, jamais publier puis supprimer (versions comptees par extension)), `usd_proxy.py` (purpose=proxy : meshes decimes, grooms BasisCurves 1 courbe sur N, ADR 0026). Orchestration : `flux_actions/config/publish*.yml`.

Zone a risque (tous les DCC + projets existants). Le layout par sous-dossier de format decrit dans l'ancienne fiche est OBSOLETE.

## Departements de plan (TYPE_SHOT)

* `resolve_publish_path` d'un plan : token `TYPE_SHOT[<task>]` puis `CLASS[<task>]` (anciens noms CLASS_SEQ_SHOT). `load_tokens` fusionne les defauts de `core/constants.py` dans le `tokens.json` du projet : un departement ajoute aux defauts (ex. RENDER, 2026-10-09, `render/{seq}/{shot}`) marche aussi dans les projets existants, une valeur du projet garde la priorite.
* Echec de resolution : `explain_unresolved_publish` donne la raison lisible (task inconnue...), renvoyee par `POST /publish` dans `message` et affichee dans le toast du Publisher.

## LAST (ADR 0017, U3a)

* `publish_into_layout` : archive un ancien LAST sans metadonnee en `vNNN`, ecrit `<base>_vNNN.ext` (temp + rename, jamais d'ecrasement, NNN+1 si la cible existe), puis derive LAST.
* Formes : `.usd`/`.usda` pointeur texte, `.usdc` pointeur crate (pxr, sinon copie), autres = copie + `<base>_LAST.ext.flux.json`, lien = `<base>_LAST.ext.link` (JSON `{target, version, published_at, user[, pattern]}`).
* Classement : taille > `storage.last_link_threshold_gb` (hors USD) -> link ; sequence / `.vdb` -> link ; `storage.last_mode` du `project.json` (`{".abc": "link"}`) ; USD -> layer ; reste -> copie.
* LAST verrouille : 3 essais, puis warning ; le `vNNN` reste valide, la fonction retourne le fichier version.
* Ecrivains directs (ROP Houdini + scene `.hip`, Nuke Write/script, Photoshop), U3b : `reserve_version` (archive un LAST legacy, premier NNN libre fichier + dossier sequence) -> le DCC ecrit `<base>_vNNN.ext` ou `<base>_vNNN/` -> `finalize_rendered_version` derive LAST (sequence = `.link` avec `pattern`). Echec : `discard_rendered_version`. `archive_flat_last` reste pour compat (plus d'appelant).
* Lecteurs : `read_last`, `find_last_file` (suit `.link`), `published_files` (cache `.flux.json` et temporaires), `next_publish_version` (preflight), `last_version_label`.

## Charge reseau (2026-10-22, `docs/school_opti_prompt/PROMPT.md`)

* `copy_limits.py` : la copie source -> `vNNN` (`write_version`) passe par un plafond de copies simultanees par backend (`FLUX_PUBLISH_MAX_PARALLEL`, defaut 10, les suivantes attendent) et un debit max optionnel par copie (`FLUX_PUBLISH_MAX_MBPS`, 0 = off = `shutil.copy2`). Reglables dans Parametres avances. `GET /publish/queue` = actives / en attente (affiche dans le Publisher).
* `vNNN -> LAST` reste `shutil.copy2` : mesure sur `\\server` (Python 3.14), 200 Mo en 0,2 s, la copie est faite cote serveur (pas d'aller-retour par le PC). Hardlink teste OK mais non retenu (the maintainer : garder la copie).
* Le POST `/publish` tourne dans `core/executors.HEAVY` (pool borne), pas dans l'executor par defaut des feeds.

## Flows apres publish (P5, 2026-10-23)

`publish_core.py` n'est pas modifie. `copy_publish` (et chaque exporteur direct) appelle `log_publish`
(`features/activity/activity_writer.py`), qui emet `flux_flows.events.publish_done` : les flows actifs `OnPublish` du
poste partent apres le publish (en parallele des hooks USD `after_usd_publish`, qui suivent `log_publish`). Sans flow
actif = rien ; `FLUX_FLOWS_HOOKS=0` coupe ; une emission qui leve ne change pas le publish. Pas d'`event.before_publish` :
"avant publish" = nodes avant le node publish d'un flow `publish_<soft>` (P6 / P8). Tests : `tests/publisher/test_publish_hooks.py`.
