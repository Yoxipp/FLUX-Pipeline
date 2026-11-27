# CONTEXT - `scripts/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee de mai 2026 retiree (lisible au tag `archive/pre-cleanup`).

Build et outils : `build.cjs` (entree de `npm run build` : bump de version x.x.xxx + enchainement du build), `flux_version.nsh` (genere), `backend.spec` (PyInstaller), `electron-builder.yml` (NSIS, sortie `INSTALLEURS/`), `installer.nsh`, `icon.ico` / `icon.png` (build + icone runtime), `build_hdas.py` et `rebuild_importer_hda.py` (HDA, doublon connu).


Details : `docs/development/BUILD.md`.

## backend.spec : modeles de bridge (2026-10-23, Flows P6c)

`app_datas` copie `backend/flux_flows/bridges/templates/*_server.py` (lus et copies par l'installeur des bridges d'extension,
jamais importes) ; `test_frozen_bundle.py` les verifie.

## backend.spec : flows livres (2026-10-22)

`app_datas` copie le dossier `backend/flux_flows/shipped` (recursif) vers `flux_flows/shipped` : flows v2 livres (`legacy_*`, puis
`publish_<soft>` en P8). `tests/system/test_frozen_bundle.py` verifie chaque `*.flow.yml`.
