# CONTEXT - `backend/dcc/maya/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/backend__dcc__maya.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

`maya_connection.py` (client commandPort `127.0.0.1:7001..7008` ; le port est ouvert par le bloc userSetup de `autostart.py`, S3), `port_guard.py` (Windows), `maya_export*.py`, `maya_import.py`, `maya_publish.py`, `maya_shelf.py`, `maya_usd_light_export.py`, `maya_bonecapture.py`, `autostart.py` (userSetup), `startup/flux_bridge.py`.

`startup/flux_bridge.py` lit `install_path.txt` que plus rien n'ecrit (bug connu, A VERIFIER).
