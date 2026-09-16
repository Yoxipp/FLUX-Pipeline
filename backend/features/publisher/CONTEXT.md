# CONTEXT - `backend/features/publisher/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/backend__features__publisher.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

`publish_core.py` (`resolve_publish_path`, briques legacy reutilisees par le moteur), `publish_layout.py` (dossier plat `<base>_LAST` + `<base>_vNNN`), `version_resolver.py`, `modif_log.py`, `texture_conform.py` (.tx OpenImageIO), `usd_proxy.py` (purpose=proxy). Orchestration : `flux_actions/config/publish*.yml`.

Zone a risque (tous les DCC + projets existants). Le layout par sous-dossier de format decrit dans l'ancienne fiche est OBSOLETE.
