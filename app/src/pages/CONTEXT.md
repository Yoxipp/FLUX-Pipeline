# CONTEXT - `app/src/pages/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/app__src__pages.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

Pages : `Hub`, `Projects` (Folder Manager, 1630 l. + `folder_manager/`), `Production/`, `Publisher` (1999 l.), `UsdAssembler` (vue Bibliotheque par defaut `usd/UsdLibrary.tsx` : assets, decors ; onglet Shots retire, ADR 0023 ; tri / filtre par tokens de classement `tokens` + `token_keys` de GET /usd/library, `lib/usdTokenSort.ts`, retake 03), `Activity`, `ShelfManager`, `TemplateEditor`, `ActionPublish`, `flow_editor/` (editeur de Flows, route `/action-graph`, voir section plus bas), `ActionGraph` (ancien editeur des actions YAML, route `/action-graph-legacy` via `flow_editor/LegacyEditor.tsx`, retire en P8), `FirstLaunch`, `Login` (changer / creer d'utilisateur seulement). `settings/` (ADR 0046, retake 06) : `SettingsPage` /settings onglets User / Projet / Avance (Avance = `AdvancedSettings part="advanced"` + Disque + Editeur de Template, plus dans la sidebar ; `/advanced`, `/disk`, `/templates` redirigent), `UserSettings`, `SettingsDialogs` (confirmations Understand / desinstaller, sorties de TitleBar).

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
  de l'asset, `sortMyTasks` : Recommande (deadline > priorite > statut RTK d'abord), Deadline + Me
  concerne (`compareDeadlineConcern(user)` reutilisable : assignee a moi en RTK, puis assignee a moi,
  puis le reste, puis deadline ; a l'accueil = mes RTK d'abord), Deadline, Priorite,
  Statut, Mise a jour (dernier publish ou commentaire), Nom ; validees toujours a la fin, nom en
  departage. Accueil (`Hub.tsx`, un seul `useProduction` partage) : colonne gauche `home/MyTasks.tsx`
  (Tes taches, projet actif, pages de 30, clic = la tache dans Production, shots compris via
  `openFavorite`) puis `home/MyRetakes.tsx` (Tes retakes : commentaires `kind: 'retake'` ecrits par
  un autre sur une tache / sous-tache assignee a moi, ou sur la tache parente d'une sous-tache a moi,
  plus recent d'abord, lus grises via `useCommentReadState`) ; chat d'equipe a droite
  (`home/TeamChat.tsx`). Le flux "Activite recente" a quitte l'accueil (page Activite).
  Commentaire de tache : case Retake dans `TaskDetail` (`ProductionComment.kind`, absent = note).
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
  Depot (A6) : dragover / drop toujours acceptes dans la zone ; si le chemin n'est pas resolu
  (pas de projet, sequence du shot introuvable, erreur `/ref/resolve`), la raison s'affiche dans la
  zone, pendant le survol et en toast au lieu d'un drop ignore en silence.
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
  Retakes 2026-10-09 : mode Assets groupe par classe (CHAR, PROPS, ENV puis les autres ;
  libelles Charas/Props/Enviros), groupes repliables. Chevron d'une ligne asset = une ligne
  par sous-tache (known_subtasks + cles `TASK|SUB` de task_details) sous la colonne de sa
  tache, badge editable (TaskStatusBadge avec `subtask`). Bouton "Deadline + Me concerne"
  (localStorage `flux.production.sort.deadlineMine`) : lignes avec une tache assignee
  d'abord, puis deadline Calendar la plus proche (`entityDeadline`). Clic droit sur la
  miniature d'un shot : source de l'apercu (Auto, Tout, etapes), partagee avec la Timeline
  via `previewSourceStore.ts` (cle localStorage + evenement `flux:preview-source-change`).
  Origine des medias (Auto = ref sinon publish / Ref / Publish) : meme store (`flux.production.timeline.previewOrigin`,
  evenement `flux:preview-origin-change`). Par plan, champs optionnels `shot.preview_origin` et `shot.preview_version`
  (vNNN, absent = LAST), appliques par `previewEdit.ts` (`pickMedia` origine, `applyVersion`). `shot-previews` renvoie
  une entree ref ET une entree publish par tache, chacune avec `versions`. Evenement `flux:ref-change`
  (`notifyRefChange`) : depot / suppression / restauration d'une ref (TaskDetail) -> la Timeline refetch aussitot.
  Backend `/ref/delete` (vNNN seulement, LAST re-pointe) et `/ref/restore` (copie en nouvelle version).
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
  Sidebar Production : clic sur Production = deplie Assets/Shots, fermeture aux changements
  d'onglet (`flux:production-tab-change`) ou de page sauf si l'epingle (seul controle, contour
  accent quand active, gris sinon, localStorage `flux.sidebar.productionPinned`) est active.
  Arbre gris : trait vertical + branche horizontale par enfant (CSS `::before`).
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

## Editeur de Flows (`flow_editor/`, chantier Flows P0 2026-10-22)

Specs : `docs/yaml_update_refonte/03_EDITEUR.md` (disposition, familles, ports, fichiers), ADR 0057. P0 = lecture seule.
* `FlowEditor.tsx` : coque (route `/action-graph`, lien profond `?flow=<nom>`) : `TopBar` (choix du flow, badges, recherche,
  Cadrer, "Ancien editeur"), `ShelfBar` (onglet par famille), `NetworkPane` (@xyflow/react, Tab, F, Echap, MiniMap par famille),
  `ParamsPane` (node selectionne ou flow).
* `nodes/FlowNode.tsx` (barre de famille, icone, ligne exec, une ligne par port), `PortHandle.tsx` (forme et couleur par type,
  plein = relie), `PortTooltip.tsx` (une seule info-bulle en portail, 300 ms), `edges/FlowEdge.tsx` (exec blanc, data couleur du type).
* `families.ts` / `icons.ts` / `portTypes.ts` : variables `--fam-*` et `--port-*` de `globals.css`, table statique lucide.
* `v1_adapter.ts` : `ActionGraph` v1 -> `FlowView` (fonctions pures : commande -> famille, params -> ports, une chaine exec
  dans l'ordre des etapes, node Start en tete, liens data des parametres cables). Appels API dans `api/flows.ts` (routes v1).
* `TabMenu.tsx` : menu d'ajout a la souris (P4, filtre possible). `useTr.ts` copie de l'ancien editeur.
* P2 (runs, 03 §7) : `TopBar` Run (le document ouvert, `draft`, TD, aucune version), Essai (fichier enregistre, grise sur
  une version figee), Stop, Runs. `FlowEditor` ecoute `useFlowsWs` : etats par `run_id` (gardes meme avant la reponse du POST),
  toast des nodes Notify et de fin de run, relecture de `GET /flows/runs/{id}` a la fin et apres reconnexion.
  `FlowNode` : bordure et pastille par etat (`running` accent + LoaderCircle, `ok` coche + `xN`, `error` `--err` + message,
  valeurs recues en info-bulle, `error_handled` `--warn`, `skipped` / `cancelled` tirets). `RunsPanel.tsx` : dock Runs
  (historique du flow, clic = graph colore par ce run, rapport d'essai et logs, clic sur une ligne = selection du node).
* P4 (edition, 2026-10-23, 03 §4 a §6) :
  * Etat : `store.ts` (`createDocStore`, `useSyncExternalStore`, aucune dependance) tient le `FlowDoc` ; `history.ts` (pile
    immuable, 200, `coalesceKey` < 800 ms) ; `reducers.ts` (actions pures, partage structurel, aucun relayout) ;
    `clipboard.ts` (`flux_flow_clip: 1`, ids regeneres, colle a la souris) ; `layout.ts` (bouton Layout seul, une entree undo).
    La vue (`v2_adapter.adaptV2Flow`) est derivee du document ; un enregistrement garde la pile. Lecture seule la ou
    Enregistrer est bloque (livre, version figee, case absente).
  * Catalogue v2 (`GET /flows/catalog`, `adaptCatalog`) : ports par spec (exec, entrees, params promouvables, sorties),
    Tab / Shelf / `NodePalette.tsx` (tiroir Catalogue, glisser `application/x-flux-node` ou clic = centre).
    `portTypes.ts` = miroir de `types.py` (`canConnect`, `editorConnect` : une sortie `any` passe), `checkLink` pendant le
    glisser (ports compatibles entoures, autres a 35 %, raison en rouge dans `PortTooltip`, 2e lien sur une sortie exec refuse,
    entree data deja reliee = remplacee). Lien lache dans le vide = Tab des nodes compatibles, node cree relie.
    `test_catalog_types.py` (backend) garde le miroir. Conversion implicite marquee `~` sur le lien (`FlowEdge`).
  * `ParamsPane.tsx` (libelle, bypass, un `ParamWidget` par port), `FlowParams.tsx` (libelle, description, `run_policy`,
    interface entrees / sorties, variables), `NodeWriterDialog.tsx` (node Python d'equipe, `POST /flows/nodes`).
  * `IssuesPanel.tsx` : `POST /flows/validate` 300 ms apres la derniere edition, erreurs puis avertissements, clic = zoom +
    clignotement, "Corriger" = `fixes.ts` (un reducer par `fix.kind`, une entree undo). Pastille par node, anneau rouge sur
    le port fautif, lien fautif en `--err`, badge "invalide" et compteur dans la TopBar ; backend injoignable = Run bloque.
  * `GroupBox.tsx` (Ctrl+G, boite derriere ses nodes, la glisser deplace les nodes, double clic = renommer) et `NoteNode.tsx`
    (N a la souris). Ids xyflow prefixes `group:` / `note:` (`NetworkPane`).
  * Enregistrer (`FlowEditor.saveDoc`) : Ctrl+S, Enregistrer et incrementer, quitter (changer de flow, fermer la fenetre :
    `components/shared/closeGuard.ts` lu par `TitleBar`). Nodes `!` ajoutes depuis le dernier enregistrement (`destructive.ts`,
    miroir de `flag_on`) = `DestructiveDialog.tsx` + `SlideToConfirm`, ids envoyes en `confirmed_destructive`. 409 de revision
    = `ConflictDialog.tsx` (voir sa version : le document reste en brouillon local ; enregistrer par-dessus). Brouillon
    `localStorage` `flux.flow_draft.<portee>.<nom>`, propose a la reouverture. `VersionsDialog.tsx` (Fichier > Versions, tag
    de version) : diff par version, Voir (lecture seule, bandeau "Lecture vNNN"), Revenir (cree v(max+1)), historique.
  * L'ancien editeur (`/action-graph-legacy`, `ActionGraph.tsx`) n'est plus dans la TopBar : lien "Ancien editeur" dans
    Parametres avances, carte Actions (YAML), jusqu'a P8.
  * P5 : `ActivationDialog.tsx` (bouton Activer de la TopBar : 0 erreur, avertissements coches, essai a blanc de `current`
    lance depuis le dialogue ; `SlideToConfirm` si un node `!`), tags "actif vN" / "vM non activee".
  * P6a : nodes DCC livres en sous-flows verrouilles (`spec.subflow`) : cadenas (livre) ou icone equipe (copie), double clic
    ou Entree = entrer, fil d'Ariane dans la TopBar, U = remonter ; `DccBanner.tsx` (Deverrouiller = copie d'equipe,
    Revenir au defaut apres `SlideToConfirm`). Les coeurs `spec.internal` ne sont ni dans Tab ni dans le Shelf.
    `icons.ts` liste toutes les icones du registre.
  * P6c : bouton Bridges de la TopBar -> `BridgesDialog.tsx` (bridges d'extension : erreurs, exe, etat d'installation,
    Installer / Mettre a jour / Desinstaller sur ce poste, conflit -> "Remplacer (sauvegarde)", Creer les nodes = Team TD).

## Pages TOOL (`tool_pages/`, chantier Flows P7, ADR 0066)

* `links.ts` : fonctions pures (pas de runner front : verifiees a la lecture et en live) : `renamedInputs` (parametres
  d'interface renommes entre l'enregistre et l'envoye, l'editeur de flows propose ensuite de suivre dans les pages),
  `widgetsOf`, `initialValue`, `coerce`, `runValues` (champs lies au flow du bouton), `blockedWidgets` (raison de grisage
  depuis les `P_*`, `P_FLOW_INACTIVE` grise aussi), `ago`, `seconds`.
* `PageRenderer.tsx` : rendu d'une page (dossiers `plain | tabs | collapsible`, lignes en grille a poids `w`, champs via
  `ParamWidget`, vrais `<button>`). Clic = `POST /flows/{flow}/run {event: button_id, values}` (version active) ; etat du
  dernier run par bouton (`GET /flows/runs?flow&event&limit=1`, rafraichi sur `run_finished` du WS) ; en cours = "Stop"
  (annule le run) ; `remember: user` dans les donnees utilisateur (`flux.pages.remember`) ; `preview` (editeur) : boutons
  inertes ("lancerait ..."), clic = selection. Widgets de donnees via `renderData`.
* `DataWidgets.tsx` (ADR 0066 n°2) : `feed` (fil + saisie, Entree envoie, canaux par `group_by`, supprimer son message),
  `table` (`columns`, `editable` : double clic = formulaire), `cards` (kanban par `group_by`, glisser entre colonnes),
  `calendar` (mois, champ `date` / `end`, double clic sur un jour = ajouter), `members` (comptes FLUX), et une source
  `{flow, output}` = sortie du dernier run ok (`outputs` du record de run). Donnees par `hooks/usePages.ts`
  (`usePageData` : etag toutes les 5 s tant que monte + WS `page_data` ; `usePageList`).
* `BoardWidget.tsx` (ADR 0066 n°1) : board facon Miro dans sa ligne : notes, cartes, images (copiees par le backend),
  liens, couleurs a plat, pan (glisser le fond), zoom a la molette, "Tout voir", Suppr. Vue par spectateur, jamais ecrite.
* `ToolPage.tsx` (route `/tool?page=<id>`, detachable) : rail des pages par portee (masque avec une seule page, recherche
  au-dela de 8), derniere page par artiste (`flux.tool.last`), en-tete (icone `icons.ts`, tag de portee, "Editer" et
  "Nouvelle" pour un Team TD), relecture sur WS `page_changed` / `activation` / `flow_changed`. Entree `TOOL` du groupe
  ASSETS (`Sidebar.tsx`) : visible des qu'une page existe, ou pour un Team TD (sinon personne ne peut creer la premiere).
  Dette : chaque `useFlowsWs` ouvre sa propre socket (sidebar, page, widgets) ; un hub partage viendra si ca pese.
* `PageBuilder.tsx` (route `/tool/:id/edit?scope=`, `new` = dialogue de creation : libelle, id propose, portee, depart
  vide / modele `shipped/pages/` / copie d'une page) : 4 colonnes Palette (Formulaire, Decor, Donnees ; un widget de
  donnees cree sa collection par defaut s'il n'y en a pas : un Fil marche du premier coup) | Arbre (dossiers > lignes >
  widgets, pastille ok / erreur, monter / descendre / gauche / droite / sortir de la ligne, collections, Problemes) |
  Proprietes (`PageProps.tsx` : id avec renommage propage pour un bouton lie, "Au clic" = `POST /flows/pages/link_button`
  apres confirmation de la nouvelle version, "Lie a" filtre par type, props par kind, champs des collections) | Apercu
  (`PageRenderer preview`). Store generique de l'editeur de flows (undo / redo), validation en direct 300 ms, Ctrl+S,
  Fermer = enregistrer puis quitter. Reducers purs dans `builder.ts`. Pas de glisser-deposer dans l'arbre (fleches) :
  a ajouter si the maintainer le demande.
* `GeneratedPublishPanel.tsx` (04 §7) : panneau Publisher d'un logiciel ajoute en extension (P6c) : `Publisher.tsx` ajoute
  les bridges valides au `SoftwareSelector` (`extra`) et, pour eux seulement, remplace le Composer et la barre du bas
  par ce panneau (une seule branche). Champs = interface du flow `publish_<soft>` (`GET /flows/pages/publish_panel/<soft>`),
  Publier = `event: publish_request` (flow actif). Destination et note de publish : en P8 (ils dependent du Composer).
