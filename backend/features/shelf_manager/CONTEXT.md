# CONTEXT - `backend/features/shelf_manager/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/backend__features__shelf_manager.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

`shelf_core.py` : installation shelves Maya/Houdini, deploiement des HDA FLUX (`deploy_houdini_hdas`, ex-installer), `_build_hdas_live`.

Boutons pipeline toujours presents sur la shelf Flux Maya (`shelf_FluxPipeline.mel`) : MAJ, CAM (Camera Rig), LIGHT (Light Rig) (ADR 0023).

Shelf Houdini (2026-09-24) : `install_shelf("Houdini")` copie `Flux.shelf` puis appelle `install_hdas` (build live si Houdini connecte, sinon copie stagee), non bloquant, message combine. `remove_shelf` garde les HDA (l'Autostart s'en sert, son uninstall les retire). Tests : `tests/shelf_manager`.

`resources/shelves/houdini/Flux.shelf` (2026-09-24) : un bouton par node FLUX (Import, Export, Anim, Shot, Crowd, Lighting), icone = IconSVG du HDA. Le bouton cree le node dans le reseau courant s'il est du bon contexte, sinon dans `/stage` (LOP) ou un `geo` de `/obj` (SOP). L'ancien outil "Import KineFX" est retire.
