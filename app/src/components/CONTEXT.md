# CONTEXT - `app/src/components/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee de mai 2026 retiree (lisible au tag `archive/pre-cleanup`).
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

Contient `shared/` : composants communs (Sidebar, TitleBar, StatusBar, Console, BackendBanner, ExportOptions, SoftwareSelector, ActionForm, ui).

ADR 0044 (interface par menus) : `ExpandPicker` (bouton = choix courant, les autres glissent a droite au clic), `DccLogo` (marques des logiciels en accent ; officielles Maya/Houdini/Nuke/Photoshop via Simple Icons CC0, monogrammes sinon), `ConnectionPill` (un point + un mot, details au clic). `SoftwareSelector` n'est plus une barre : c'est un `ExpandPicker` a placer dans la `.page-toolbar` de la page. Launcher (Sidebar) : logo + bouton Play, toutes les actions dans le menu au clic.

Style : pas de neon/glow, pas de tiret cadratin dans les textes UI.

TitleBar (retake 06) : l'engrenage ouvre la page `/settings` (plus de popover Parametres) ; Sidebar Pipeline sans Editeur de Template ni Disque (dans Parametres > Avance).
