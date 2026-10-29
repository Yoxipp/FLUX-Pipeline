# CONTEXT - `backend/dcc/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/backend__dcc.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

`bridge_secret.py` (2026-10-24) : secret par poste (`%APPDATA%/FluxPipeline/bridge_secret.txt`) qui protege l'action `run` des bridges TCP ; l'installation du bridge le copie dans `<script>.json` a cote du script, la desinstallation le retire.

Un dossier par logiciel : `maya`, `houdini`, `zbrush`, `nuke`, `substance_painter`, `substance_designer`, `marvelous`, `mari`, `photoshop`, `unreal`. Chaque dossier melange code backend (`client.py`, `*_export.py`) et code execute DANS le logiciel (serveur/plugin installe par `autostart.py`).

Ports : `core/constants.py`. Tableau d'etat par DCC : `docs/architecture/OVERVIEW.md` section 4.

Flows (P6a, 2026-10-23) : les nodes DCC des Flows enveloppent ces clients sans les reecrire (`backend/flux_flows/bridges/` :
`softs.py` registre logiciel -> cle de constantes / launcher / prefixe / transport, `primitives.py`, `session.py`,
`headless.py`). Refactors : `houdini_export` / `houdini_import` `client=`, `HoudiniClient.get` / `post`, Marvelous
`mailbox_dir(name)` + `call(..., box=)`, `maya/maya_hub.py`. Aucun `autostart.py` ni serveur Houdini modifie.

Flows P6c (2026-10-23) : un logiciel non livre s'ajoute en bridge d'extension (`CONFIG/extensions/bridges/<soft>/bridge.yml`,
`backend/flux_flows/bridges/extension.py`, modeles `bridges/templates/`), jamais dans `dcc/`. Plages de ports a ne pas
chevaucher : `core/constants.DCC_PORT_RANGES`. Aucun `autostart.py` modifie.

Flows P6b (2026-10-23) : `NukeClient`, `SubstancePainterClient`, `SubstanceDesignerClient`, `MariClient` prennent
`port=` (une instance de la plage ; sans port, appels identiques a avant). `core/dcc_context.instance_context` lit aussi
le script ouvert de Nuke. Etat par logiciel des nodes Flows :

| Logiciel | Transport (session) | Nodes (P6b) | Publish boite noire | Reportes ("bridge+", accord du mainteneur + live) | Live |
|---|---|---|---|---|---|
| Nuke (`nk`) | TCP JSON `{"cmd"}`, `run(code)` | Instance, OpenScene, SaveScene, SaveAs, RunScript, Export (Write temporaire), Import (Read), Render (Write existant), FindNodes ; SceneOpened | `publish_from_nuke` | aucun (headless `nuke -t` non offert) | a verifier par le mainteneur |
| Substance Painter (`sp`) | TCP JSON `{"action"}`, `run` protege par le secret du poste | Instance, Export, Info ; bridge+ (2026-10-24) : OpenScene (.spp ou mesh), SaveScene, SaveAs, Import (mesh ou ressource), RunScript | `publish_painter` | aucun (bridge a reinstaller) | bridge+ valide live 2026-10-24 ; export / publish a verifier |
| Substance Designer (`sd`) | TCP JSON `{"action"}`, `run` protege par le secret du poste | Instance, Export, Info, Cook (`sbscooker` cote hub, sans session) ; bridge+ (2026-10-24) : OpenScene (charge un .sbs de plus), SaveScene / SaveAs (package du graphe courant), Import (bitmap, mesh lies), RunScript | `publish_designer` | aucun (bridge a reinstaller) | a verifier par le mainteneur |
| Marvelous (`mvd`) | boite a fichiers (une instance), `run` protege par le secret du poste (lu dans `%APPDATA%`) | Instance, Export, Import, Info ; bridge+ (2026-10-24) : OpenScene (.zprj avec discard_changes), SaveScene, SaveAs (.zprj), RunScript | `publish_marvelous` | aucun (script a reinstaller et relancer dans Marvelous) | a verifier par le mainteneur |
| ZBrush (`zb`) | TCP `{"action"}`, `run` protege par le secret du poste (lu dans `%APPDATA%`) | Instance, Export (ztl, obj, fbx), MeshInfo ; bridge+ (2026-10-24) : OpenScene (.zpr avec discard_changes, ou .ztl), SaveScene, SaveAs (.zpr ou .ztl), Import (mesh, tool), RunScript. Tout ne marche que pendant Export FLUX (gel) ; relache a la fin du run et sur erreur | `publish_zbrush` | aucun (bridge a reinstaller) | a verifier par le mainteneur |
| Mari (`mari`) | TCP JSON `{"action"}`, `run` protege par le secret du poste | Instance, Export (un a la fois), Info ; bridge+ (2026-10-24) : OpenScene (nom de projet, .mra ou mesh), SaveScene, SaveAs (archive .mra), Import (image, object, version), RunScript | `publish_mari` | aucun (bridge a reinstaller) | a verifier par le mainteneur |
