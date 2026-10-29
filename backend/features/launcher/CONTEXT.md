# CONTEXT - `backend/features/launcher/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/backend__features__launcher.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

`launcher_core.py` : detection et lancement des DCC avec scene (liste d'arguments, pas de `shell=True`, S4), branche POSIX presente.

Detection des exe (retake F2, 2026-10-09) : `list_dcc_candidates(key)` = toutes les installs trouvees, la plus recente
d'abord. Sources : registre Windows (Maya : `HKLM\SOFTWARE\Autodesk\Maya\<ver>\Setup\InstallPath` `MAYA_INSTALL_LOCATION` ;
Photoshop : `HKLM\SOFTWARE\Adobe\Photoshop\<ver>` `ApplicationPath` et `App Paths\Photoshop.exe`), puis les globs de
`DCC_EXE_PATTERN_GROUPS` (`core/constants.py`) sur toutes les racines `%ProgramW6432%`, `%ProgramFiles%`, `%ProgramFiles(x86)%`.
Tri : groupe de priorite d'abord (ex. Painter Adobe avant un vieux Allegorithmic), puis version numerique du dossier
(`Photoshop 2025` > `CC 2019`, `Houdini 20.5.332` > `20.0`). `winreg` garde (absent hors Windows, mocke en test).
Un chemin perso configure qui n'existe plus est ignore avec un warning (une fois par chemin). Tests : `tests/system/test_dcc_detection.py`.

`bridges.py` (retake F1) : `install_all_bridges` installe le bridge de chaque DCC detecte (memes `dcc/<soft>/autostart.install`
que le menu du launcher) + la librairie Photoshop ; resultat par DCC `ok` / `skip` (non detecte) / `error`, jamais d'exception.
Route `POST /dcc/bridges/install-all`, bouton dans Parametres > User > Logiciels. Tests : `tests/dcc_router/test_install_all_bridges.py`.
Flows P6c (2026-10-23) : la route ajoute les bridges d'extension valides (`flux_flows/bridges/installer.install_all_entries`,
cle "<label> (extension)", `skip` si `exe_hints` ne trouve rien, conflit = `error` sans ecrasement). `launch_exe(exe, scene, *, extra, env,
label)` extrait de `launch_dcc` (comportement inchange) lance l'exe d'une extension. Tests : `tests/launcher_exe`.

Plage de frames au lancement (2026-09-27) : un Maya / Houdini lance **sans scene** demarre sur `DEFAULT_FRAME_START`-`DEFAULT_FRAME_END` (1001-1050, `core/constants.py`). Le launcher ajoute un script en ligne de commande (`maya -script resources/startup/flux_frame_range.mel`, `houdini resources/startup/flux_frame_range.cmd`) et passe la plage via `FLUX_FRAME_START` / `FLUX_FRAME_END`. Rien a installer dans les prefs. Un lancement avec scene (preset, scene de rendu de sequence) garde sa plage. Script absent -> lancement normal + warning.
