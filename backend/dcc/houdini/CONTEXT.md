# CONTEXT - `backend/dcc/houdini/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/backend__dcc__houdini.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

`flux_houdini_server.py` (HTTP in-app 48884..48891, refuse les navigateurs S2), `client.py`, `houdini_export.py` / `houdini_import.py` / `houdini_usd_light_export.py`, `autostart.py` (package `packages/flux.json` + favoris `jump.pref` `$FLUX/` et `$FLUX/DOSSIER_PROJETS/` ajoutes a l'installation, retires a la desinstallation), `hda/` (HDA importer/exporter/lighting), `startup/`.

Ne jamais ecrire dans `houdini.env` (crash Houdini 22). Ne jamais exposer le `usd-core` pip au Python de Houdini.

Import USD "Ouvrir dans Houdini" (2026-09-17) : toujours par contexte, jamais via l'HDA tokens (`create_usd_context_import`, sonde pxr `features/importer/usd_probe.py`) : `/stage` = Reference LOP (`/assets/<X>` component ou skeleton, `/sets/<X>` assembly), `/obj` ou SOP = `kinefx::usdcharacterimport` (source fichier) si skeleton, sinon `usdimport`. Export SOP `.usd*` = `usdexport` (plage = un fichier anime), jamais `rop_geometry`.
Launcher : `PYTHONUSERBASE` retire de l'env (sinon Houdini charge le pxr pip du Python Store).
HDA `flux_importer` (2026-09-17) : parm `source_mode` = Publish (tokens) / Bibliotheque USD (`/dcc/houdini/importer/library`, `library_resolve`) / Chemin libre (`probe?file=`). Un USD avec skeleton passe `usd_character` a 1 : sortie 1 = mesh boneCapture (`kinefx::usdcharacterimport`), sorties 2-3 = skeleton repos / anime. Le module Python est servi par le backend (relancer FLUX), le `.hda` (parms, noeuds internes) est rebuild dans `resources/shelves/houdini/` puis recopie par `reconcile_installed_dccs` au demarrage.
