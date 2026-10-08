# CONTEXT - `app/src/components/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/app__src__components.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

Contient `shared/` : composants communs (Sidebar, TitleBar, StatusBar, Console, BackendBanner, ExportOptions, SoftwareSelector, ActionForm, ui).

ADR 0044 (interface par menus) : `ExpandPicker` (bouton = choix courant, les autres glissent a droite au clic), `DccLogo` (marques des logiciels en accent ; officielles Maya/Houdini/Nuke/Photoshop via Simple Icons CC0, monogrammes sinon), `ConnectionPill` (un point + un mot, details au clic). `SoftwareSelector` n'est plus une barre : c'est un `ExpandPicker` a placer dans la `.page-toolbar` de la page. Launcher (Sidebar) : logo + bouton Play, toutes les actions dans le menu au clic.

Style : pas de neon/glow, pas de tiret cadratin dans les textes UI.
