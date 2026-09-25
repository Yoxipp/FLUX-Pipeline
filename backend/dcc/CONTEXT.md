# CONTEXT - `backend/dcc/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/backend__dcc.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

Un dossier par logiciel : `maya`, `houdini`, `zbrush`, `nuke`, `substance_painter`, `substance_designer`, `marvelous`, `mari`, `photoshop`. Chaque dossier melange code backend (`client.py`, `*_export.py`) et code execute DANS le logiciel (serveur/plugin installe par `autostart.py`).

Ports : `core/constants.py`. Tableau d'etat par DCC : `docs/architecture/OVERVIEW.md` section 4.
