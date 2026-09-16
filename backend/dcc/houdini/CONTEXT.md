# CONTEXT - `backend/dcc/houdini/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/backend__dcc__houdini.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

`flux_houdini_server.py` (HTTP in-app 48884..48891, refuse les navigateurs S2), `client.py`, `houdini_export.py` / `houdini_import.py` / `houdini_usd_light_export.py`, `autostart.py` (package `packages/flux.json`), `hda/` (HDA importer/exporter/lighting), `startup/`.

Ne jamais ecrire dans `houdini.env` (crash Houdini 22). Ne jamais exposer le `usd-core` pip au Python de Houdini.
