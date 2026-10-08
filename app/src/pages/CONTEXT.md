# CONTEXT - `app/src/pages/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/app__src__pages.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

Pages : `Hub`, `Projects` (Folder Manager, 1630 l. + `folder_manager/`), `Production/`, `Publisher` (1999 l.), `UsdAssembler` (vue Bibliotheque par defaut `usd/UsdLibrary.tsx` : assets, decors ; onglet Shots retire, ADR 0023 ; tri / filtre par tokens de classement `tokens` + `token_keys` de GET /usd/library, `lib/usdTokenSort.ts`, retake 03), `Activity`, `ShelfManager`, `TemplateEditor`, `ActionPublish`, `ActionGraph` (node flow lecture seule, route cachee `/action-graph`), `FirstLaunch`, `Login` (changer / creer d'utilisateur seulement). `settings/` (ADR 0046, retake 06) : `SettingsPage` /settings onglets User / Projet / Avance (Avance = `AdvancedSettings part="advanced"` + Disque + Editeur de Template, plus dans la sidebar ; `/advanced`, `/disk`, `/templates` redirigent), `UserSettings`, `SettingsDialogs` (confirmations Understand / desinstaller, sorties de TitleBar).

Pages geantes = dette connue, ne pas les decouper sans demande.

## Production (2026-10-02)

* `ProductionTracking.tsx` + `tracking.css` : table Shots/Assets par departement, recherche,
  Show All/Seq/Mine, miniatures, casting compact, Timing et dependances rouges sous les badges
  de projet. Main, Timeline (Shots) et retakes plein ecran partagent des onglets compacts.
  Pas de panneau droit ni de barre de review du bas ; edition d'entite en modale.
* `ProductionSettings.tsx` : onglet Settings, fixed/optional pour tous les departements,
  liste reordonnee/supprimable, sans toucher aux taches ni aux dossiers. Configuration souveraine.
* `ProductionTableMenus.tsx` : Show All/Seq/Mine et liste compacte des entites liees ; ouverture
  d'un onglet de table filtre sur une seule entite dans le bon mode.
* `EntityContextMenu.tsx` : edit au clic droit, Lock/Unlock de shot, Delete avec confirmation
  d'archivage existante (`MenuEdit.useArchiveDelete`). Pas d'edit au clic simple du nom.
* Production est a 90% par defaut ; boutons de zoom retires, Ctrl+molette reste disponible.
* `NewProductionDialog.tsx` : creation asset/groupe ou sequence/shots, choix de sequence,
  creation multiple validee avant sauvegarde. Assets/Shots sont sous Production dans la sidebar.
* `taskPriority.ts` (retake 07) : seule logique de priorite des taches. `task_details[<TASK>|<SUB>].priority`
  = `high` | `low` (absent = normale), reglee au clic droit d'un badge > Priorite (aussi en selection
  multiple), marquee par une fleche sur le badge. `myTasks` (taches assignees a un artiste), deadline =
  entree Calendrier ouverte la plus proche liee au shot (meme regle que le badge deadline) ou au NAME
  de l'asset, `sortMyTasks` : Recommande (deadline > priorite > statut RTK d'abord), Deadline, Priorite,
  Statut, Mise a jour (dernier publish ou commentaire), Nom ; validees toujours a la fin, nom en
  departage. Accueil : colonne droite `home/MyTasks.tsx` (projet actif, pages de 30, clic = la tache
  dans Production, shots compris via `openFavorite`).
* `CreateMenu.tsx` (retake 05) : un bouton Create en haut du tableau et de la Timeline, menu
  Shot / Sequence (ou Asset / Groupe) qui ouvre `NewProductionDialog` sur ce type ; Shot grise
  sans sequence. Timeline (`ProductionShot.tsx`) : molette = defiler, Maj+molette = page,
  Ctrl+molette = zoom sous le curseur, Ctrl+Maj+molette = hauteur, clic milieu glisse = deplacer,
  bouton Tout voir ; aide des gestes affichee au premier usage puis dans l'infobulle.
  Molette ignoree sur un champ ; curseurs H / V gardes (tactile, pas de molette).
  Clic droit d'un shot : Suivre le shot (notifications Self, ADR 0045).
  ADR 0047 : clic sur un clip = selection + apercu sous le montage (`TimelinePreview.tsx`, logique
  `previewEdit.ts`) ; clic droit = Editer, Montage de la sequence, Keyframe Pro, bookmark. Source de
  l'apercu (Auto / Tout / etape) gardee en localStorage. Montage de la sequence ou du film lu dans FLUX
  (duree des shots respectee, trous gardes) ou envoye a Keyframe Pro. Point blanc = media disponible.
* `TaskDetail.tsx` > `MediaEmbed` (retake 10, ADR 0047) : bandeau sous la video (version affichee,
  Derniere version, Versions (n), Keyframe), liste des versions depuis le modif log du dossier `ref/`
  (auteur, date, statut, miniature, fleches / Entree / Echap), choix garde pour la session par zone.
  `lib/keyframe.ts` : appel `/review/keyframe/open` + toasts + lecteur systeme si Keyframe absent.
* `TaskStatusBadge.tsx` + `taskActions.ts` : meme menu clic droit Main/retakes, statuts,
  artiste courant/prise/assignation via les utilisateurs du pipe, Publisher (Instance vide)
  et chemin Folder Manager resolu au backend. Artiste stocke dans `task_details.assignee`.
* `tracking.ts` : statuts agreges, heritage des taches/casting, dependances, materialisation
  des taches et patch de review sans perdre les notes. Configuration optionnelle
  `production.tracking.departments`, review dans `task_details.status` (ADR 0041).
* Un badge ouvre `MenuSpec.initialOpen` avec l'entite, la tache et la sous-tache choisies.
  Aucun nouveau store de review. Fixe = TODO sans creation ; optionnel = cellule vide au clic droit. Les miniatures utilisent
  les references versionnees existantes, sous `_production/thumbnails/<id>`.
* Timeline est ouverte dans la bande d'onglets des Shots des le depart ; Main reste la vue
  initiale. Les onglets ouverts et filtres Main survivent a l'ouverture des retakes.
  Show > Lignes > Departments (sous-menu) : colonnes cochees a la main, pre-reglees par le profil de travail
  (ADR 0043, `workPrefs.productionDepartments`, noms en majuscules, au moins une colonne,
  mode sans departement coche = toutes les colonnes). NEED calcule sur tous les departements.
  Le filtre de lignes All/Seq/Mine reste local par projet et mode.
* `TrackingMenus.tsx` + `tableRows.ts` : sequences en blocs repliables, clic droit du nom
  pour Edit ; clic droit du titre de departement pour prioriser un statut. Tri local a
  la vue, par sequence, sans changer l'ordre sauvegarde. Icone artiste accent sous les
  badges assignes a l'utilisateur ; tooltip affiche uniquement les artistes concernes.
* `taskSelection.ts` : Ctrl/Meta + clic autour du badge ajoute/retire une tache, Shift + clic selectionne
  un rectangle de lignes/departements visibles. Clic droit sur la selection : assignation,
  prise en charge, statut commun ou suppression des badges avec confirmation. Une seule
  mise a jour de production par action groupee ; filtres/repli retirent les taches masquees.
  Clic simple autour du badge deselectionne tout ; le badge ouvre toujours les retakes.
  Fonctionne dans Shots et Assets, y compris cellules optionnelles vides et shots verrouilles.
  Hovers artiste/NEED : echelle explicite 0.9 * zoom du tableau ; texte, espacements et
  fleche redimensionnes en pixels via --tooltip-scale, sans zoom CSS sur le popup porte.
  Hovers zoomes ancres directement via getBoundingClientRect en coordonnees fenetre
  (`shared/tooltipPosition.ts`), avec suivi du zoom et retournement aux bords.
  Rendu zoome non interactif : disableHoverableContent ferme au pointerleave ; fermeture
  aussi au blur, clic exterieur, scroll, Echap ou ouverture d'un autre tooltip.
  Cellules vides : bouton invisible sans interception du pointeur ; la zone de selection
  couvre aussi le centre vide et le menu de statut cree les badges selectionnes.
* `useProductionShow.ts` + `showPreference.ts` : filtre Show conserve dans localStorage
  par projet et mode, avec preferences distinctes pour les vues d'entite. Survit a la
  navigation et aux redemarrages ; donnees manquantes/corrompues retournent All.
  Les cellules reservent des emplacements fixes au-dessus/dessous du badge : NEED
  rouge au-dessus, tooltip avec les dependances requises, icone artiste en dessous.
  Leur apparition/disparition ne change ni la position du badge ni la hauteur de ligne.
* Supprimer le badge passe par une confirmation simple et ecrit `task_details.status = ''`.
  Cette valeur explicite cache meme un badge fixe sans retirer la tache, les sous-taches,
  l'artiste ou les notes ; le clic droit de la cellule permet de choisir un nouveau statut.
  Un badge fixe efface ne suffit pas a faire passer le shot en Done.
* Retakes : `TaskDetail.renderHeader` insere le statut et les actions dans le seul bandeau
  colore `TaskStrip`. Aucune suppression de tache/sous-tache depuis cette page.
  Sidebar Production : fleche, trait continu vers Assets/Shots, fermeture aux changements
  d'onglet (`flux:production-tab-change`) ou de page sauf maintien via l'icone de fenetre.
* Timing concerne les shots seulement. Les badges de statut restent editables sur les shots
  verrouilles : seuls les `task_details` changent, aucune tache structurelle n'est ajoutee.
* `shotCalendar.ts` + `ShotDeadlineBadge.tsx` : badge de delai a droite du label, calendrier
  relu toutes les 30 secondes et au focus/refresh. Liens par tokens exacts sequence + shot.
  None sans lien non refuse, Done si tous les statuts visibles sont APPROVED (cellules
  optionnelles vides ignorees), sinon echeance ouverte la plus proche : Extra-late <= 0 jour,
  Late < 5 jours, In time >= 5 jours. Une fin calendrier ne vaut pas approval de production.
  Le menu Calendar ouvre `/calendar?project=...&seq=...&shot=...`, filtre la grille et
  selectionne la tache liee ; sans tache, le formulaire reprend le lien sans creer d'entree.

## Folder Manager (`Projects.tsx` + `folder_manager/`, B2 2026-09-28)

* `Projects.tsx` : la page. Barre laterale (listes sauvegardees, presets), menu Affichage (vues, taille des tuiles,
  formulaires de creation repliables ; preferences de page dans le navigateur, hors profils ADR 0043,
  Ctrl + molette = taille), Token Finder, onglets de creation,
  panneau droit, choix des vues (1 / 2 empilees / 2 cote a cote / 4), et l'etat partage par les vues
  (`FolderManagerContext` : favoris, presse-papier, undo, `transfer` = tout deplacement / copie, `fsTick` = relecture
  de toutes les vues apres une ecriture). La vue active (dernier clic, cadre accent) pilote le panneau droit, le projet
  actif, les presets et les resultats du Token Finder.
* `folder_manager/ExplorerPane.tsx` : une vue (historique, barre de chemin, recherche, grille, selection, menu clic
  droit, modales). Memoire de session par vue (`fm.navStack` pour la vue 0, `fm.paneN.*` pour les autres). Glisser
  d'une vue a l'autre : Ctrl = copie, sinon deplacement, meme projet seulement.
* `folder_manager/shared.ts` (types, helpers, contexte), `open_in.ts` (actions "Open in" DCC), `ItemModals.tsx`,
  `icons.tsx`.

## Activity

* Menu Notifications (en-tete) : mentions, taches suivies, publishs / commentaires / erreurs
  des autres artistes du projet actif. Pre-regle par le profil de travail (ADR 0043).

* Table Production (2026-10-08) : layout fixe (`colgroup`), Shot / Timing / Casting gardent leur largeur
  et les departements masques elargissent les colonnes de departement. Plus de resume
  "X taches selectionnees" : Ctrl / Shift + clic sur le badge selectionne, clic simple ouvre les retakes.
