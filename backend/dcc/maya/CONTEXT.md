# CONTEXT - `backend/dcc/maya/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee de mai 2026 retiree (lisible au tag `archive/pre-cleanup`).
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`.

`maya_connection.py` (client commandPort `127.0.0.1:7001..7008` ; le port est ouvert par le bloc userSetup de `autostart.py`, S3), `port_guard.py` (Windows), `maya_export*.py`, `maya_import.py`, `maya_publish.py`, `maya_shelf.py`, `maya_usd_light_export.py` (export USD leger ; avec `options.preset` il delegue a `maya_usd_presets.py` : model / rig / anim, ADR 0034), `maya_usd_preview.py` (listing de ce que chaque preset exporterait, `GET /dcc/maya/usd-preview`), `maya_bonecapture.py`, `import_prep.py` (cote backend : chemin ASCII, USD aplati pour mayaUsd, appel JSON de `maya_update` ; sorti de `routers/dcc.py` en V9-08), `maya_update.py` (X4 : tag `flux_project` / `flux_source` / `flux_stamp` / `flux_mode` pose par `run_import` sur les nodes racine d'un import FLUX, `run_list` / `run_replace` pilotes par `POST /dcc/maya/update-imports`, bouton shelf "MAJ" = `update_imports()` dans un thread car le hub rappelle Maya par le commandPort), `maya_rigs.py` (ADR 0023 : boutons shelf "CAM" = `create_camera_rig()` importe le rig du mainteneur `resources/rigs/maya/flux_cam_rig.ma` (rig seul, sans globals de scene ni chemin machine ; un 2e rig va dans le namespace `CAM`), "LIGHT" = `create_light_rig()` importe le rig du mainteneur `resources/rigs/maya/flux_light_rig.ma` (key / fill / rim directionnelles + dome ambient ; 2e rig dans le namespace `LIGHT`), un undo chacun, attribut `flux_rig`), `maya_layout.py` (placements `|<ASM>|<CLASS>|<INSTANCE>` pour le publish du layout d'assembly, enveloppe JSON), `autostart.py` (userSetup).

`startup/flux_bridge.py` (ancien pont qui lisait `install_path.txt`) archive le 2026-09-18 puis retire (lisible au tag `archive/pre-cleanup`) : le bloc userSetup d'`autostart.py` ouvre le port directement et remplace l'ancien bloc `flux_bridge`.

`maya_keys.py` (U1, 2026-09-24) : plage de l'export anime = premiere / derniere cle (selection + hierarchie, ou scene ; cles pilotees `animCurveU*` ignorees), sinon la timeline. `GET /dcc/maya/anim-range?scope=` via `import_prep.call_maya_update(..., module="maya_keys")`. Houdini : `GET /dcc/houdini/anim-range` = playbar. Le Publisher remplit Start / End a l'activation d'ANIMATION (bouton "Cles" pour relire).

`maya_instances.py` (U2, 2026-09-24) : instances d'un perso dans la scene (noeuds racine / namespaces commencant par NAME, ou imports FLUX de NAME via `flux_source`), numero lu dans le nom (`DINGO_02`, `DINGO2`) sinon premier libre. `GET /dcc/maya/character-instances?name=`. Le Publisher (shot, USD leger) les liste des que le perso est choisi, toutes cochees ; une anim publiee par instance cochee (`SEQ_SHOT_ANIM_DINGO` pour 01, `..._DINGO_02` ensuite), exportee depuis les meshes sous le noeud (`run_light_export(root=...)`).

Presets shot `camera` / `light` (2026-09-27) : `maya_usd_presets.camera_asset` / `light_asset` (nœuds via `maya_usd_light_export._camera_nodes` / `_light_nodes`, donnees `_camera_data` / `_light_data`, bake `_bake`), apercu `maya_usd_preview.list_cameras` / `list_lights`. Scope selection : le nœud, sa shape ou un groupe au-dessus selectionne.

Flows P6a (2026-10-23) : `maya_hub.py` (cote backend) porte la logique hub de `POST /dcc/maya/import` (`import_into_maya`,
`send=` injectable) et `/update-imports` (`update_imports`, `dry`, `only`, `call=`) ; les routes gardent leurs controles
et traduisent `MayaHubError` en meme HTTP. `maya_playblast.py` (NOUVEAU, cote Maya, importe depuis la racine backend
comme `maya_update`) : playblast de la vue active (mov / mp4 H.264, sequence PNG), node `mayPlayblast` Live seulement,
**non valide en live**. Nodes `may*` : `backend/flux_flows/nodes/dcc_maya.py` (le code passe par la session : commandPort
en Live, worker `mayapy` en headless). `autostart.py` non modifie.
