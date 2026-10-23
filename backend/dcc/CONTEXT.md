# CONTEXT - `backend/dcc/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/backend__dcc.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

Un dossier par logiciel : `maya`, `houdini`, `zbrush`, `nuke`, `substance_painter`, `substance_designer`, `marvelous`, `mari`, `photoshop`, `unreal`. Chaque dossier melange code backend (`client.py`, `*_export.py`) et code execute DANS le logiciel (serveur/plugin installe par `autostart.py`).

Ports : `core/constants.py`. Tableau d'etat par DCC : `docs/architecture/OVERVIEW.md` section 4.

Flows (P6a, 2026-10-23) : les nodes DCC des Flows enveloppent ces clients sans les reecrire (`backend/flux_flows/bridges/` :
`softs.py` registre logiciel -> cle de constantes / launcher / prefixe / transport, `primitives.py`, `session.py`,
`headless.py`). Refactors : `houdini_export` / `houdini_import` `client=`, `HoudiniClient.get` / `post`, Marvelous
`mailbox_dir(name)` + `call(..., box=)`, `maya/maya_hub.py`. Aucun `autostart.py` ni serveur Houdini modifie.

Flows P6b (2026-10-23) : `NukeClient`, `SubstancePainterClient`, `SubstanceDesignerClient`, `MariClient` prennent
`port=` (une instance de la plage ; sans port, appels identiques a avant). `core/dcc_context.instance_context` lit aussi
le script ouvert de Nuke. Etat par logiciel des nodes Flows :

| Logiciel | Transport (session) | Nodes (P6b) | Publish boite noire | Reportes ("bridge+", accord du mainteneur + live) | Live |
|---|---|---|---|---|---|
| Nuke (`nk`) | TCP JSON `{"cmd"}`, `run(code)` | Instance, OpenScene, SaveScene, SaveAs, RunScript, Export (Write temporaire), Import (Read), Render (Write existant), FindNodes ; SceneOpened | `publish_from_nuke` | aucun (headless `nuke -t` non offert) | a verifier par le mainteneur |
| Substance Painter (`sp`) | TCP JSON `{"action"}`, pas de code | Instance, Export, Info | `publish_painter` | open, save, save_as, run_script, import | a verifier par le mainteneur |
| Substance Designer (`sd`) | TCP JSON `{"action"}`, pas de code | Instance, Export, Info, Cook (`sbscooker` cote hub, sans session) | `publish_designer` | open, save, save_as, run_script, import | a verifier par le mainteneur |
| Marvelous (`mvd`) | boite a fichiers (une instance) | Instance, Export, Import, Info | `publish_marvelous` | open, save, save_as, run_script | a verifier par le mainteneur |
| ZBrush (`zb`) | TCP `{"action"}`, pas de code | Instance, Export (ztl, obj, fbx), MeshInfo ; ZBrush toujours relache | `publish_zbrush` | open, save, save_as, run_script, import | a verifier par le mainteneur |
| Mari (`mari`) | TCP JSON `{"action"}`, pas de code | Instance, Export (un a la fois), Info | `publish_mari` | open, save, save_as, run_script, import | a verifier par le mainteneur |
