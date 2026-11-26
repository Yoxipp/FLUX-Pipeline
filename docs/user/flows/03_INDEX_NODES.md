# Flows : index des nodes

Les 88 nodes disponibles au 2026-10-24, par famille. Chaque section est aussi affichee par le bouton (i) du node
dans l'editeur.

<!-- Ecriture : un titre `### <type> : <Label>` par node, regles dans README.md (lu par nodeDoc.tsx et flows_doc.py). -->

Conventions : `exec` / `then` = liens d'ordre ; une entree marquee obligatoire doit etre reliee ou remplie ;
`!` = destructif (efface ou ecrase), demande une confirmation. Tout node a effet a une sortie `on_error` : la relier
pour gerer l'erreur soi-meme au lieu d'arreter le run. Les nodes a venir sont dans [02_DISPO_ET_A_VENIR.md](02_DISPO_ET_A_VENIR.md).

## Evenements

Le point de depart d'un flow. Pas d'entree exec ; un flow peut en avoir plusieurs.

### event.page_inputs : InputsPageReader

Part quand on clique un bouton d'une page TOOL (ADR 0068). On choisit la page dans `page` : le node montre **une
sortie par bouton** (avec son libelle) et **une sortie par champ** de la page. On relie chaque bouton a ce qu'il doit
lancer : deux boutons peuvent lancer deux branches differentes du meme flow. Le flow doit etre **actif** pour qu'un
clic le lance ; un meme bouton lance tous les flows actifs qui l'ecoutent.

Lance autrement (Horaire, Run de l'editeur, FlowCall), les sorties des champs donnent les **valeurs par defaut de la
page**. Si un bouton ou un champ relie disparait de la page, le flow l'affiche en avertissement : selectionne le node
pour rafraichir ses ports.

* Sorties : une par bouton (exec : la relier a l'`exec` du node a lancer, c'est elle qui part au clic), une par champ
  (son type, a brancher seulement si un node en a besoin), `values` (dict des champs).
* Reglage : `page`, la page TOOL lue.

Exemple : page Daily render (champ Dossier, bouton Lancer maintenant) : `InputsPageReader (page: daily_render)`
`Lancer maintenant` > `FindPublishes` > `Copy`, et `Dossier` > `PathJoin`.

### event.button : Button

Ancien depart de page, remplace par `InputsPageReader` (ADR 0068). Retire du Shelf ; un ancien flow qui l'a encore ne
part plus que par Run dans l'editeur.

* Sorties : `then`, `values` (dict des entrees de l'interface).
* Reglage : `button_id`.

Exemple : un ancien flow `Button (button_id: daily_render)` > `FindPublishes` : remplace `Button` par `InputsPageReader`.

### event.manual : Manual

Depart a la main : Run dans l'editeur, ou appel par un autre flow avec `FlowCall` (c'est par lui que demarre un
sous-flow). A utiliser pour tout flow d'outillage ou de test.

* Sorties : `then`, `values` (les entrees de l'interface).

Exemple : un sous-flow `archive_old_versions` commence par `Manual` ; un autre flow l'appelle avec `FlowCall`.

### event.schedule : Schedule

Part a heure fixe (heure du poste qui execute), tous les jours ou certains jours. Flow d'equipe ou de projet : un
seul poste FLUX l'execute (celui qui tient le verrou) ; flow perso : ton poste. Si FLUX etait ferme a l'heure, le
creneau est rattrape une fois au prochain lancement (`missed: catch_up_once`) ou oublie (`skip`). Le run prend les
valeurs par defaut de l'interface du flow.

* Sorties : `then`, `fired_at` (creneau, ISO), `missed` (vrai pour un rattrapage).
* Reglages : `days` (`daily` ou `mon,tue,wed,thu,fri,sat,sun`), `time` (HH:MM), `missed`.

Exemple : `Schedule (days: mon,tue,wed,thu,fri, time: 08:00)` > `FindPublishes` > `Copy` vers le dossier des dailies.

### event.new_file : NewFile

Part pour chaque nouveau fichier qui arrive dans un dossier. Le premier scan sert de base : les fichiers deja la ne
declenchent rien. Les fichiers vus sont gardes, ceux arrives pendant que FLUX etait ferme partent au lancement
suivant. Par defaut un fichier part quand sa taille est la meme sur deux scans (copie finie).

* Entree : `folder` (dossier surveille).
* Sorties : `then`, `path`, `name`, `dir`.
* Reglages : `pattern` (motif, defaut `*`), `recursive`, `every_s` (min 5, defaut 30 ; sous 10 s : avertissement de
  charge reseau), `wait_stable`.

Exemple : `NewFile (folder: $FLUX/DROP/refs, pattern: *.jpg *.png)` > `ConvertImage` vers `$FLUX/REFS`.

### event.when : When

Part quand une condition passe de faux a vrai. La condition est calculee par des nodes purs (Exists, Compare, And...)
toutes les `every_s` secondes ; la premiere evaluation sert de base ; une erreur est notee sans declencher.

* Entree : `condition` (booleen).
* Sortie : `then`.
* Reglages : `every_s` (min 5, defaut 30).

Exemple : `Exists ($FLUX/PROJ/render/shot010/done.txt)` > `When` > `Notify` "shot010 rendu".

### event.on_publish : OnPublish

Part apres chaque publish reussi sur ce poste, quel que soit le logiciel (le flow tourne chez l'artiste qui publie).
Mode, task, asset, sequence et plan sont lus dans le nom FLUX du fichier ; type et version dans le nom et
l'extension ; le logiciel est envoye par le Publisher (un `.abc` publie depuis Maya compte pour `maya` ; sans lui,
deduit de l'extension, et un export USD leger n'en a pas). Les filtres choisissent les
publishs qui declenchent le flow, vide = tout ; un publish filtre ne cree aucun run (rien dans l'historique). Pour
un filtre plus complexe, relie `infos` a PublishInfos puis a un If. Le reglage avance "Flows apres publish"
(`FLUX_FLOWS_HOOKS`) coupe cet evenement.

* Sorties : `then`, `publish` (le publish, lisible avec PublishFields), `project`, `infos` (a eclater avec
  PublishInfos).
* Reglages : `mode` (any, asset, shot), `task`, `class`, `asset`, `seq`, `shot`, `project`, `soft`, `type`, `name`
  (motifs, vide = tous ; `type: capture` = images et videos).

Exemple : `OnPublish (mode: asset, task: RIG)` > `Notify` : prevenir seulement quand un rig d'asset est publie.

### event.scene_opened : SceneOpened

Part quand une autre scene est ouverte dans Maya, Houdini ou Nuke sur ce poste. FLUX interroge chaque instance ouverte
toutes les `every_s` secondes (rien a installer dans le logiciel) ; les scenes deja ouvertes au lancement ne
declenchent rien. Un script du logiciel peut aussi l'envoyer : `POST /flows/events/scene_opened`.

* Sorties : `then`, `scene`, `soft`, `session` (instance : port et pid ; servira aux nodes DCC).
* Reglages : `soft` (maya, houdini, nuke), `every_s` (min 2, defaut 5).

Exemple : `SceneOpened (soft: maya)` > `Notify` "pense a mettre a jour tes references".

### event.publish_request : PublishRequest

Depart des flows de publish par logiciel (`publish_maya`, `publish_houdini`) : le Publisher du logiciel envoie son
formulaire, ses valeurs remplissent l'interface du flow. D'ici la bascule du Publisher (P8), on lance ces flows avec Run.

La sortie `infos` donne ce que le nom FLUX du formulaire dit du publish (mode, task, asset ou sequence et plan,
instance, logiciel, projet, artiste) : relie-la a PublishInfos pour lire chaque champ (la version est vide avant le
publish).

* Sorties : `then`, `values` (le formulaire), `soft`, `infos`, puis une sortie par champ du formulaire.
* Reglage : `soft`.

Exemple : `PublishRequest (soft: maya)` > `MayaInstance (live_connect_only)` > `mayPublish (name: ${name})`.

### event.page_data : PageData

Part pour chaque enregistrement ajoute (ou modifie) dans une collection d'une page TOOL (un message du fil, une carte
du board, une date du calendrier), quel que soit le poste qui l'a ecrit : les journaux de tous les auteurs sont relus
quand ils bougent. La premiere lecture sert de base. Un flow d'equipe sur une collection rangee par projet surveille
chaque projet. Les runs partent l'un apres l'autre (aucun message perdu), 20 au plus par lecture.

* Sorties : `then`, `record` (l'enregistrement : ses champs, `_by`, `_at`), `user` (qui l'a ecrit), `project`.
* Reglages : `page`, `collection`, `on` (`added`, `changed` ou `any`, defaut `added`), `every_s` (min 5, defaut 10).

Exemple : `PageData (page: team, collection: messages)` > `Notify` "nouveau message de {user}".

### event.team_command : TeamCommand

Part quand un artiste tape `/nom` dans le chat de la page Team (ADR 0081), par exemple `/zip "\\serveur\projet\SEQ010"`.
Le message est poste dans le canal (l'equipe le voit), puis chaque flow actif qui declare ce nom (perso de l'artiste,
equipe, projet) tourne **sur le poste de l'artiste** : ses droits, ses chemins, pas d'hebergeur. Il faut voir le canal.
Un flow perso = une commande pour soi. Un run qui n'aboutit pas repond tout seul dans le fil (message FLUX). Lance
par Run dans l'editeur, le node donne des valeurs d'exemple.

* Sorties : `then`, `arg` (premier argument, entre guillemets s'il a des espaces), `path` (le meme en chemin), `dir`
  (le meme si c'est un dossier existant, sinon vide), `parent` (dossier qui le contient), `args` (tous), `text` (texte
  brut apres la commande), `user`, `channel`, `values` (tout en un, pour Template).
* Reglages : `name` (sans `/`, minuscules, chiffres, `-` et `_`, 2 a 32), `help` (montre pendant la saisie),
  `channels` (motifs separes par espaces ou virgules, vide = tous), `confirm` (le chat demande confirmation).

Exemple : `TeamCommand (name: zip)` > `ZipFolder (folder: dir, dest: parent)` > `TeamReply` "Zip pret : {arg}.zip"
(flow livre `example_team_zip`).

## Data

Des valeurs : constantes, parametres du flow, variables, lectures de fichiers. Pas de port exec (sauf SetVariable) :
calcules quand un node les lit.

### data.value : Value

Une valeur fixe tapee dans le node : texte, nombre, booleen, liste, dictionnaire ou motif. Le type choisi fixe le type
de la sortie, donc ce qu'on peut y brancher.

* Sortie : `value`.
* Reglages : `type` (str, int, float, bool, list, dict, pattern), `value`.

Exemple : `Value (type: int, value: 3)` vers `max_items` d'un ForEach pour ne traiter que 3 elements pendant un test.

### data.get_variable : GetVariable

Lit une variable du flow (declaree dans Params du flow > Variables). Une variable vit le temps d'un run ; elle vaut sa
valeur initiale tant qu'aucun SetVariable ne l'a ecrite.

* Sortie : `value`.
* Reglage : `name`, la variable.

Exemple : compter les fichiers copies : `GetVariable (copied)` > `Math add 1` > `SetVariable (copied)` dans la boucle.

### data.set_variable : SetVariable

Ecrit une variable du flow, convertie dans le type declare. C'est un node exec : l'ecriture se fait a son tour dans la
chaine, ce qui garantit l'ordre.

* Entrees : `exec`, `value`. Sorties : `then`, `on_error`, `value` (la valeur ecrite).
* Reglage : `name`.

Exemple : garder le dernier publish trouve dans une boucle pour le notifier apres la fin.

### data.flow_input : FlowInput

Un parametre que l'utilisateur remplit avant de lancer le flow : formulaire du Run, champ d'une page TOOL, ou valeur
passee par le `FlowCall` qui appelle ce flow. Le node donne cette valeur au graph (sinon le defaut de l'interface).
Son `id` (affiche en gros sur le node) se choisit dans un menu : les entrees declarees dans le panneau du flow (clic dans
le vide). Voir "Entrees et sorties d'un flow" dans la vue globale.

* Sortie : `value`.
* Reglage : `id`, l'entree de l'interface lue.

Exemple : interface `dest_folder` (dir, defaut `$FLUX/DAILY`) > `FlowInput (dest_folder)` > `PathJoin base`.

### data.path : Path

Un chemin fixe. Accepte `$FLUX/...` (portable entre postes), `{token}` et `${variable}`. Un chemin relatif part du
dossier du projet (ou reste tel quel avec `relative_to: absolute`). C'est une constante : `value` et `relative_to` se
saisissent, ils ne recoivent pas de lien.

* Sorties : `path` (le chemin), `dir` (le meme, type dossier).
* Reglages : `value`, `relative_to` (project ou absolute).

Exemple : `Path (value: {project_path}/ARCHIVE)` comme dossier a lister par ListFiles.

### data.token_path : TokenPath

Compose un chemin du projet avec les tokens, comme le Publisher : choisis la classe, le nom, le type (asset) ou la
sequence, le plan et la task (shot), le node donne le dossier du publish. `level: last` donne le fichier LAST de ce
dossier (le layout est plat : `<base>_LAST.<ext>`, choisis le format avec `ext`), `level: entity` le dossier de
l'asset ou du plan. Les menus proposent les tokens du projet ; chaque reglage peut aussi etre relie. Lecture : tourne
aussi en essai a blanc.

Les entrees suivent le `mode` : en asset le node montre classe, nom et type ; en shot, sequence, plan et task. Les
autres sont masquees (gardees dans le fichier : un ancien flow tourne toujours). Un lien reste visible sur une entree
masquee, avec l'avertissement `W_PORT_HIDDEN` : retire le lien ou change le mode. `project` est optionnel : vide, c'est
le projet du flow.

* Sorties : `path`, `dir` (le meme si c'est un dossier existant, sinon vide), `exists`.
* Reglages : `mode` (asset, shot), `project` (vide : celui du flow), `class`, `name`, `type` (asset), `seq`, `shot`,
  `task` (shot), `instance` (null par defaut), `level` (publish, last, entity), `ext` (format du LAST, level last).

Exemple : `TokenPath (asset, CHAR, HERO, MOD)` > `path` vers `ListFiles.folder` pour lister les publishs du modeling.

### data.publish_infos : PublishInfos

Eclate les infos d'un publish en champs a relier : `mode` (asset ou shot), `task`, `class`, `asset` (asset), `seq`,
`shot` (shot), `instance`, `soft`, `project`, `user`, `version`, `file_type`, `path`. Un champ qui ne s'applique pas
est vide (un plan n'a pas d'asset). Le meme node sert apres PublishRequest (avant le publish) et apres OnPublish (apres).
Accepte aussi un publish (FindPublishes) ou un nom de fichier. Lecture.

* Entree : `infos` (sortie `infos` de PublishRequest ou OnPublish).
* Sorties : les champs ci-dessus.

Exemple : `OnPublish` > `infos` > `PublishInfos` > `task` vers `Compare (== RIG)` > `If` > `Notify`.

### data.python_value : PythonValue

Lit une variable d'un fichier `.py` sans l'executer (lecture du texte : nombres, textes, listes, dicts seulement).
Sert a reutiliser une liste ou un reglage deja ecrit dans un script.

* Sortie : `value`.
* Reglages : `file` (le .py), `name` (la variable du module).

Exemple : lire `DEPARTMENTS = ["mod", "rig", "surf"]` d'un script d'outil pour boucler dessus avec ForEach.

### data.json_value : JsonValue

Lit une valeur dans un JSON par son chemin pointe `a.b[0].c`, depuis un fichier ou depuis un dict relie. `found` dit
si la cle existe ; sinon la sortie vaut `default`.

* Entree : `json` (dict, prioritaire sur le fichier). Sorties : `value`, `found`.
* Reglages : `file`, `key`, `default`.

Exemple : `JsonValue (file: {project_path}/production.json, key: settings.fps, default: 24)` > `Template`.

### data.template : Template

Compose un texte a partir d'un modele : tokens du run (`{project}`, `{user}`, `{date:%Y%m%d}`), variables `${nom}`,
`$FLUX`, et les cles du dict relie a `values` (`{name}`, `{version}`).

* Entree : `values` (dict). Sortie : `text`.
* Reglage : `text`, le modele.

Exemple : `Template ("{shot}_daily_{date:%Y%m%d}.mov")` pour nommer un fichier de livraison.

### data.context : Context

Les valeurs du run en cours : projet et son dossier, asset, sequence, plan, artiste, date, heure, nom du flow. Vides si
le depart ne les donne pas.

* Sorties : `project`, `project_path`, `asset`, `seq`, `shot`, `user`, `date`, `time`, `flow`.

Exemple : `Context.user` vers `Ping.user` pour prevenir l'artiste qui a lance le flow.

## Logique

Tester et choisir. If et Switch choisissent la branche exec ; les autres calculent un booleen ou une valeur.

### logic.if : If

Une seule branche s'execute : `then` si la condition est vraie, `else` sinon. Les deux branches peuvent se rejoindre
plus loin sur la meme entree exec.

* Entrees : `exec`, `condition` (bool). Sorties : `then`, `else`, `on_error`.

Exemple : `Exists (dossier de sortie)` > `If` : `else` > `MakeDir`, puis les deux branches vers `Copy`.

### logic.switch : Switch

Prend la sortie du cas egal a la valeur (egalite exacte, pas de motif), sinon `default`. Jusqu'a 8 cas, une sortie
`case_N` par valeur de la liste `cases`.

* Entrees : `exec`, `value`. Sorties : `case_0` a `case_7`, `default`, `on_error`.
* Reglages : `cases` (liste), `type` (str, int, float).

Exemple : `Switch (cases: [mod, rig, surf])` sur le departement : chaque branche publie a sa facon.

### logic.compare : Compare

Compare `a` et `b` : egal, different, plus petit, plus grand, contient, commence par, finit par, ou `matches` (a contre
le motif b, par exemple `*.abc ^*_tmp*`).

* Entrees : `a`, `b`. Sortie : `result` (bool).
* Reglage : `op` (eq, ne, lt, le, gt, ge, contains, startswith, endswith, matches).

Exemple : `Compare (op: gt)` entre `ListLength` et `Value 0` > `If` : ne notifier que s'il y a des fichiers.

### logic.and : And

Vrai si toutes les entrees reliees sont vraies (2 a 4 entrees).

* Entrees : `a`, `b`, `c`, `d` (c et d optionnelles). Sortie : `result`.

Exemple : `And (Exists source, Not Exists dest)` > `If` pour copier seulement ce qui manque.

### logic.or : Or

Vrai si au moins une entree reliee est vraie (2 a 4 entrees).

* Entrees : `a`, `b`, `c`, `d`. Sortie : `result`.

Exemple : `Or (Compare ext == .ma, Compare ext == .mb)` pour reconnaitre une scene Maya.

### logic.not : Not

Le contraire du booleen.

* Entree : `value`. Sortie : `result`.

Exemple : `Exists` > `Not` > `If` pour creer un dossier seulement s'il manque.

### logic.is_empty : IsEmpty

Vrai si la valeur est vide : texte vide, liste ou dict vide, rien.

* Entree : `value`. Sortie : `result`.

Exemple : `FindPublishes.items` > `IsEmpty` > `If` : `then` > `Notify ("Rien publie aujourd'hui")`.

### logic.exists : Exists

Le fichier ou le dossier existe-t-il ? `is_dir` dit si c'est un dossier.

* Entree : `path`. Sorties : `result`, `is_dir`.

Exemple : verifier qu'un `.tx` existe deja avant de lancer ConformTexture.

### logic.select : Select

Choisit une valeur, pas une branche : `a` si la condition est vraie, sinon `b`. Equivalent de `a if condition else b`.

* Entrees : `condition`, `a`, `b`. Sortie : `value`.

Exemple : dossier de sortie = `Select (case "en local", dossier perso, dossier du projet)`.

## Operateurs

Boucles, ordre, calculs sur nombres, textes, listes, chemins et dates.

### operator.foreach_begin : ForEachBegin

Ouvre une boucle : le corps (les nodes relies entre Begin et End) tourne une fois par element de la liste. `item` est
l'element du tour, `index` son rang. Liste vide : le corps est saute, la suite part du `done` de ForEachEnd.

`mode: dispatch` : le corps tourne pareil, mais chaque Submit du corps ajoute ses taches a un seul job, envoye au
dispatcher a ForEachEnd (sa sortie `job_id`).

* Entrees : `exec`, `list`. Sorties : `loop` (vers le corps), `item`, `index`, `count`, `on_error`.
* Reglages : `max_items` (plafond, 10000), `mode` (sequential, dispatch).

Exemple : `FindPublishes.items` > `ForEachBegin` > `PublishFields` + `Copy` > `ForEachEnd`.

### operator.foreach_end : ForEachEnd

Ferme la boucle de son ForEachBegin (apparie par l'editeur). A chaque tour, garde la valeur reliee a `collect` ; a la
fin, `results` est la liste de ces valeurs et le flux repart de `done`.

* Entrees : `exec`, `collect`. Sorties : `done`, `results`, `job_id` (mode dispatch : le job envoye), `on_error`.
* Reglage : `begin` (pose par l'editeur).

Exemple : `collect` <- `Copy.path` : `results` = liste des fichiers copies, envoyee a `StrJoin` puis `Notify`.

### operator.sequence : Sequence

Execute ses sorties dans l'ordre, l'une apres l'autre. Une sortie exec n'acceptant qu'un lien, c'est le node pour
enchainer plusieurs suites independantes depuis un meme point.

* Entree : `exec`. Sorties : `then_0` a `then_7`, `on_error`.
* Reglage : `count` (1 a 8).

Exemple : apres un publish, `Sequence` : `then_0` > `GenerateProxy`, `then_1` > `UsdCheck`, `then_2` > `Notify`.

### operator.for_begin : ForBegin

Boucle sur des nombres : le corps tourne pour chaque index de `start` a `end` inclus, avec un pas (negatif pour
descendre). Plafonnee par `max_iterations`.

* Entrees : `exec`, `start`, `end`, `step`. Sorties : `loop`, `index`, `on_error`.
* Reglages : `max_iterations` (1000), `mode` (reserve).

Exemple : `ForBegin (1 a 10)` > `StrFormat 03d` > `Template "SH{index}"` pour preparer 10 noms de plans.

### operator.for_end : ForEnd

Ferme la boucle de son ForBegin ; la suite part de `done` apres le dernier tour.

* Entree : `exec`. Sorties : `done`, `on_error`.
* Reglage : `begin` (pose par l'editeur).

Exemple : fin du corps d'une boucle de 1 a 10, puis `done` > `Notify ("10 dossiers crees")`.

### operator.while_begin : WhileBegin

Le corps tourne tant que la condition est vraie ; elle est relue apres chaque tour. Atteindre `max_iterations` est une
erreur : jamais de boucle infinie.

* Entrees : `exec`, `condition`. Sorties : `loop`, `index`, `on_error`.
* Reglage : `max_iterations` (1000).

Exemple : attendre qu'un rendu ecrive son fichier : `WhileBegin (Not Exists)` > `Wait 10 s` > `WhileEnd`.

### operator.while_end : WhileEnd

Ferme la boucle de son WhileBegin ; la suite part de `done` quand la condition devient fausse.

* Entree : `exec`. Sorties : `done`, `on_error`.
* Reglage : `begin` (pose par l'editeur).

Exemple : `done` > `Notify ("Le rendu est arrive")`.

### operator.break_loop : BreakLoop

Sort tout de suite de la boucle qui l'entoure : la suite part du `done` du End de cette boucle.

* Entree : `exec`.

Exemple : dans un ForEach, `If (fichier trouve)` > `BreakLoop` pour s'arreter au premier resultat.

### operator.math : Math

Calcule `a op b` (add, sub, mul, div, mod, min, max) ou `op a` (round, floor, ceil, abs). `as_int` donne le resultat
en entier.

* Entrees : `a`, `b`. Sorties : `result` (float), `as_int`.
* Reglage : `op`.

Exemple : `Math (sub)` entre deux `index` pour un nombre d'images, ou `Math add 1` pour un compteur.

### operator.null : Null

Laisse passer la valeur telle quelle. Sert a ranger le graph : un point de rassemblement d'ou partent plusieurs liens.

* Entree : `value`. Sortie : `value`.

Exemple : `Null` nomme `OUT_FOLDER` relie a tous les nodes qui ecrivent dans le meme dossier.

### operator.str_join : StrJoin

Joint une liste de textes avec un separateur.

* Entree : `items`. Sortie : `text`.
* Reglage : `sep`.

Exemple : `ForEachEnd.results` > `StrJoin (sep: ", ")` > `Notify` : "chair, table, lamp copies".

### operator.str_split : StrSplit

Coupe un texte a chaque separateur (vide = aux espaces).

* Entree : `text`. Sortie : `items`.
* Reglage : `sep`.

Exemple : `StrSplit (sep: _)` sur `chair_mod_v003` puis `ListGet 0` pour retrouver le nom de l'asset.

### operator.str_replace : StrReplace

Remplace `find` par `with` dans le texte ; `regex` pour une expression reguliere.

* Entree : `text`. Sortie : `text`.
* Reglages : `find`, `with`, `regex`.

Exemple : `StrReplace (find: _WIP, with: "")` pour nettoyer un nom avant de publier.

### operator.str_case : StrCase

Majuscules, minuscules, Titre, ou espaces retires au debut et a la fin.

* Entree : `text`. Sortie : `text`.
* Reglage : `op` (upper, lower, title, strip).

Exemple : `StrCase (upper)` sur le nom d'artiste pour le dossier `ARCHIVE/<date>_<ARTISTE>`.

### operator.str_format : StrFormat

Met une valeur en forme avec un format Python : `03d` donne `007`, `.2f` donne `3.14`.

* Entree : `value`. Sortie : `text`.
* Reglage : `spec`.

Exemple : `index` d'un ForBegin > `StrFormat 03d` > `Template "v{version}"` pour `v001`, `v002`...

### operator.list_length : ListLength

Nombre d'elements d'une liste.

* Entree : `list`. Sortie : `length`.

Exemple : `ListFiles.files` > `ListLength` > `Template "{n} fichiers a traiter"`.

### operator.list_get : ListGet

L'element a un rang donne (0 = premier, -1 = dernier). Si le rang n'existe pas : `found` faux et `default`.

* Entrees : `list`, `index`. Sorties : `item`, `found`.
* Reglage : `default`.

Exemple : `ListSort (date)` > `ListGet -1` pour le fichier le plus recent.

### operator.list_filter : ListFilter

Garde les elements qui passent un motif facon Houdini, sur le nom ou sur le chemin entier ; les autres sortent par
`rejected`. Sur le chemin (`match_on: path`), `*` s'arrete a chaque `/` : pour traverser les dossiers, ecris `**`
(`** ^**/ARCHIVE/**` garde tout sauf ce qui est sous un dossier ARCHIVE).

* Entree : `list`. Sorties : `items`, `rejected`.
* Reglages : `pattern`, `match_on` (name ou path).

Exemple : `ListFilter (*.exr ^*_denoise*)` pour garder les images de rendu sans les passes debruitees.

### operator.list_sort : ListSort

Trie une liste : par nom, par date ou taille (fichiers), ou en ordre naturel (`v2` avant `v10`).

* Entree : `list`. Sortie : `items`.
* Reglages : `key` (name, date, size, natural), `reverse`.

Exemple : `ListSort (natural, reverse)` > `ListGet 0` pour la version la plus haute.

### operator.list_unique : ListUnique

Retire les doublons en gardant l'ordre de premiere apparition.

* Entree : `list`. Sortie : `items`.

Exemple : liste des artistes ayant publie aujourd'hui, sans repetition, avant de les pinguer.

### operator.list_append : ListAppend

Renvoie une nouvelle liste avec l'element ajoute a la fin (la liste d'origine ne change pas).

* Entrees : `list`, `item`. Sortie : `items`.

Exemple : ajouter le dossier `LAST` a la liste des dossiers a zipper.

### operator.path_join : PathJoin

Joint un dossier de depart et jusqu'a 3 morceaux relatifs. `dir` donne le meme chemin comme dossier, pour un
node qui attend un dossier (ZipFolder, ListFiles, NewFile).

* Entrees : `base`, `a`, `b`, `c`. Sorties : `path`, `dir`.

Exemple : `PathJoin (FlowInput dest_folder, DateNow.date)` > `MakeDir` : un dossier par jour.

### operator.path_split : PathSplit

Decoupe un chemin : dossier parent, nom complet, nom sans extension, extension.

* Entree : `path`. Sorties : `parent`, `name`, `stem`, `ext`.

Exemple : `PathSplit.stem` > `Template "{stem}_proxy.usd"` pour nommer un fichier a cote de sa source.

### operator.path_relative : PathRelative

Chemin relatif a un dossier de reference.

* Entrees : `path`, `base`. Sortie : `relative`.

Exemple : ecrire dans un rapport les chemins relatifs au projet plutot que des chemins absolus de poste.

### operator.path_flux_token : PathFluxToken

Passe d'un chemin absolu a la forme portable `$FLUX/...`, et inversement. La forme `$FLUX` marche sur tous les postes.

* Entree : `value`. Sorties : `token` (forme `$FLUX/...`), `path` (chemin absolu).

Exemple : `PathFluxToken.token` > `WriteJson` pour stocker un chemin lisible depuis n'importe quel poste.

### operator.date_now : DateNow

Date et heure au moment ou le node est lu : en ISO, en date `AAAA-MM-JJ` et en secondes.

* Sorties : `iso`, `date`, `epoch`.

Exemple : `DateNow.date` > `PathJoin` pour un dossier de dailies date du jour.

### operator.date_format : DateFormat

Met une date ISO en forme avec un format strftime (`%Y%m%d`, `%d/%m %H:%M`...).

* Entree : `iso`. Sortie : `text`.
* Reglage : `fmt`.

Exemple : `DateNow.iso` > `DateFormat (%Y%m%d)` > nom de zip `livraison_20261023.zip`.

### operator.date_add : DateAdd

Ajoute (ou retire, en negatif) des jours et des heures a une date.

* Entree : `iso`. Sortie : `iso`.
* Reglages : `days`, `hours`.

Exemple : `DateAdd (days: -7)` > `FindPublishes date` pour lister les publishs de la semaine passee.

## Actions

Agir sur les fichiers et le poste. Nodes a effet : simules pendant un essai a blanc.

### action.run : Run

Ouvre un fichier dans son logiciel (Maya, Houdini, Nuke...), detache de FLUX : le flow continue sans attendre.
`soft: auto` choisit le logiciel d'apres l'extension.

* Entrees : `exec`, `path`. Sorties : `then`, `on_error`, `launched`.
* Reglage : `soft` (auto, maya, houdini, nuke, painter...).

Exemple : `ResolvePath (LAST de la scene de layout)` > `Run` : bouton "ouvrir le layout du plan".

### action.rename : Rename

Renomme un fichier ou un dossier sans le deplacer. N'ecrase jamais : erreur si le nouveau nom existe deja.

* Entrees : `exec`, `path`, `new_name` (nom seul, sans dossier). Sorties : `then`, `on_error`, `path` (nouveau chemin).

Exemple : dans un ForEach, `StrReplace (_WIP -> "")` > `Rename` pour nettoyer les noms d'un dossier.

### action.move : Move

Deplace un fichier ou un dossier ; une destination qui est un dossier existant recoit l'element dedans. N'ecrase jamais.

* Entrees : `exec`, `source`, `dest`. Sorties : `then`, `on_error`, `path`.

Exemple : ranger les captures d'ecran posees sur le bureau dans `{project_path}/REF/` avec `ListFiles` + ForEach.

### action.copy : Copy

Copie un fichier ou un dossier. Avec `dest_is: auto`, une destination qui est un dossier existant ou qui finit par
`/` recoit la copie dedans (avec le nom de la source) ; `folder` copie toujours dedans, `file` prend `dest` comme
chemin exact de la copie. Les dossiers manquants sont crees (`make_dirs`, actif par defaut ; coupe, un dossier absent
est une erreur). N'ecrase rien, sauf avec `overwrite` (alors destructif `!`).

* Entrees : `exec`, `source`, `dest`. Sorties : `then`, `on_error`, `path` (la copie).
* Reglages : `overwrite`, `dest_is` (auto, folder, file), `make_dirs`.

Exemple : `PublishFields.path` > `Copy (dest: dossier des dailies)` dans un ForEach sur les publishs du jour.

### action.make_dir : MakeDir

Cree un dossier et ses parents. S'il existe deja, rien ne change et le node reussit quand meme.

* Entrees : `exec`, `path`. Sorties : `then`, `on_error`, `dir`.

Exemple : `PathJoin (DAILY, date du jour)` > `MakeDir` > `dir` vers `Copy.dest`.

### action.delete : Delete

Supprime un fichier ou un dossier du projet. Par defaut il **archive** : l'element part dans
`ARCHIVE/<date>_<ARTISTE>/` du projet et reste recuperable. En mode `erase` il efface definitivement (`!`, seulement
sous FLUX_ROOT, jamais une racine ni un dossier projet).

* Entrees : `exec`, `path`. Sorties : `then`, `on_error`, `archived_to`.
* Reglage : `mode` (archive, erase).

Exemple : `ListFiles (*_v0*)` > `ListSort` > garder les 3 dernieres > ForEach > `Delete (archive)`.

### action.write_json : WriteJson

Ecrit des donnees dans un fichier JSON, de facon sure (ecrit a cote puis remplace). En mode `create` il refuse un
fichier existant ; `overwrite` le remplace (`!`).

Comme WriteText, le fichier est `path`, ou `dir` + `name` ; les dossiers manquants sont crees (`make_dirs`).

* Entrees : `exec`, `path` ou `dir`, `data`. Sorties : `then`, `on_error`, `path`.
* Reglages : `mode` (create, overwrite), `name`, `make_dirs`.

Exemple : ecrire un rapport `{date}_check.json` avec la liste des problemes trouves par UsdCheck.

### action.write_text : WriteText

Ecrit un fichier texte (note, rapport, liste). Le fichier est `path`, ou `dir` + `name` (un dossier et un nom) ; si
`path` est un dossier existant, le fichier `name` est ecrit dedans. Les dossiers manquants sont crees (`make_dirs`,
actif par defaut). `create` refuse un fichier existant, `overwrite` le remplace (`!`), `append` ajoute a la fin,
une ligne par ecriture (retour a la ligne ajoute si le texte n'en a pas).

* Entrees : `exec`, `path` ou `dir`, `text`. Sorties : `then`, `on_error`, `path`.
* Reglages : `mode` (create, overwrite, append), `name`, `make_dirs`.

Exemple : `WriteText (append)` dans un journal `livraisons.txt`, une ligne par livraison.

### action.create_file : CreateFile

Cree un fichier dans un dossier a partir d'un nom et d'une extension, vide ou avec un texte de depart. `name` et
`ext` se saisissent ou se relient (ex. un nom compose par Template). `create` refuse un fichier existant,
`overwrite` le remplace (`!`). Les dossiers manquants sont crees (`make_dirs`).

* Entrees : `exec`, `dir`. Sorties : `then`, `on_error`, `path` (le fichier cree).
* Reglages : `name`, `ext` (le point est optionnel, vide = sans extension), `text`, `mode` (create, overwrite),
  `make_dirs`.

Exemple : `TokenPath (level: entity)` > `CreateFile (name: README, ext: txt)` pour poser une note dans un asset.

### action.list_files : ListFiles

Liste les fichiers (ou dossiers) d'un dossier dont le nom passe un motif (`^` exclut), avec ou sans sous-dossiers.
Simple lecture : tourne aussi pendant un essai a blanc.

* Entrees : `exec`, `folder`. Sorties : `then`, `files`, `count`, `first`.
* Reglages : `pattern`, `recursive`, `kind` (file, dir, both).

Exemple : `ListFiles (*.exr, recursive)` sur un dossier de rendu > ForEach > `ConvertImage` en png.

### action.wait : Wait

Attend un certain temps avant la suite. S'arrete tout de suite si le run est annule.

* Entrees : `exec`, `seconds`. Sorties : `then`, `on_error`.

Exemple : dans un While qui surveille un fichier, `Wait 10` entre deux verifications.

### action.zip_folder : ZipFolder

Zippe un dossier (livraison, sauvegarde avant une modification risquee). `.zip` est ajoute au nom si absent ; un
dossier comme destination recoit le zip dedans. N'ecrase qu'avec `overwrite` (`!`).

* Entrees : `exec`, `folder`, `dest`. Sorties : `then`, `on_error`, `zip`.
* Reglage : `overwrite`.

Exemple : `ZipFolder (dossier du plan, dest: LIVRAISON/{shot}_{date:%Y%m%d})` avant l'envoi au monteur.

### action.convert_image : ConvertImage

Convertit une image dans un autre format (exr, png, tif, jpg) avec OpenImageIO ; l'extension de `dest` choisit le
format. N'ecrase qu'avec `overwrite` (`!`).

* Entrees : `exec`, `source`, `dest`. Sorties : `then`, `on_error`, `path`.
* Reglage : `overwrite`.

Exemple : rendus `.exr` > `ConvertImage` en `.jpg` pour une planche de review.

### action.run_headless : RunHeadless

Lance un script Python dans `hython` (Houdini) ou `mayapy` (Maya), sans interface, sur une scene (ou une scene vide),
puis ferme le process. Le script lit ses valeurs dans `args` et rend une valeur en affectant `result`. Prend une
licence du logiciel pendant le script. En essai a blanc : rien n'est lance.

* Entrees : `scene` (optionnel), `script`.
* Sorties : `result` (dictionnaire), `log` (sortie du logiciel).
* Reglages : `soft` (houdini, maya), `args`, `timeout_s` (600).

Exemple : `RunHeadless (soft: houdini, script: $FLUX/CONFIG/scripts/cache_sim.py, scene: $FLUX/PROJ/fx_v004.hip)`.

### action.batch : Batch

Lance le meme script sur une liste de scenes, une apres l'autre, chacune dans son process `hython` / `mayapy` (une
licence a la fois). S'arrete a la premiere erreur ou continue.

* Entrees : `scenes` (liste), `script`.
* Sorties : `results` (un par scene : scene, ok, result ou error), `failed`.
* Reglages : `soft`, `args`, `timeout_s`, `on_item_error` (stop, continue).

Exemple : `ListFiles (*.hip)` > `Batch (soft: houdini, script: relink_textures.py, on_item_error: continue)`.

## FLUX

Le pipeline : Production, publishs, activite, USD, textures.

### flux.notify : Notify

Affiche un message dans FLUX (toast) et / ou le poste dans le fil Activite du projet, avec un niveau info,
avertissement ou erreur. `path` lie un fichier ou dossier au message. Le toast n'apparait que dans les fenetres FLUX
du poste qui execute le flow ; pour prevenir l'equipe, choisis `where: activity` ou `both`. Pour mettre des valeurs
dans le texte (nom d'asset, version...), relie un Template.

* Entrees : `exec`, `text` (obligatoire), `path`. Sorties : `then`, `on_error`.
* Reglages : `level` (info, warn, error), `where` (toast, activity, both).

Exemple : fin d'un flow de daily : `Notify ("Daily copie", where: both, path: dossier du jour)`.

### flux.legacy_command : LegacyCommand

Execute une commande d'action v1 telle quelle. On le trouve dans les flows migres depuis les actions YAML v1 ; ses
ports reprennent les parametres et sorties de la commande. Son effet n'est pas connu du moteur : il est traite comme
destructif et jamais lance en essai a blanc.

* Entrees : `exec`, `inputs`. Sorties : `then`, `on_error`, `outputs`.
* Reglages : `command` (cle v1), `params`.

Exemple : `legacy_publish` : `select_publish` puis `copy_publish`, chacun dans un LegacyCommand.

### flux.find_publishes : FindPublishes

Liste les publishs du projet sur un jour ou une plage, filtres par logiciel, type, nom ou artiste (motifs). Logiciel,
type et version sont deduits du nom et de l'extension ; une image ou une video passe toujours le filtre logiciel.
Simple lecture.

* Entrees : `exec`, `project` (vide = projet du flow). Sorties : `then`, `items` (liste de publishs), `count`, `first`.
* Reglages : `date` (today, yesterday, AAAA-MM-JJ), `date_to`, `soft`, `type` (scene, usd, cache, texture, image, video,
  capture), `name`, `user`.

Exemple : `FindPublishes (date: today, soft: "maya houdini", type: capture)` > ForEach > Copy vers les dailies.

### flux.publish_fields : PublishFields

Lit les champs d'un publish : chemin, dossier, nom, version, artiste, date, logiciel, type. C'est la seule facon de
passer d'un `publish` a un chemin.

* Entree : `publish`. Sorties : `path`, `dir`, `name`, `version`, `user`, `date`, `soft`, `type`.

Exemple : dans un ForEach sur `FindPublishes.items` : `item` > `PublishFields.path` > `Copy.source`.

### flux.resolve_path : ResolvePath

Donne le chemin publie d'un asset d'apres ses tokens (classe, type / departement, nom, instance, variante) : le dossier
du publish et le fichier `LAST` ou d'une version `vNNN`. `exists` dit si le fichier est la. Simple lecture.

* Entree : `exec`. Sorties : `then`, `path`, `dir`, `exists`.
* Reglages : `project`, `class`, `type`, `name`, `instance`, `variant`, `iter` (LAST ou vNNN).

Exemple : `ResolvePath (class: PROPS, type: mod, name: chair)` > `GenerateProxy.source`.

### flux.project_info : ProjectInfo

Le nom, le dossier et les tokens d'un projet (ceux de Folder Manager).

* Entree : `project` (vide = projet du flow). Sorties : `name`, `path`, `tokens`.

Exemple : `ProjectInfo.path` > `PathJoin "LIVRAISON"` pour un dossier de sortie qui suit le projet.

### flux.asset_info : AssetInfo

Lit la fiche Production d'un asset (par `NOM` ou `CLASSE/NOM`) et son dossier. `found` faux si l'asset n'existe pas.

* Entrees : `project`, `asset` (obligatoire). Sorties : `found`, `class`, `folder`, `record`.

Exemple : `AssetInfo (chair)` > `JsonValue (json: record, key: status)` > `If` pour ne traiter que les assets valides.

### flux.shot_info : ShotInfo

Lit la fiche Production d'un plan (sequence + plan) et son dossier.

* Entrees : `project`, `seq`, `shot` (obligatoires). Sorties : `found`, `folder`, `record`.

Exemple : `ShotInfo (SEQ010, SH020).folder` > `ListFiles (*.mov)` pour trouver les previews du plan.

### flux.list_assets : ListAssets

Liste les assets de la Production, filtres par classe (motif, vide = toutes).

* Entree : `project`. Sorties : `names`, `records`, `count`.
* Reglage : `class`.

Exemple : `ListAssets (class: CHARS)` > ForEach > `ResolvePath` > `UsdCheck` : controle de tous les personnages.

### flux.list_shots : ListShots

Liste les plans de la Production sous la forme `SEQ/SHOT`, filtres par sequence (motif).

* Entree : `project`. Sorties : `names`, `records`, `count`.
* Reglage : `seq`.

Exemple : `ListShots (seq: SEQ010)` > ForEach > `RefreshShotStage` pour regenerer tous les stages d'une sequence.

### flux.ping : Ping

Ecrit un message dans le chat du projet en mentionnant `@artiste` : il recoit une mention non lue.

* Entrees : `exec`, `user`, `text` (obligatoires). Sorties : `then`, `on_error`.

Exemple : `UsdCheck.ok` faux > `Ping (user: PublishFields.user, text: "Ton USD a des erreurs")`.

### flux.team_reply : TeamReply

Repond a la commande du chat Team qui a lance le run (TeamCommand) : un message signe FLUX dans le fil du message,
meme canal, l'artiste de la commande garde en `via`. Lance autrement (Run de l'editeur, Schedule), il ne poste rien et
le note dans le journal du run.

* Entrees : `exec`, `text` (obligatoires). Sorties : `then`, `on_error`.

Exemple : `ZipFolder.then` > `TeamReply (text: Template "Zip pret : {arg}.zip")`.

### flux.log_activity : LogActivity

Poste un evenement dans le fil Activite du projet, vu par toute l'equipe (action update, import ou error ; `publish`
est reserve au Publisher).

* Entrees : `exec`, `text` (obligatoire), `folder`. Sorties : `then`, `on_error`.
* Reglage : `action` (update, import, error).

Exemple : apres une conversion de textures : `LogActivity ("Textures chair converties en .tx", action: update)`.

### flux.archive : Archive

Deplace un fichier ou un dossier du projet dans `ARCHIVE/<date>_<ARTISTE>/`. N'efface jamais : c'est la version sure
de Delete, jamais marquee `!`.

* Entrees : `exec`, `path` (obligatoire). Sorties : `then`, `on_error`, `archived_to`.

Exemple : archiver les anciennes versions `v0*` d'un dossier de publish en gardant les 3 dernieres.

### flux.publish_file : PublishFile

Publie un fichier dans le layout FLUX comme le Publisher : nouvelle version `vNNN`, mise a jour de `LAST`, logs. Une
version publiee ne s'ecrase jamais.

* Entrees : `exec`, `source` (obligatoire). Sorties : `then`, `on_error`, `publish`, `path`.
* Reglages : `target_name` (vide = nom du fichier), `description`.

Exemple : `ConvertImage` (planche en jpg) > `PublishFile (target_name: chair_turntable)`.

### flux.call_function : CallFunction

Appelle une fonction du code de FLUX (`package.module:fonction`, limite aux packages `features`, `core`, `dcc`). Un
argument absent prend la valeur du contexte du meme nom. Code libre : traite comme destructif, jamais lance en essai
a blanc. A reserver aux cas qu'aucun node ne couvre.

* Entrees : `exec`, `args`. Sorties : `then`, `on_error`, `result`.
* Reglage : `function`.

Exemple : `CallFunction (features.usd_assembler...:fonction)` le temps qu'un node dedie existe.

### flux.conform_texture : ConformTexture

Convertit une texture, un dossier ou un set UDIM (`<UDIM>`) en `.tx` mipmappes et tiles pour Karma, avec OpenImageIO :
aucun logiciel ouvert, aucune licence. Saute les `.tx` deja a jour, sauf avec `force` (`!`).

* Entrees : `exec`, `source`. Sorties : `then`, `on_error`, `tx_paths`, `converted`, `skipped`.
* Reglages : `out_dir` (vide = a cote), `colorconvert`, `color_in`, `color_out`, `force`.

Exemple : apres un publish de surfacing : `ResolvePath (surf, LAST)` > `ConformTexture` > `Notify ("{converted} .tx")`.

### flux.generate_proxy : GenerateProxy

Cree un proxy decime (`purpose=proxy`) pour chaque mesh de rendu d'un USD, en Python : pas de Houdini, aucune licence.
Saute un proxy deja a jour, sauf avec `force` (`!`).

* Entrees : `exec`, `source`. Sorties : `then`, `on_error`, `proxy_path`, `mesh_count`, `tri_count`.
* Reglages : `out` (vide = `<source>.proxy.usda`), `target_reduction`, `min_tris`, `force`.

Exemple : `ListAssets (PROPS)` > ForEach > `ResolvePath (mod)` > `GenerateProxy` : proxys de tous les props.

### flux.usd_check : UsdCheck

Lance le controle USD de FLUX sur un USD publie et liste ce qui ne va pas. Simple lecture ; `ok` vrai si rien a
signaler.

* Entrees : `exec`, `source`. Sorties : `then`, `on_error`, `issues`, `count`, `ok`.

Exemple : `UsdCheck` > `If (ok)` : `else` > `StrJoin issues` > `Ping` l'artiste du publish.

### flux.usd_flatten : UsdFlatten

Aplatit un stage USD (couches, references, variantes) en un seul fichier `.usda` ou `.usdc`, pour une livraison ou un
outil qui ne suit pas les references. N'ecrase qu'avec `overwrite` (`!`). Une reference introuvable (un LAST
archive, un fichier deplace) n'arrete pas l'aplatissement mais manque dans le fichier : `missing` la liste,
`complete` est faux (relie-le a un If pour prevenir). L'essai a blanc le dit aussi.

* Entrees : `exec`, `source`, `dest`. Sorties : `then`, `on_error`, `path`, `missing`, `complete`.
* Reglage : `overwrite`.

Exemple : stage du plan > `UsdFlatten (dest: LIVRAISON/{shot}.usdc)` > `ZipFolder`.

### flux.refresh_component : RefreshComponent

Met a jour le component USD de l'asset depuis un dossier de publish, comme le fait un publish. Utile apres une
correction manuelle dans un dossier publie.

* Entrees : `exec`, `folder`. Sorties : `then`, `on_error`, `updated`.
* Reglages : `base` (nom de base du publish, obligatoire), `ext` (`.usd`).

Exemple : `ResolvePath (mod, chair).dir` > `RefreshComponent (base: chair_mod)`.

### flux.refresh_shot_stage : RefreshShotStage

Regenere le stage USD du plan depuis un dossier de publish d'un departement de plan (layout, anim, lighting...).

* Entrees : `exec`, `folder`. Sorties : `then`, `on_error`, `updated`.
* Reglages : `base` (obligatoire), `ext` (`.usd`).

Exemple : `ListShots` > ForEach > `ShotInfo.folder` > `PathJoin anim` > `RefreshShotStage`.

### flux.refuse_publish : RefusePublish

Arrete le publish avec un message : rien n'est publie et le Publisher montre le message tel quel a l'artiste. Se place
dans le flow `publish_<soft>` (copie d'equipe), entre l'Instance et le node publish, derriere un If de verification
("avant publish"). Un refus ne republie jamais par l'ancien chemin. Essai a blanc : "refuserait le publish".

* Entrees : `exec`, `message` (obligatoire). Pas de sortie : le run s'arrete la.

Exemple : `PublishRequest.values` > `JsonValue name` > `Matches *_null` > `If` : `else` > `RefusePublish "Le nom doit finir par _null"`.


### flux.page_data_read : PageDataRead

Lit les enregistrements d'une collection d'une page TOOL : les journaux de tous les auteurs fusionnes, du plus ancien
au plus recent (par champ, la derniere ecriture gagne). Sert aux rappels et aux resumes.

* Entrees : `exec`, `page`, `collection`, `project` (vide = celui du run).
* Sorties : `then`, `on_error`, `records` (liste de dicts : champs + `rid`, `_by`, `_at`), `count`.

Exemple : `Schedule (8 h)` > `PageDataRead (team, events)` > `ForEach` > `If` (date du jour) > `Notify` (rappel).

### flux.page_data_write : PageDataWrite

Ajoute, modifie ou supprime un enregistrement d'une collection d'une page TOOL. L'ecriture va dans le journal de
l'utilisateur du run (jamais dans celui d'un autre), les champs sont verifies contre la collection. L'essai a blanc
n'ecrit rien.

* Entrees : `exec`, `page`, `collection`, `fields` (dict), `rid` (vide = un nouvel enregistrement), `project`.
* Sorties : `then`, `on_error`, `rid` (l'enregistrement ecrit).
* Reglage : `op` (`put` ajoute ou modifie, `del` supprime).

Exemple : `OnPublish` > `PageDataWrite (team, messages, fields: {text: "publish fait"})` : le fil de l'equipe le montre.

## Dispatcher

Envoyer du travail au dispatcher du pipe (ADR 0067). Aucun node ne nomme une farm : la config du dispatcher
(`CONFIG/dispatcher.json`, surchargee par le projet) choisit le backend, `local` (ce poste) ou `tractor` (la farm de
l'ecole, reglages de `render.json`). Le meme flow tourne a la maison et au studio. Une tache ne lance qu'un programme
declare dans `programs` de la config (husk, hython, mayapy par defaut), jamais une commande libre. En essai a blanc,
rien n'est envoye (`job_id` = `dry:...`) ; avec Tractor en simulation, le job est ecrit (.alf) sans partir (etat
`simulated`).

### dispatcher.submit : Submit

Envoie un job : une tache par entree de `tasks` (une liste d'arguments, ou `{program, args, title}`), ou une seule tache
`program` + `args`. Dans une boucle ForEach en mode dispatch, ajoute ses taches au job de la boucle au lieu d'en
envoyer un.

* Entrees : `exec`, `tasks`, `args`, `title`. Sorties : `then`, `on_error`, `job_id`, `backend`, `tasks`.
* Reglages : `program` (un programme declare), `priority` (100), `start_after` (AAAA-MM-JJTHH:MM).

Exemple : `ListFiles (*.hip)` > `ForEachBegin (mode: dispatch)` > `Submit (program: hython, args: [script, item])` >
`ForEachEnd` > `job_id` > `WaitJob` > `Notify`.

### dispatcher.status : JobStatus

Lit l'etat d'un job sans attendre : `waiting`, `active`, `done`, `error`, `cancelled` ou `simulated`, et ses compteurs.

* Entrees : `exec`, `job_id`. Sorties : `then`, `on_error`, `state`, `done`, `total`, `errors`, `finished`.

Exemple : un flow `Schedule` toutes les heures > `JobStatus` > `If (finished)` > `Notify`.

### dispatcher.wait : WaitJob

Attend la fin d'un job en relisant son etat (1 s, 2 s, 4 s... puis toutes les `every_s` secondes). `then` si tout est fini sans erreur,
`on_error` si une tache echoue, si le job est annule ou apres `timeout_s`.

* Entrees : `exec`, `job_id`. Sorties : `then`, `on_error`, `state`, `done`, `total`, `errors`.
* Reglages : `every_s` (10, min 5), `timeout_s` (3600).

Exemple : `RenderShot` > `job_id` > `WaitJob` > `Notify ("Rendu fini", path: output)`.

### dispatcher.cancel : CancelJob

Annule un job : plus aucune tache ne demarre, celles en cours sont arretees. Sur la farm, seulement un job envoye par
toi depuis FLUX.

* Entrees : `exec`, `job_id`. Sorties : `then`, `on_error`, `cancelled`.

Exemple : `WaitJob` > `on_error` > `CancelJob` pour arreter le reste d'un job qui a echoue.

### dispatcher.render_shot : RenderShot

Rend un plan (`seq` + `shot`) ou un USD publie avec husk, Karma ou RenderMan, comme l'onglet Render : gel LAST -> vNNN
(recommande), plage du plan ou du USD si vide, une tache par paquet de `chunk_size` frames, images dans
`render/vNNN/<nom>.$F4.exr`. Sur la farm, les chemins doivent etre ceux du partage (UNC).

* Entrees : `exec`, `seq`, `shot`, `usd`, `frame_start`, `frame_end`. Sorties : `then`, `on_error`, `job_id`, `output`,
  `usd`, `frames`, `backend`.
* Reglages : `renderer` (karma, renderman), `chunk_size`, `freeze` (oui), `priority`.

Exemple : `OnPublish (mode: shot, task: LIGHT)` > `PublishInfos` > `seq`, `shot` > `RenderShot` > `WaitJob` > `Notify`.

## Sous-flow

Reutiliser un flow dans un autre.

### subflow.flow_call : FlowCall

Appelle un autre flow et attend sa fin. Les parametres exposes du flow appele deviennent des entrees du node, ses
`FlowOutput` des sorties. Le flow appele demarre a son `Manual`. Profondeur maximale 8 ; un flow qui s'appelle
lui-meme est refuse.

Choisir `flow` dans Params lit l'interface du flow appele et cree les ports ; si elle change ensuite, un bouton
"Mettre a jour les ports" apparait.

* Entree : `exec` + une entree par parametre de l'interface appelee. Sorties : `then`, `on_error`, `run_id` + les
  sorties declarees.
* Reglages : `flow` (nom, cherche en perso, projet, equipe puis livre), `version` (current ou un numero).

Exemple : un flow `make_daily` appele par `daily_maya` et `daily_houdini` avec un `soft` different.

### subflow.flow_output : FlowOutput

Rend une valeur au `FlowCall` qui a appele ce flow. La sortie doit etre declaree dans Params du flow > Sorties
(sous-flow).

* Entrees : `exec`, `value`. Sortie : `then`.
* Reglage : `id`, la sortie declaree.

Exemple : sous-flow `find_last_render` : `ListSort` > `ListGet -1` > `FlowOutput (id: path)`.

## Bridges

Les briques de transport vers un logiciel ouvert : surtout a l'interieur des nodes DCC livres (double clic pour y
entrer) et pour brancher un nouveau logiciel en extension. Le protocole reste dans le node, jamais dans le flow.

### bridge.scan_ports : ScanPorts

Liste les instances ouvertes d'un logiciel sur ce poste (un port de bridge par instance) avec leur port, leur process
et leur scene. Lecture : tourne aussi en essai a blanc.

* Entree : `soft` (maya, houdini, nuke, painter, designer, marvelous, zbrush, mari).
* Sorties : `instances` (liste), `count`.

Exemple : `ScanPorts (soft: maya)` > `If (count > 0)` pour ne lancer Maya que s'il n'est pas deja ouvert.

### bridge.launch : Launch

Lance un logiciel detache de FLUX (fermer FLUX ne le ferme jamais), avec une scene si on lui en donne une. En essai a
blanc : rien n'est lance.

* Entrees : `soft`, `scene` (optionnel).
* Sortie : `launched`.

Exemple : `Launch (soft: houdini, scene: $FLUX/PROJ/lookdev_v002.hip)` > `WaitReady`.

### bridge.wait_ready : WaitReady

Attend que le bridge d'un logiciel reponde, avec des pings de plus en plus espaces, jusqu'a `timeout_s`. Sans port,
prend le premier port de la plage du logiciel qui repond (un logiciel tout juste lance choisit un port libre).

* Entrees : `soft`, `port` (optionnel).
* Sorties : `version`, `port`.
* Reglages : `timeout_s` (60), `poll_s` (1).

Exemple : `Launch (soft: maya)` > `WaitReady (soft: maya, timeout_s: 180)` > `MayaInstance (live_connect_only)`.

### bridge.ping : BridgePing

Le bridge d'un logiciel repond-il ? Ne leve pas d'erreur : `ok` est faux s'il ne repond pas. Lecture.

* Entrees : `soft`, `port` (optionnel).
* Sorties : `ok`, `version`.

Exemple : `BridgePing (soft: nuke)` > `If` > `Notify` "ouvre Nuke avant de lancer le flow".

### bridge.tcp_json_call : TcpJsonCall

Envoie une requete JSON d'une ligne a un bridge TCP local (protocole de Nuke, Mari, Painter, Designer, ZBrush) et rend
sa reponse. Une reponse `ok: false` est une erreur du node.

* Entree : `payload` (dictionnaire).
* Sortie : `response`.
* Reglages : `host` (127.0.0.1), `port`, `timeout_s`.

Exemple : `TcpJsonCall (port: 7020, payload: {"cmd": "ping"})` pour tester un bridge maison.

### bridge.http_call : HttpCall

Requete HTTP JSON vers un bridge facon Houdini (`/ping`, `/state`, `/run`).

* Entree : `body` (dictionnaire, POST).
* Sortie : `response`.
* Reglages : `port`, `path`, `method` (POST, GET), `timeout_s`.

Exemple : `HttpCall (port: 48884, path: /state, method: GET)` pour lire la selection de Houdini.

### bridge.command_port_call : CommandPortCall

Envoie du code Python au commandPort de Maya et rend la reponse brute (texte).

* Entree : `code`.
* Sortie : `response`.
* Reglages : `port`, `timeout_s`.

Exemple : `CommandPortCall (port: 7001, code: "cmds.file(q=True, sceneName=True)")`.

### bridge.file_mailbox_call : FileMailboxCall

Envoie une requete par une boite a fichiers (le protocole du bridge Marvelous, sans reseau) et attend la reponse.

* Entree : `payload`.
* Sortie : `response`.
* Reglages : `mailbox_dir` (vide = Marvelous), `timeout_s`.

Exemple : `FileMailboxCall (payload: {"action": "info"})` pour lire la scene ouverte dans Marvelous.

### bridge.com_call : ComCall

Appelle une methode d'une application Windows deja ouverte par COM (ne la lance jamais). Windows seulement.

* Entree : `args` (arguments nommes).
* Sortie : `result`.
* Reglages : `prog_id` (ex. `Photoshop.Application`), `method`.

Exemple : `ComCall (prog_id: Photoshop.Application, method: Version)`.

## Logiciels (Houdini, Maya)

Agir dans un logiciel. Un node **Instance** donne la `session` du logiciel ; chaque node `hou*` / `may*` la prend en
entree, le meme flow marche en Live (logiciel ouvert) et en Headless (sans interface). En essai a blanc, aucun logiciel
n'est lance : une instance deja ouverte sert aux lectures, sinon les nodes branches dessus sont sautes (une ligne
chacun). Les nodes marques "Live" demandent une vue a l'ecran.

### session.hou_instance : HoudiniInstance

Session Houdini. `live_connect_or_open` (defaut) : se connecte a l'instance ouverte, sinon ouvre Houdini (avec `scene`)
et attend son bridge (`wait_s`). `live_connect_only` : echoue sans instance. `headless` : lance `hython` sans interface
(une licence pour tout le run, ferme a la fin). `pick` choisit l'instance : `active` (celle choisie dans FLUX), `scene`
(celle qui a `scene` ouverte), `pid`. FLUX ne ferme jamais un Houdini Live.

* Entrees : `scene`, `template` (headless : scene de depart).
* Sorties : `session`, `scene`, `version`, `state` (live, headless).
* Reglages : `mode`, `pick`, `pid`, `wait_s` (60).

Exemple : `HoudiniInstance (mode: headless, scene: $FLUX/PROJ/fx_v004.hip)` > `houCookNode` > `houSaveScene`.

### session.may_instance : MayaInstance

Session Maya, memes modes que HoudiniInstance ; le headless lance `mayapy`. En Live, le code passe par le commandPort.

* Entrees : `scene`, `template`.
* Sorties : `session`, `scene`, `version`, `state`.
* Reglages : `mode`, `pick`, `pid`, `wait_s`.

Exemple : `MayaInstance (pick: scene, scene: $FLUX/PROJ/shot010_anim_v003.ma)` > `mayPlayblast`.

### dcc.hou_open_scene : houOpenScene

Ouvre une scene (ou une scene vide avec `new`). Refuse si la scene courante a des modifications non enregistrees, sauf
`discard_changes` (destructif).

* Entrees : `session`, `path`.
* Sortie : `scene`.

Exemple : `ForEach (scenes)` > `houOpenScene (path: item)` > `houCookNode`.

### dcc.hou_save_scene : houSaveScene

Enregistre la scene en place, ou sous `path` (.hip, .hiplc, .hipnc). Un fichier existant n'est ecrase qu'avec
`overwrite` (destructif).

* Entrees : `session`, `path` (optionnel).
* Sortie : `path`.

Exemple : `houSetParm` > `houSaveScene` pour garder la modification.

### dcc.hou_save_as : houSaveAs

Enregistre sous un autre nom. `copy` : la scene ouverte garde son nom. `increment` : ajoute la version suivante libre
(`_v001`, `_v002`...).

* Entrees : `session`, `path`.
* Sortie : `path`.

Exemple : `houSaveAs (path: $FLUX/PROJ/wip/fx.hip, increment: true)` avant une modification risquee.

### dcc.hou_run_script : houRunScript

Execute du Python dans Houdini : un fichier `script` ou du `code`. `args` donne des valeurs au code, `result` rend une
valeur. Code libre : marque destructif par prudence.

* Entrees : `session`, `script`, `code`, `args`.
* Sorties : `result`, `log`.

Exemple : `houRunScript (code: "result = [n.path() for n in hou.node('/out').children()]")`.

### dcc.hou_export : houExport

Exporte un node (ou le premier node selectionne) vers un fichier : reutilise le ROP ou en cree un (geometry, alembic,
usd), regle la sortie et le cuit. Avec `frame_range`, abc et usd ecrivent un seul fichier anime.

* Entrees : `session`, `path`, `node`.
* Sortie : `files`.
* Reglages : `format`, `frame_range`, `options` (parms du ROP), `overwrite`.

Exemple : `houFindNode (pattern: OUT)` > `houExport (path: $FLUX/PROJ/cache/rock.abc, frame_range: 1001-1100)`.

### dcc.hou_import : houImport

Importe un fichier : node d'import adapte a l'extension dans `network` (mode `node`), ou Reference / Payload / Sublayer
dans un reseau LOP.

* Entrees : `session`, `path`.
* Sortie : `nodes`.
* Reglages : `mode` (node, reference, payload, sublayer), `network`.

Exemple : `FindPublishes (type: usd)` > `ForEach` > `houImport (mode: reference)`.

### dcc.hou_find_node : houFindNode

Premier node dont le nom (et le type) passe le motif, sous `root`. Lecture.

* Entree : `session`.
* Sorties : `node`, `found`.
* Reglages : `root` (/), `pattern`, `type`.

Exemple : `houFindNode (root: /out, type: karma*)` > `houRender`.

### dcc.hou_find_nodes : houFindNodes

Tous les nodes dont le nom (et le type) passe le motif, sous `root`. Lecture.

* Entree : `session`.
* Sorties : `nodes`, `count`.
* Reglages : `root`, `pattern`, `type`.

Exemple : `houFindNodes (pattern: cache_*, type: rop_*)` > `ForEach` > `houCookNode`.

### dcc.hou_cook_node : houCookNode

Cuit un node : un ROP est rendu (sur sa plage ou `frame_range`), un autre node est recalcule (`force`).

* Entrees : `session`, `node`.
* Sortie : `cooked`.
* Reglages : `wait`, `frame_range`, `force`.

Exemple : exemple 2 de la doc : `houFindNodes` > `ForEach` > `houCookNode` > `houSaveScene`.

### dcc.hou_render : houRender

Rend un ROP (Karma, Mantra...) sur une plage, vers `output` si donne (`$F4` pour le numero d'image). Rend la liste des
images ecrites.

* Entrees : `session`, `node`.
* Sortie : `files`.
* Reglages : `frame_range`, `output`, `overwrite`.

Exemple : `houRender (node: /out/karma1, frame_range: 1001-1010)` > `ConvertImage` pour une preview.

### dcc.hou_set_parm : houSetParm

Regle la valeur d'un parm.

* Entrees : `session`, `node`, `parm`, `value`.

Exemple : `houSetParm (node: /obj/geo1/scatter1, parm: npts, value: 5000)`.

### dcc.hou_get_parm : houGetParm

Lit la valeur evaluee d'un parm. Lecture.

* Entrees : `session`, `node`, `parm`.
* Sortie : `value`.

Exemple : `houGetParm (parm: f2)` > `Compare` pour verifier la plage d'un ROP.

### dcc.hou_selected : houSelectedNodes

Les nodes selectionnes dans Houdini. Live seulement. Lecture.

* Entree : `session`.
* Sortie : `nodes`.

Exemple : `houSelectedNodes` > `ForEach` > `houExport` : exporter ce que l'artiste a selectionne.

### dcc.may_open_scene : mayOpenScene

Ouvre une scene Maya (ou une scene vide avec `new`). Refuse si la scene a des modifications non enregistrees, sauf
`discard_changes` (destructif).

* Entrees : `session`, `path`.
* Sortie : `scene`.

Exemple : `mayOpenScene (path: $FLUX/PROJ/shot010_anim_v003.ma)` > `mayPlayblast`.

### dcc.may_save_scene : maySaveScene

Enregistre la scene en place, ou sous `path` (.ma, .mb). `overwrite` pour ecraser (destructif).

* Entrees : `session`, `path` (optionnel).
* Sortie : `path`.

Exemple : `mayUpdateRef` > `maySaveScene`.

### dcc.may_save_as : maySaveAs

Enregistre sous un autre nom ; `copy` exporte tout sans changer le nom de la scene ouverte ; `increment` ajoute la
version suivante libre.

* Entrees : `session`, `path`.
* Sortie : `path`.

Exemple : `maySaveAs (path: $FLUX/PROJ/wip/anim.ma, copy: true, increment: true)`.

### dcc.may_run_script : mayRunScript

Execute du Python dans Maya (`cmds` est disponible) : fichier `script` ou `code`, `args` en entree, `result` en
sortie. Code libre : destructif par prudence.

* Entrees : `session`, `script`, `code`, `args`.
* Sorties : `result`, `log`.

Exemple : `mayRunScript (code: "result = cmds.ls(type='camera')")`.

### dcc.may_export : mayExport

Exporte la scene ou la selection (.ma .mb .abc .fbx .obj .usd), avec le meme export que le Publisher Maya.

* Entrees : `session`, `path`.
* Sortie : `files`.
* Reglages : `scope` (selection, scene), `frame_range`, `options`, `overwrite`.

Exemple : `mayFindNodes (pattern: *_cache_grp)` > `mayRunScript (select)` > `mayExport (path: anim.abc, frame_range: 1001-1100)`.

### dcc.may_import : mayImport

Importe un fichier comme le Hub : USD aplati pour Maya, import marque pour la mise a jour (MAJ). `reference` = reference
Maya ; `proxy` = USD vivant (mayaUsdProxyShape).

* Entrees : `session`, `path`.
* Sortie : `nodes`.
* Reglages : `mode` (import, reference, proxy).

Exemple : `FindPublishes` > `ForEach` > `mayImport (mode: reference)`.

### dcc.may_update_ref : mayUpdateRef

Met a jour les imports FLUX de la scene dont le LAST a change (comme le bouton MAJ) ; les imports `vNNN` restent figes.
En essai a blanc : liste les imports qui seraient remplaces.

* Entrees : `session`, `node` (vide = tous).
* Sorties : `updated`, `skipped`.

Exemple : `SceneOpened (soft: maya)` > `mayUpdateRef` : la scene est a jour des son ouverture.

### dcc.may_playblast : mayPlayblast

Capture la vue active (playblast) en video (mov, mp4) ou en images PNG (`sequence`). Live seulement. A valider en live
(codec H.264 de Maya).

* Entrees : `session`, `path`.
* Sortie : `file`.
* Reglages : `frame_range`, `size` (1920x1080), `format`, `camera`, `overwrite`.

Exemple : `mayOpenScene` > `mayPlayblast (camera: shotCam, format: mp4)` > `Notify`.

### dcc.may_find_nodes : mayFindNodes

Les nodes dont le nom court passe le motif (et du type donne), en chemins complets. Lecture.

* Entree : `session`.
* Sorties : `nodes`, `count`.
* Reglages : `pattern`, `type`.

Exemple : `mayFindNodes (pattern: *_ctrl, type: transform)` > `ForEach` > `maySetAttr`.

### dcc.may_set_attr : maySetAttr

Regle un attribut (texte, nombre, booleen, ou liste pour un attribut compose).

* Entrees : `session`, `node`, `attr`, `value`.

Exemple : `maySetAttr (node: |cam, attr: focalLength, value: 35)`.

### dcc.may_get_attr : mayGetAttr

Lit un attribut. Lecture.

* Entrees : `session`, `node`, `attr`.
* Sortie : `value`.

Exemple : `mayGetAttr (attr: translate)` > `Template` pour un rapport.

### dcc.hou_publish : houPublish

Publie un ROP (ou la scene .hip) exactement comme le Publisher Houdini : version `vNNN` immuable + LAST, journal
d'activite, flows OnPublish. Session Live sur le Houdini choisi dans FLUX (une autre instance est refusee). Jamais
destructif. En essai a blanc : calcule la destination et la version suivante, n'ecrit rien.

* Entrees : `session`, `name` (vide = nom du node), `node` (vide = selection).
* Sorties : `publish`, `path` (LAST), `version`.
* Reglages : `format`, `description`, `frame_range`, `sequence`, `options`, `project` (vide = celui du flow).

Exemple : le flow livre `publish_houdini` : `PublishRequest` > `HoudiniInstance` > `houPublish` > `FlowOutput`.

### dcc.may_publish : mayPublish

Publie la scene ou la selection de Maya exactement comme le Publisher Maya (vNNN + LAST, activite, flows OnPublish).
Session Live. En essai a blanc : destination et version calculees, rien d'ecrit.

* Entrees : `session`, `name` (nom FLUX sans version).
* Sorties : `publish`, `path`, `version`.
* Reglages : `format`, `scope` (scene, selection), `description`, `frame_range`, `options`, `project`.

Exemple : le flow livre `publish_maya` ; une verification d'equipe (ex. `mayFindNodes` + `If`) se place avant
`mayPublish`.

### session.hou_instance_core : HoudiniInstanceCore

Le coeur Python de `HoudiniInstance`, visible seulement en entrant dans le node livre (double clic). Il fait la
connexion, l'ouverture ou le lancement de `hython`. On ne le pose pas soi-meme : utiliser `HoudiniInstance`.

* Sorties : `session`, `scene`, `version`, `state`.

Exemple : dans une copie d'equipe de `HoudiniInstance`, un `Notify` avant le coeur previent l'artiste qu'Houdini va
s'ouvrir.

### session.may_instance_core : MayaInstanceCore

Le coeur Python de `MayaInstance` (connexion, ouverture, `mayapy`), visible en entrant dans le node livre.

* Sorties : `session`, `scene`, `version`, `state`.

Exemple : dans une copie d'equipe de `MayaInstance`, forcer `pick: scene` pour toute l'equipe.

### dcc.hou_publish_core : houPublishCore

Le coeur Python de `houPublish` : appelle le publish du Publisher Houdini. Visible en entrant dans le node livre.

* Sorties : `publish`, `path`, `version`.

Exemple : dans une copie d'equipe de `houPublish`, un `houGetParm` + `If` avant le coeur refuse un cache sans plage.

### dcc.may_publish_core : mayPublishCore

Le coeur Python de `mayPublish` : appelle le publish du Publisher Maya. Visible en entrant dans le node livre.

* Sorties : `publish`, `path`, `version`.

Exemple : dans une copie d'equipe de `mayPublish`, un `mayFindNodes` + `If` avant le coeur verifie qu'il n'y a pas de
node `tmp_*`.

## Logiciels (Nuke, Painter, Designer, Marvelous, ZBrush, Mari)

P6b : seuls les verbes que le bridge du logiciel sait faire aujourd'hui sont des nodes ; ouvrir, enregistrer, script et import de Painter, Designer, ZBrush, Mari (et ouvrir, enregistrer, script de Marvelous) demandent une commande nouvelle dans le bridge : reportes. Tous Live (logiciel ouvert).

### session.mari_instance : MariInstance

Session Mari (node livre, verrouille ; decision 24) : se connecte a l'instance ouverte, sinon ouvre Mari et attend son bridge. Live seulement (pas de headless). Double clic pour voir dedans ; Deverrouiller = copie d'equipe.

* Entrees : `scene`, `pid`, `wait_s`.
* Sorties : `session`, `scene`, `version`, `state`.
* Reglages : `mode`, `pick`.

Exemple : `MariInstance` > `mariInfo` > `mariExport (channels: channels)`.

### session.mari_instance_core : MariInstanceCore

Le coeur Python de `MariInstance`, visible seulement en entrant dans le node livre (double clic). On ne le pose pas soi-meme.

* Entrees : `scene`.
* Sorties : `session`, `scene`, `version`, `state`.
* Reglages : `mode`, `pick`, `pid`, `wait_s`.

Exemple : dans une copie d'equipe de `MariInstance`, une verification (`If` + `Notify`) avant le coeur.

### session.mvd_instance : MarvelousDesignerInstance

Session Marvelous Designer (node livre, verrouille ; decision 24) : se connecte a l'instance ouverte, sinon ouvre Marvelous Designer et attend son bridge. Live seulement (pas de headless). Double clic pour voir dedans ; Deverrouiller = copie d'equipe.

* Entrees : `scene`, `pid`, `wait_s`.
* Sorties : `session`, `scene`, `version`, `state`.
* Reglages : `mode`, `pick`.

Exemple : `MarvelousInstance` > `mvdExport (format: abc)`.

### session.mvd_instance_core : MarvelousDesignerInstanceCore

Le coeur Python de `MarvelousDesignerInstance`, visible seulement en entrant dans le node livre (double clic). On ne le pose pas soi-meme.

* Entrees : `scene`.
* Sorties : `session`, `scene`, `version`, `state`.
* Reglages : `mode`, `pick`, `pid`, `wait_s`.

Exemple : dans une copie d'equipe de `MarvelousDesignerInstance`, une verification (`If` + `Notify`) avant le coeur.

### session.nk_instance : NukeInstance

Session Nuke (node livre, verrouille ; decision 24) : se connecte a l'instance ouverte, sinon ouvre Nuke et attend son bridge. Live seulement (pas de headless). Double clic pour voir dedans ; Deverrouiller = copie d'equipe.

* Entrees : `scene`, `pid`, `wait_s`.
* Sorties : `session`, `scene`, `version`, `state`.
* Reglages : `mode`, `pick`.

Exemple : `NukeInstance` > `nkFindNodes (class: Write)` > `ForEach` > `nkRender`.

### session.nk_instance_core : NukeInstanceCore

Le coeur Python de `NukeInstance`, visible seulement en entrant dans le node livre (double clic). On ne le pose pas soi-meme.

* Entrees : `scene`.
* Sorties : `session`, `scene`, `version`, `state`.
* Reglages : `mode`, `pick`, `pid`, `wait_s`.

Exemple : dans une copie d'equipe de `NukeInstance`, une verification (`If` + `Notify`) avant le coeur.

### session.sd_instance : SubstanceDesignerInstance

Session Substance Designer (node livre, verrouille ; decision 24) : se connecte a l'instance ouverte, sinon ouvre Substance Designer et attend son bridge. Live seulement (pas de headless). Double clic pour voir dedans ; Deverrouiller = copie d'equipe.

* Entrees : `scene`, `pid`, `wait_s`.
* Sorties : `session`, `scene`, `version`, `state`.
* Reglages : `mode`, `pick`.

Exemple : `DesignerInstance` > `sdInfo` > `Notify` avec la liste des graphs.

### session.sd_instance_core : SubstanceDesignerInstanceCore

Le coeur Python de `SubstanceDesignerInstance`, visible seulement en entrant dans le node livre (double clic). On ne le pose pas soi-meme.

* Entrees : `scene`.
* Sorties : `session`, `scene`, `version`, `state`.
* Reglages : `mode`, `pick`, `pid`, `wait_s`.

Exemple : dans une copie d'equipe de `SubstanceDesignerInstance`, une verification (`If` + `Notify`) avant le coeur.

### session.sp_instance : SubstancePainterInstance

Session Substance Painter (node livre, verrouille ; decision 24) : se connecte a l'instance ouverte, sinon ouvre Substance Painter et attend son bridge. Live seulement (pas de headless). Double clic pour voir dedans ; Deverrouiller = copie d'equipe.

* Entrees : `scene`, `pid`, `wait_s`.
* Sorties : `session`, `scene`, `version`, `state`.
* Reglages : `mode`, `pick`.

Exemple : `PainterInstance` > `spExport (preset: PBR Metallic Roughness)`.

### session.sp_instance_core : SubstancePainterInstanceCore

Le coeur Python de `SubstancePainterInstance`, visible seulement en entrant dans le node livre (double clic). On ne le pose pas soi-meme.

* Entrees : `scene`.
* Sorties : `session`, `scene`, `version`, `state`.
* Reglages : `mode`, `pick`, `pid`, `wait_s`.

Exemple : dans une copie d'equipe de `SubstancePainterInstance`, une verification (`If` + `Notify`) avant le coeur.

### session.zb_instance : ZBrushInstance

Session ZBrush (node livre, verrouille ; decision 24) : se connecte a l'instance ouverte, sinon ouvre ZBrush et attend son bridge. Live seulement (pas de headless). Double clic pour voir dedans ; Deverrouiller = copie d'equipe.

* Entrees : `scene`, `pid`, `wait_s`.
* Sorties : `session`, `scene`, `version`, `state`.
* Reglages : `mode`, `pick`.

Exemple : `ZBrushInstance` > `zbMeshInfo` > `If` (trop de polygones) > `Notify`.

### session.zb_instance_core : ZBrushInstanceCore

Le coeur Python de `ZBrushInstance`, visible seulement en entrant dans le node livre (double clic). On ne le pose pas soi-meme.

* Entrees : `scene`.
* Sorties : `session`, `scene`, `version`, `state`.
* Reglages : `mode`, `pick`, `pid`, `wait_s`.

Exemple : dans une copie d'equipe de `ZBrushInstance`, une verification (`If` + `Notify`) avant le coeur.

### dcc.mari_export : mariExport

Exporte les channels de la geo courante de Mari dans un dossier (un export a la fois).

* Entrees : `session`, `path`.
* Sorties : `files`.
* Reglages : `format`, `channels`, `formats`, `sizes`.

Exemple : `MariInstance` > `mariExport`.

### dcc.mari_import : mariImport

Importe un fichier dans Mari : image = dans l'Image Manager ; object = nouvel objet ; version = nouvelle version de geometrie de l'objet courant (retake).

* Entrees : `session`, `path`.
* Reglages : `kind`.

Exemple : `OnPublish` (modelisation) > `MariInstance` > `mariImport` > `mariSaveScene`.

### dcc.mari_info : mariInfo

La geo courante de Mari et ses channels. Lecture.

* Entrees : `session`.
* Sorties : `geo`, `channels`.

Exemple : `MariInstance` > `mariInfo`.

### dcc.mari_open_scene : mariOpenScene

Ouvre un projet Mari, ou en cree un depuis un mesh. Refuse si le projet courant a des modifications non enregistrees, sauf discard_changes.

* Entrees : `session`, `path`, `mesh`.
* Sorties : `scene`.
* Reglages : `discard_changes`.

Exemple : `MariInstance` > `mariOpenScene` > `mariSaveAs`.

### dcc.mari_publish : mariPublish

Publish Mari (node livre, verrouille ; boite noire, decision 9) : meme code que le Publisher Mari, vNNN immuable + LAST, activite, flows OnPublish. Live, instance du Publisher. Double clic pour voir dedans ; Deverrouiller = copie d'equipe (verifications avant publish).

* Entrees : `session`, `class`, `task`, `name`, `instance`, `format`, `channels`, `conform_tx`, `description`.
* Sorties : `publish`, `path`, `version`, `files`.

Exemple : le flow livre `publish_mari` : `PublishRequest` > Instance > `mariPublish` > `FlowOutput`.

### dcc.mari_publish_core : mariPublishCore

Le coeur Python de `mariPublish`, visible seulement en entrant dans le node livre (double clic). On ne le pose pas soi-meme.

* Entrees : `session`, `class`, `task`, `name`.
* Sorties : `publish`, `path`, `version`, `files`.
* Reglages : `instance`, `format`, `channels`, `conform_tx`, `description`, `extra`.

Exemple : dans une copie d'equipe de `mariPublish`, une verification (`If` + `Notify`) avant le coeur.

### dcc.mari_run_script : mariRunScript

Execute du Python dans Mari (fichier ou code) ; `args` donne des valeurs au code, `result` rend une valeur. Code libre : destructif par prudence.

* Entrees : `session`, `script`, `code`, `args`.
* Sorties : `result`, `log`.
* Reglages : `timeout_s`.

Exemple : `MariInstance` > `mariRunScript`.

### dcc.mari_save_as : mariSaveAs

Archive le projet Mari en .mra (le projet reste dans le cache, toujours une copie) (increment : version suivante libre).

* Entrees : `session`, `path`.
* Sorties : `path`.
* Reglages : `increment`, `overwrite`.

Exemple : `MariInstance` > `mariSaveAs` (increment).

### dcc.mari_save_scene : mariSaveScene

Enregistre le projet Mari en place.

* Entrees : `session`.
* Sorties : `path`.

Exemple : `MariInstance` > `mariImport` > `mariSaveScene`.

### dcc.mvd_export : mvdExport

Exporte le projet Marvelous ouvert (abc, obj, fbx, usd, zprj) dans un dossier.

* Entrees : `session`, `path`, `name`.
* Sorties : `files`.
* Reglages : `format`, `options`, `with_zprj`.

Exemple : `MarvelousInstance` > `mvdExport`.

### dcc.mvd_import : mvdImport

Importe un fichier dans la scene Marvelous ouverte.

* Entrees : `session`, `path`.
* Sorties : `nodes`.
* Reglages : `options`.

Exemple : `MarvelousInstance` > `mvdImport`.

### dcc.mvd_info : mvdInfo

Le projet ouvert dans Marvelous et les formats qu'il sait exporter. Lecture.

* Entrees : `session`.
* Sorties : `project`, `formats`.

Exemple : `MarvelousInstance` > `mvdInfo`.

### dcc.mvd_open_scene : mvdOpenScene

Ouvre un projet Marvelous Designer. Refuse si le projet courant a des modifications non enregistrees, sauf discard_changes.

* Entrees : `session`, `path`.
* Sorties : `scene`.
* Reglages : `discard_changes`.

Exemple : `MarvelousDesignerInstance` > `mvdOpenScene` > `mvdSaveAs`.

### dcc.mvd_publish : mvdPublish

Publish Marvelous Designer (node livre, verrouille ; boite noire, decision 9) : meme code que le Publisher Marvelous Designer, vNNN immuable + LAST, activite, flows OnPublish. Live, instance du Publisher. Double clic pour voir dedans ; Deverrouiller = copie d'equipe (verifications avant publish).

* Entrees : `session`, `name`, `format`, `with_zprj`, `description`.
* Sorties : `publish`, `path`, `version`, `files`.

Exemple : le flow livre `publish_marvelous` : `PublishRequest` > Instance > `mvdPublish` > `FlowOutput`.

### dcc.mvd_publish_core : mvdPublishCore

Le coeur Python de `mvdPublish`, visible seulement en entrant dans le node livre (double clic). On ne le pose pas soi-meme.

* Entrees : `session`, `name`.
* Sorties : `publish`, `path`, `version`, `files`.
* Reglages : `format`, `options`, `with_zprj`, `description`.

Exemple : dans une copie d'equipe de `mvdPublish`, une verification (`If` + `Notify`) avant le coeur.

### dcc.mvd_run_script : mvdRunScript

Execute du Python dans Marvelous Designer (fichier ou code) ; `args` donne des valeurs au code, `result` rend une valeur. Code libre : destructif par prudence.

* Entrees : `session`, `script`, `code`, `args`.
* Sorties : `result`, `log`.
* Reglages : `timeout_s`.

Exemple : `MarvelousDesignerInstance` > `mvdRunScript`.

### dcc.mvd_save_as : mvdSaveAs

Enregistre le projet Marvelous en .zprj (increment : version suivante libre).

* Entrees : `session`, `path`.
* Sorties : `path`.
* Reglages : `increment`, `overwrite`.

Exemple : `MarvelousDesignerInstance` > `mvdSaveAs` (increment).

### dcc.mvd_save_scene : mvdSaveScene

Enregistre le projet Marvelous Designer en place.

* Entrees : `session`.
* Sorties : `path`.

Exemple : `MarvelousDesignerInstance` > `mvdImport` > `mvdSaveScene`.

### dcc.nk_export : nkExport

Ecrit un node (ou la selection) avec un Write temporaire, sur une plage ou l'image courante.

* Entrees : `session`, `path`, `node`.
* Sorties : `files`.
* Reglages : `frame_range`, `options`, `colorspace`, `overwrite`.

Exemple : `NukeInstance` > `nkExport`.

### dcc.nk_find_nodes : nkFindNodes

Les nodes du script dont le nom passe le motif (et de la classe donnee). Lecture.

* Entrees : `session`.
* Sorties : `nodes`, `count`.
* Reglages : `pattern`, `class`.

Exemple : `NukeInstance` > `nkFindNodes`.

### dcc.nk_import : nkImport

Cree un Read dans Nuke pour une image ou une sequence.

* Entrees : `session`, `path`.
* Sorties : `nodes`.
* Reglages : `frame_range`, `colorspace`.

Exemple : `NukeInstance` > `nkImport`.

### dcc.nk_open_scene : nkOpenScene

Ouvre un script Nuke (ou un script vide). Refuse si le script courant a des modifications non enregistrees, sauf discard_changes.

* Entrees : `session`, `path`.
* Sorties : `scene`.
* Reglages : `new`, `discard_changes`.

Exemple : `NukeInstance` > `nkOpenScene`.

### dcc.nk_publish : nkPublish

Publish Nuke (node livre, verrouille ; boite noire, decision 9) : meme code que le Publisher Nuke, vNNN immuable + LAST, activite, flows OnPublish. Live, instance du Publisher. Double clic pour voir dedans ; Deverrouiller = copie d'equipe (verifications avant publish).

* Entrees : `session`, `name`, `node`, `format`, `frame_range`, `sequence`, `description`, `colorspace`.
* Sorties : `publish`, `path`, `version`, `files`.

Exemple : le flow livre `publish_nuke` : `PublishRequest` > Instance > `nkPublish` > `FlowOutput`.

### dcc.nk_publish_core : nkPublishCore

Le coeur Python de `nkPublish`, visible seulement en entrant dans le node livre (double clic). On ne le pose pas soi-meme.

* Entrees : `session`, `name`, `node`.
* Sorties : `publish`, `path`, `version`, `files`.
* Reglages : `format`, `frame_range`, `sequence`, `description`, `options`, `colorspace`.

Exemple : dans une copie d'equipe de `nkPublish`, une verification (`If` + `Notify`) avant le coeur.

### dcc.nk_render : nkRender

Execute un Write existant avec ses reglages, sur une plage. Refuse d'ecraser la premiere image sans overwrite.

* Entrees : `session`, `node`.
* Sorties : `files`.
* Reglages : `frame_range`, `overwrite`.

Exemple : `NukeInstance` > `nkRender`.

### dcc.nk_run_script : nkRunScript

Execute du Python dans Nuke (fichier ou code) ; `args` donne des valeurs au code, `result` rend une valeur. Code libre : destructif par prudence.

* Entrees : `session`, `script`, `code`, `args`.
* Sorties : `result`, `log`.
* Reglages : `timeout_s`.

Exemple : `NukeInstance` > `nkRunScript`.

### dcc.nk_save_as : nkSaveAs

Enregistre le script sous un autre nom (copy : le script ouvert garde son nom ; increment : version suivante libre).

* Entrees : `session`, `path`.
* Sorties : `path`.
* Reglages : `copy`, `increment`, `overwrite`.

Exemple : `NukeInstance` > `nkSaveAs`.

### dcc.nk_save_scene : nkSaveScene

Enregistre le script Nuke en place, ou sous un autre nom.

* Entrees : `session`, `path`.
* Sorties : `path`.
* Reglages : `overwrite`.

Exemple : `NukeInstance` > `nkSaveScene`.

### dcc.sd_cook : sdCook

Cuit un .sbs en .sbsar avec sbscooker (a cote de Designer), sans ouvrir Designer.

* Entrees : `session`, `source`, `dest`.
* Sorties : `path`.
* Reglages : `overwrite`.

Exemple : `ListFiles (*.sbs)` > `ForEach` > `sdCook` : cuire tous les .sbsar d'un dossier sans ouvrir Designer.

### dcc.sd_export : sdExport

Exporte les maps, le .sbsar et / ou le .sbs du graph ouvert (ou des graphs donnes) dans un dossier.

* Entrees : `session`, `path`.
* Sorties : `files`.
* Reglages : `graphs`, `format`, `size`, `bit_depth`, `maps`, `sbsar`, `sbs`.

Exemple : `DesignerInstance` > `sdExport`.

### dcc.sd_import : sdImport

Importe un fichier dans Substance Designer : bitmap ou mesh lie dans les ressources du package du graphe courant.

* Entrees : `session`, `path`.
* Reglages : `kind`.

Exemple : `OnPublish` (modelisation) > `SubstanceDesignerInstance` > `sdImport` > `sdSaveScene`.

### dcc.sd_info : sdInfo

Les packages et graphs ouverts dans Designer. Lecture.

* Entrees : `session`.
* Sorties : `info`.

Exemple : `DesignerInstance` > `sdInfo`.

### dcc.sd_open_scene : sdOpenScene

Ouvre un projet Substance Designer (s'ajoute aux projets ouverts, rien n'est remplace).

* Entrees : `session`, `path`.
* Sorties : `scene`.

Exemple : `SubstanceDesignerInstance` > `sdOpenScene` > `sdSaveAs`.

### dcc.sd_publish : sdPublish

Publish Substance Designer (node livre, verrouille ; boite noire, decision 9) : meme code que le Publisher Substance Designer, vNNN immuable + LAST, activite, flows OnPublish. Live, instance du Publisher. Double clic pour voir dedans ; Deverrouiller = copie d'equipe (verifications avant publish).

* Entrees : `session`, `class`, `task`, `name`, `instance`, `format`, `size`, `bit_depth`, `maps`, `sbsar`, `sbs`, `conform_tx`, `description`.
* Sorties : `publish`, `path`, `version`, `files`.

Exemple : le flow livre `publish_designer` : `PublishRequest` > Instance > `sdPublish` > `FlowOutput`.

### dcc.sd_publish_core : sdPublishCore

Le coeur Python de `sdPublish`, visible seulement en entrant dans le node livre (double clic). On ne le pose pas soi-meme.

* Entrees : `session`, `class`, `task`, `name`.
* Sorties : `publish`, `path`, `version`, `files`.
* Reglages : `instance`, `format`, `size`, `bit_depth`, `maps`, `sbsar`, `sbs`, `conform_tx`, `description`, `extra`.

Exemple : dans une copie d'equipe de `sdPublish`, une verification (`If` + `Notify`) avant le coeur.

### dcc.sd_run_script : sdRunScript

Execute du Python dans Substance Designer (fichier ou code) ; `args` donne des valeurs au code, `result` rend une valeur. Code libre : destructif par prudence.

* Entrees : `session`, `script`, `code`, `args`.
* Sorties : `result`, `log`.
* Reglages : `timeout_s`.

Exemple : `SubstanceDesignerInstance` > `sdRunScript`.

### dcc.sd_save_as : sdSaveAs

Enregistre le package du graphe courant sous un nouveau .sbs (il devient son fichier) (increment : version suivante libre).

* Entrees : `session`, `path`.
* Sorties : `path`.
* Reglages : `increment`, `overwrite`.

Exemple : `SubstanceDesignerInstance` > `sdSaveAs` (increment).

### dcc.sd_save_scene : sdSaveScene

Enregistre le projet Substance Designer en place.

* Entrees : `session`.
* Sorties : `path`.

Exemple : `SubstanceDesignerInstance` > `sdImport` > `sdSaveScene`.

### dcc.sp_export : spExport

Exporte les textures du projet Painter ouvert dans un dossier, avec un preset.

* Entrees : `session`, `path`.
* Sorties : `files`.
* Reglages : `preset`, `format`, `bit_depth`, `size`, `texture_sets`, `maps`.

Exemple : `PainterInstance` > `spExport`.

### dcc.sp_import : spImport

Importe dans le projet Painter ouvert : `kind` mesh remplace le mesh (retake modelisation), `kind` resource ajoute une ressource (texture, smart material...) a l'etagere du projet. Demande le bridge Painter reinstalle (2026-10-24).

* Entrees : `session`, `path`.
* Sorties : `url` (vide pour un mesh).
* Reglages : `kind`, `usage`.

Exemple : `OnPublish` (modelisation) > `PainterInstance` > `spImport` (kind mesh) > `spSaveScene`.

### dcc.sp_info : spInfo

Le projet ouvert dans Painter et ses texture sets. Lecture.

* Entrees : `session`.
* Sorties : `info`, `texture_sets`.

Exemple : `PainterInstance` > `spInfo`.

### dcc.sp_open_scene : spOpenScene

Ouvre un projet Painter (.spp), ou en cree un depuis un mesh (`mesh`). Refuse si le projet courant a des modifications non enregistrees, sauf `discard_changes`.

* Entrees : `session`, `path`, `mesh`.
* Sorties : `scene`.
* Reglages : `discard_changes`.

Exemple : `PainterInstance` > `spOpenScene` (mesh) > `spSaveAs`.

### dcc.sp_publish : spPublish

Publish Substance Painter (node livre, verrouille ; boite noire, decision 9) : meme code que le Publisher Substance Painter, vNNN immuable + LAST, activite, flows OnPublish. Live, instance du Publisher. Double clic pour voir dedans ; Deverrouiller = copie d'equipe (verifications avant publish).

* Entrees : `session`, `class`, `task`, `name`, `instance`, `preset`, `format`, `bit_depth`, `size`, `maps`, `conform_tx`, `description`.
* Sorties : `publish`, `path`, `version`, `files`.

Exemple : le flow livre `publish_painter` : `PublishRequest` > Instance > `spPublish` > `FlowOutput`.

### dcc.sp_publish_core : spPublishCore

Le coeur Python de `spPublish`, visible seulement en entrant dans le node livre (double clic). On ne le pose pas soi-meme.

* Entrees : `session`, `class`, `task`, `name`.
* Sorties : `publish`, `path`, `version`, `files`.
* Reglages : `instance`, `preset`, `format`, `bit_depth`, `size`, `maps`, `conform_tx`, `description`, `extra`.

Exemple : dans une copie d'equipe de `spPublish`, une verification (`If` + `Notify`) avant le coeur.

### dcc.sp_run_script : spRunScript

Execute du Python dans Substance Painter (fichier ou code, module `substance_painter`) ; `args` donne des valeurs au code, `result` rend une valeur. Protege par le secret du poste copie a l'installation du bridge. Code libre : destructif par prudence.

* Entrees : `session`, `script`, `code`, `args`.
* Sorties : `result`, `log`.
* Reglages : `timeout_s`.

Exemple : `PainterInstance` > `spRunScript`.

### dcc.sp_save_as : spSaveAs

Enregistre le projet sous un autre nom en .spp (`copy` : le projet ouvert garde son nom ; `increment` : version suivante libre).

* Entrees : `session`, `path`.
* Sorties : `path`.
* Reglages : `copy`, `increment`, `overwrite`.

Exemple : `PainterInstance` > `spSaveAs` (increment).

### dcc.sp_save_scene : spSaveScene

Enregistre le projet Painter en place. Un projet jamais enregistre demande `spSaveAs`.

* Entrees : `session`.
* Sorties : `path`.

Exemple : `PainterInstance` > `spImport` > `spSaveScene`.

### dcc.zb_export : zbExport

Exporte l'outil actif de ZBrush (.ztl, .obj, .fbx selon l'extension). ZBrush est toujours relache apres, meme en cas d'erreur ou d'annulation.

* Entrees : `session`, `path`.
* Sorties : `files`.
* Reglages : `options`, `overwrite`.

Exemple : `ZBrushInstance` > `zbExport`.

### dcc.zb_import : zbImport

Importe un fichier dans ZBrush : mesh = dans le tool actif (Tool:Import, obj / fbx) ; tool = un .ztl charge comme nouveau tool.

* Entrees : `session`, `path`.
* Reglages : `kind`.

Exemple : `OnPublish` (modelisation) > `ZBrushInstance` > `zbImport` > `zbSaveScene`.

### dcc.zb_mesh_info : zbMeshInfo

Points et polygones de l'outil actif de ZBrush. Lecture.

* Entrees : `session`.
* Sorties : `info`.

Exemple : `ZBrushInstance` > `zbMeshInfo`.

### dcc.zb_open_scene : zbOpenScene

Ouvre un projet ZBrush. Refuse si le projet courant a des modifications non enregistrees, sauf discard_changes.

* Entrees : `session`, `path`.
* Sorties : `scene`.
* Reglages : `discard_changes`.

Exemple : `ZBrushInstance` > `zbOpenScene` > `zbSaveAs`.

### dcc.zb_publish : zbPublish

Publish ZBrush (node livre, verrouille ; boite noire, decision 9) : meme code que le Publisher ZBrush, vNNN immuable + LAST, activite, flows OnPublish. Live, instance du Publisher. Double clic pour voir dedans ; Deverrouiller = copie d'equipe (verifications avant publish).

* Entrees : `session`, `name`, `format`, `description`.
* Sorties : `publish`, `path`, `version`, `files`.

Exemple : le flow livre `publish_zbrush` : `PublishRequest` > Instance > `zbPublish` > `FlowOutput`.

### dcc.zb_publish_core : zbPublishCore

Le coeur Python de `zbPublish`, visible seulement en entrant dans le node livre (double clic). On ne le pose pas soi-meme.

* Entrees : `session`, `name`.
* Sorties : `publish`, `path`, `version`, `files`.
* Reglages : `format`, `options`, `description`.

Exemple : dans une copie d'equipe de `zbPublish`, une verification (`If` + `Notify`) avant le coeur.

### dcc.zb_run_script : zbRunScript

Execute du Python dans ZBrush (fichier ou code) ; `args` donne des valeurs au code, `result` rend une valeur. Code libre : destructif par prudence.

* Entrees : `session`, `script`, `code`, `args`.
* Sorties : `result`, `log`.
* Reglages : `timeout_s`.

Exemple : `ZBrushInstance` > `zbRunScript`.

### dcc.zb_save_as : zbSaveAs

Enregistre le projet (.zpr) ou le tool actif (.ztl, toujours une copie) (increment : version suivante libre).

* Entrees : `session`, `path`.
* Sorties : `path`.
* Reglages : `copy`, `increment`, `overwrite`.

Exemple : `ZBrushInstance` > `zbSaveAs` (increment).

### dcc.zb_save_scene : zbSaveScene

Enregistre le projet ZBrush en place.

* Entrees : `session`.
* Sorties : `path`.

Exemple : `ZBrushInstance` > `zbImport` > `zbSaveScene`.

## Logiciels en extension (bridge maison, P6c)

Un logiciel que FLUX ne livre pas s'ajoute par un `bridge.yml` dans `CONFIG/extensions/bridges/<soft>/` (voir `docs/development/FLOWS_BRIDGE_3DSMAX.md`). Flows > Bridges > "Creer les nodes" ecrit deux nodes d'equipe : `<Logiciel>Instance` (`session.<prefixe>_instance`) et `<prefixe>Publish` (`dcc.<prefixe>_publish`).

### session.ext_instance_core : ExtensionInstanceCore

Le coeur Python de l'Instance d'un logiciel en extension, visible seulement en entrant dans le node `<Logiciel>Instance` cree depuis le bridge. On ne le pose pas soi-meme. Live seulement (pas de headless ni de farm pour les extensions).

* Entrees : `scene`.
* Sorties : `session`, `scene`, `version`, `state`.
* Reglages : `soft`, `mode`, `pick`, `pid`, `wait_s`.

Exemple : `3dsMaxInstance` contient `ExtensionInstanceCore` avec `soft: max`.

### dcc.ext_run_script : ExtRunScript

Execute du Python dans un logiciel en extension (fichier ou code) ; `args` donne des valeurs au code, `result` rend une valeur, `args["path"]` un fichier (temporaire avec `temp_ext`, supprime a la fin du run). Code libre : destructif par prudence.

* Entrees : `session`, `script`, `code`, `args`, `path`.
* Sorties : `result`, `log`, `path`.
* Reglages : `timeout_s`, `temp_ext`.

Exemple : `3dsMaxInstance` > `ExtRunScript` (code `rt.saveMaxFile(args["path"])`, `temp_ext: .max`) > `PublishFile`.
