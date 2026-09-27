# CONTEXT - `backend/features/launcher/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/backend__features__launcher.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

`launcher_core.py` : detection et lancement des DCC avec scene (liste d'arguments, pas de `shell=True`, S4), branche POSIX presente.

Plage de frames au lancement (2026-09-27) : un Maya / Houdini lance **sans scene** demarre sur `DEFAULT_FRAME_START`-`DEFAULT_FRAME_END` (1001-1050, `core/constants.py`). Le launcher ajoute un script en ligne de commande (`maya -script resources/startup/flux_frame_range.mel`, `houdini resources/startup/flux_frame_range.cmd`) et passe la plage via `FLUX_FRAME_START` / `FLUX_FRAME_END`. Rien a installer dans les prefs. Un lancement avec scene (preset, scene de rendu de sequence) garde sa plage. Script absent -> lancement normal + warning.
