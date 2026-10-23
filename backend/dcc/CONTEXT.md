# CONTEXT - `backend/dcc/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/backend__dcc.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

Un dossier par logiciel : `maya`, `houdini`, `zbrush`, `nuke`, `substance_painter`, `substance_designer`, `marvelous`, `mari`, `photoshop`, `unreal`. Chaque dossier melange code backend (`client.py`, `*_export.py`) et code execute DANS le logiciel (serveur/plugin installe par `autostart.py`).

Ports : `core/constants.py`. Tableau d'etat par DCC : `docs/architecture/OVERVIEW.md` section 4.

Flows (P6a, 2026-10-23) : les nodes DCC des Flows enveloppent ces clients sans les reecrire (`backend/flux_flows/bridges/` :
`softs.py` registre logiciel -> cle de constantes / launcher / prefixe / transport, `primitives.py`, `session.py`,
`headless.py`). Refactors : `houdini_export` / `houdini_import` `client=`, `HoudiniClient.get` / `post`, Marvelous
`mailbox_dir(name)` + `call(..., box=)`, `maya/maya_hub.py`. Aucun `autostart.py` ni serveur Houdini modifie.
