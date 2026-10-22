# CONTEXT - `scripts/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/scripts.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

Build et outils : `build.cjs` (entree de `npm run build` : bump de version x.x.xxx + enchainement du build), `flux_version.nsh` (genere), `backend.spec` (PyInstaller), `electron-builder.yml` (NSIS, sortie `INSTALLEURS/`), `installer.nsh`, `icon.ico` / `icon.png` (build + icone runtime), `build_hdas.py` et `rebuild_importer_hda.py` (HDA, doublon connu).

Test de charge serveur : `loadtest/` (`flux_loadtest.py` seed / run / cleanup, `flux_instance.py` = un backend isole). Hors build, voir `loadtest/README.md`.

Details : `docs/development/BUILD.md`.

## backend.spec : flows livres (2026-10-22)

`app_datas` copie le dossier `backend/flux_flows/shipped` (recursif) vers `flux_flows/shipped` : flows v2 livres (`legacy_*`, puis
`publish_<soft>` en P8). `tests/system/test_frozen_bundle.py` verifie chaque `*.flow.yml`.
