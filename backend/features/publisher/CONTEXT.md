# CONTEXT - `backend/features/publisher/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/backend__features__publisher.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

`publish_core.py` (`resolve_publish_path`, briques legacy reutilisees par le moteur), `publish_layout.py` (dossier plat `<base>_LAST` + `<base>_vNNN`), `last_pointer.py` (ADR 0017 : `vNNN` immuable ecrit d'abord, LAST derive en layer USD / copie + `.flux.json` / `.link`), `version_resolver.py`, `modif_log.py`, `texture_conform.py` (.tx OpenImageIO), `usd_proxy.py` (purpose=proxy). Orchestration : `flux_actions/config/publish*.yml`.

Zone a risque (tous les DCC + projets existants). Le layout par sous-dossier de format decrit dans l'ancienne fiche est OBSOLETE.

## LAST (ADR 0017, U3a)

* `publish_into_layout` : archive un ancien LAST sans metadonnee en `vNNN`, ecrit `<base>_vNNN.ext` (temp + rename, jamais d'ecrasement, NNN+1 si la cible existe), puis derive LAST.
* Formes : `.usd`/`.usda` pointeur texte, `.usdc` pointeur crate (pxr, sinon copie), autres = copie + `<base>_LAST.ext.flux.json`, lien = `<base>_LAST.ext.link` (JSON `{target, version, published_at, user[, pattern]}`).
* Classement : taille > `storage.last_link_threshold_gb` (hors USD) -> link ; sequence / `.vdb` -> link ; `storage.last_mode` du `project.json` (`{".abc": "link"}`) ; USD -> layer ; reste -> copie.
* LAST verrouille : 3 essais, puis warning ; le `vNNN` reste valide, la fonction retourne le fichier version.
* Ecrivains ROP (Houdini, Nuke, Photoshop) : encore `archive_flat_last` + ecriture directe dans LAST (U3b). `archive_flat_last` sur un LAST derive retire seulement la metadonnee.
* Lecteurs : `read_last`, `find_last_file` (suit `.link`), `published_files` (cache `.flux.json` et temporaires), `next_publish_version` (preflight), `last_version_label`.
