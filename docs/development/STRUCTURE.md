# FLUX Pipeline - Structure du depot

> Reecrit le 2026-09-16 (V7-05). Arborescence + chemins dont depend le build.
> Commandes build : `docs/development/BUILD.md`.
> A mettre a jour quand un dossier de premier niveau ou un chemin de build change.

## Arborescence trackee

```
FLUX_Pipeline/
├── README.md                 point d'entree humain (quoi, lancer, carte du depot, ou lire quoi)
├── CONTRIBUTING.md           regles de contribution
├── LICENSE, NOTICE           MPL-2.0
├── package.py                package Rez de FLUX
├── FLUX_DEV.bat              lancement dev (double-clic)
├── INSTALL_DEV.bat           installation des dependances de dev
├── BUILD_INSTALLER.bat       build installeur NSIS -> INSTALLEURS/
├── PUBLISH_GITHUB_PUBLIC.bat publication du repo public (controles puis push, tools/publish/)
├── .gitattributes            binaires (.hda, .hipnc, images)
│
├── app/
│   ├── electron/             main.ts, preload.ts, python_bridge.ts (process main)
│   └── src/                  React + TS : App.tsx, api/client.ts, components/shared/, hooks/,
│                             lib/ (pollIntervals, *ExportOptions), pages/ (+ Production/, flow_editor/ = editeur de Flows, tool_pages/ = pages TOOL), i18n.tsx
├── public/                   assets statiques Vite (logo)
│
├── backend/
│   ├── main.py               entree FastAPI (17 routers, middleware jeton S1)
│   ├── requirements.txt, .importlinter (contrats d'imports)
│   ├── core/                 config, paths, constants, api_auth, logger, repository json/sqlite/remote,
│   │                         storage local/object, dcc_instances, dcc_context, socket_manager, migration JSON->SQLite
│   ├── features/             activity, calendar, folder_manager, houdini_work (FLUX Work, ADR 0051), importer, launcher, production, publisher,
│   │                         render (job_builder, freeze, team_settings, exit_codes, farm_paths, farm_targets, farm_limits, image_sequence, tractor_bridge, bridge/flux_tractor_bridge.py, blade/flux_freeze_at_start.py ; router routers/render.py, page pages/Render.tsx + onglets pages/render/* (EnvPanel = config farm verrouillee), HDA flux_render_submit_hda.py),
│   │                         review (Keyframe Pro, ADR 0047), settings, shelf_manager, system, usd_assembler, usd_export
│   ├── flux_core/            moteur d'actions (zero dependance FLUX/DCC)
│   ├── flux_flows/           Flows v2 : model, types, store, rights, migrate_v1, engine, runs, events, scheduler, hosts, hooks, dcc_nodes,
│   │                         pages, page_store, page_links, page_data (pages TOOL, P7), shipped/pages/ (modeles de pages), board_templates + shipped/boards/ (modeles de board),
│   │                         bridges/ (softs, primitives, session, headless, extension, installer, flow_templates,
│   │                         templates/*_server.py : script cote logiciel des bridges d'extension, embarque par backend.spec),
│   │                         nodes/ (registry, contract, event, data, logic, operator, flux, bridge, dcc_common, dcc_houdini, dcc_maya,
│   │                         dcc_publish, dcc_softs, dcc_extension, headless, page_nodes),
│   │                         shipped/*.flow.yml (legacy_*, example_*, publish_maya / publish_houdini, team_*) + shipped/dcc/<soft>/ (nodes DCC
│   │                         verrouilles) ; embarque par backend.spec, dossier recursif
│   ├── flux_actions/         commandes + config/*.yml (publish, publish_maya, publish_houdini,
│   │                         conform_texture, generate_proxy) + switch.py (flags env) + graph.py
│   ├── dcc/                  maya, houdini, zbrush, nuke, substance_painter, substance_designer, marvelous, mari, photoshop, unreal
│   ├── routers/              couche HTTP
│   ├── utils/                project_utils, user_utils
│   ├── resources/            bundles dans le sidecar : shelves/ (maya, houdini), scenes/ (template Houdini), rigs/maya/ (Camera Rig, Light Rig),
│   │                         manual/FLUX_Manuel.html (copie dans <FLUX_ROOT>/FLUX_DOC au demarrage, features/system/manual.py, ADR 0049)
│   │                         manual/FLUX_Flows.html (genere depuis docs/user/flows/ : python -m features.system.flows_doc, meme copie)
│   └── tests/                run_tests.py + une suite par dossier (test_flux_core, test_flux_actions, security...)
│
├── scripts/                  build.cjs (npm run build + version), backend.spec, electron-builder.yml, installer.nsh, flux_version.nsh, set_exe_icon.cjs (afterPack: logo dans FLUX.exe), icon.ico/png,
│                             build_hdas.py, rebuild_importer_hda.py
│
├── tools/                    scripts hors application (cross_platform/ : audit des chemins Windows/Linux,
│                             publish/ : publication + hook pre-push, voir publish/CONTEXT.md)
│
├── docs/                     index : docs/README.md
│   ├── development/          BUILD, STRUCTURE (ce fichier)
│   ├── user/                 doc utilisateur : README, REZ, PUBLISH_ROLLBACK, FLOWS_BRIDGE_3DSMAX
│   │   └── flows/            doc des Flows (03_INDEX_NODES.md embarque dans l'app : bouton (i) des nodes)
│   └── images/               captures du README
│
├── index.html, vite.config.ts, postcss.config.js, tailwind.config.js,
├── tsconfig.json, tsconfig.electron.json, package.json, package-lock.json
```

Chaque dossier important a un `CONTEXT.md` court (role + pieges).

## Chemins a ne pas changer sans propagation

| Fichier | Valeur sensible | Pourquoi |
|---|---|---|
| `scripts/backend.spec` | `backend/main.py`, `pathex=["backend"]`, `("resources", "resources")`, `collect_all("pxr")` | Le sidecar PyInstaller est construit depuis ces chemins. |
| `scripts/electron-builder.yml` | `extraResources from: backend/dist/flux_backend`, `buildResources: scripts/`, `output: INSTALLEURS`, `files` (inclut `scripts/icon.*`) | Sidecar, icones et sortie de l'installeur. |
| `app/electron/python_bridge.ts` | `process.resourcesPath/backend/flux_backend.exe`, port `8765` | Chemin du sidecar dans l'app packagee. |
| `app/electron/main.ts` | `preload.js` et `../dist/index.html` relatifs a `__dirname`, icones `../scripts/icon.*` | Charges depuis `dist-electron/` et `app.asar`. |
| `tsconfig.electron.json` | `rootDir` `app/electron`, `outDir` `dist-electron` | Sortie packagee par electron-builder. |
| `vite.config.ts` | `outDir: 'dist'`, `base: './'` | `file://` en prod. |
| `package.json` | `"main": "dist-electron/main.js"`, scripts `build:*` | Entree Electron, `python -m PyInstaller`. |
| `index.html` | `/app/src/main.tsx` | Entree Vite. |
| `tailwind.config.js`, `tsconfig.json`, `vite.config.ts` | `app/src/**`, alias `@` | Contenu CSS et resolution TS. |
| `scripts/backend.spec` (datas) | `backend/features/render/bridge/flux_tractor_bridge.py` -> `features/render/bridge` | Script bridge Tractor embarque en donnees dans le sidecar. |
| `scripts/backend.spec` (datas) | `backend/features/render/blade/flux_freeze_at_start.py` -> `features/render/blade` | Gel au demarrage d'un rendu programme, copie dans `_job/` et lance sur la blade par le python de Houdini. |
| `scripts/backend.spec` (hiddenimports) | `collect_submodules("flux_flows.nodes")`, `collect_submodules("features.dispatcher")` | Modules de nodes importes par nom (`registry.BUILTIN_MODULES`) et dispatcher importe a la demande (ADR 0067) : invisibles pour l'analyse statique. |
| `backend/resources/` | 3 niveaux de parent depuis `shelf_core.py`, `sys._MEIPASS` en frozen | Shelves et templates. |
| `backend/flux_actions/config/*.yml` | exception `!backend/flux_actions/config/*.yml` dans `.gitignore` | Sinon un nouveau YAML n'est pas tracke (piege V4). |

Doivent rester a la racine : `index.html`, `vite.config.ts`, `postcss.config.js`, `tailwind.config.js`, `tsconfig*.json`, `package*.json`.

## Ignore par git (local seulement)

| Ignore | Genere par / role |
|---|---|
| `dist/`, `dist-electron/`, `backend/dist/`, `build/`, `release/`, `INSTALLEURS/` | builds |
| `node_modules/`, `__pycache__/`, `.venv/` | dependances |
| `config.json` | config machine (dev : racine du repo) |
| `USER/`, `CONFIG/`, `DOSSIER_PROJETS/`, `test/` | donnees locales FLUX_ROOT de dev |
| `PRIVATE/`, `state/`, `scratchpad/` | fichiers locaux du mainteneur |
