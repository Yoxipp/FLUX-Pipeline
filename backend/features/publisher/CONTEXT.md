# CONTEXT - `backend/features/publisher/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/backend__features__publisher.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

`publish_core.py` (`resolve_publish_path`, briques legacy reutilisees par le moteur), `publish_layout.py` (dossier plat `<base>_LAST` + `<base>_vNNN`), `last_pointer.py` (ADR 0017 : `vNNN` immuable ecrit d'abord, LAST derive en layer USD / copie + `.flux.json` / `.link`), `version_resolver.py`, `modif_log.py`, `texture_conform.py` (.tx OpenImageIO), `usd_proxy.py` (purpose=proxy : meshes decimes, grooms BasisCurves 1 courbe sur N, ADR 0026). Orchestration : `flux_actions/config/publish*.yml`.

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
