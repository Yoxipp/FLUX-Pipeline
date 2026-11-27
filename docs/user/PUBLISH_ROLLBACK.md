# Retour arriere du publish (P8, ADR 0070)

Depuis P8, un projet peut publier de deux facons, au choix dans ses parametres :

| Choix | Chemin | Logiciels |
|---|---|---|
| `v1` (defaut) | Chemin actuel de chaque route `POST /dcc/<soft>/publish` : moteur v1 (`flux_actions`) pour Maya / Houdini, fonctions `dcc/*` pour les autres | tous |
| `v2` | La route lance le flow livre `publish_<soft>` (ou la copie d'equipe / projet active), meme reponse au Publisher | Maya, Houdini, Nuke, Painter, Designer, Mari, Marvelous, ZBrush |

Photoshop n'a pas de flow : il reste en v1. Les ingests de fichier (`/dcc/designer/publish`, `/dcc/marvelous/publish`,
`/publish/*`) restent en v1 aussi.

**Les bridges sont identiques en v1 et en v2** : seul le backend choisit le chemin. P8 n'a modifie aucun fichier
installe dans les logiciels (`dcc/*/autostart.py`, plugins, serveur Houdini, commandPort Maya, `bridge_secret.py`).

## Ou se regle le choix

FLUX > Production > Settings > **Parametres avances du projet** > **Publish (v1 = chemin actuel, v2 = flows)**.
La valeur est la cle `publish_engine` de `<projet>/project.json` (absente = `v1`). Elle est relue a chaque publish :
pas de redemarrage.

## Ce que fait FLUX tout seul en v2

* **Repli automatique** : si le run echoue **avant** le coeur du publish (flow absent ou invalide, aucune instance du
  logiciel ouverte, port refuse), FLUX publie par v1 et le Publisher affiche un avertissement
  `publie par l'ancien chemin : <raison>`. Une ligne `repli sur v1` est ecrite dans le journal
  (logger `flux.flows.publish`, console FLUX).
* **Jamais de repli apres le coeur** : si le publish a commence puis echoue, le Publisher recoit l'erreur (503) et FLUX ne
  republie pas (sinon une deuxieme `vNNN`).
* **Refus de l'equipe** (`flux.refuse_publish` dans une copie d'equipe) : erreur 409 avec le message de l'equipe, rien
  n'est publie, pas de repli.

## Si un publish ne marche plus

Un "bridge" = le code FLUX installe DANS le logiciel (autostart, plugin, serveur Houdini, commandPort Maya) et son
client cote backend. Remonter cette echelle, du plus leger au plus lourd, en s'arretant des que ca remarche :

1. **Diagnostiquer en 1 minute** : Parametres avances du projet, Publish en `v1` (sans redemarrer), republier.
   * Ca remarche : le bridge va bien, c'est le chemin par flow. Laisser le projet en `v1`, noter l'erreur du run
     (editeur de flows, dock Runs, flow `publish_<soft>`) et corriger le flow ou le runner. Si une copie d'equipe de
     `publish_<soft>` est en cause : **Revenir au defaut** dans l'editeur supprime la copie.
   * Ca ne remarche pas : le probleme n'est pas P8 seul, etape 2.
2. **Le bridge repond-il ?** Launcher : pastille d'etat du logiciel ; console FLUX (icone terminal de la barre du haut)
   pour l'erreur du client. Pas de reponse : relancer le logiciel depuis FLUX ; puis Parametres > User > Logiciels >
   **Installer tous les bridges** (recopie le bridge du FLUX installe dans les prefs du logiciel), relancer le logiciel.
3. **Moteur v1 en cause** (Maya, Houdini) : variable d'environnement `FLUX_LEGACY_PUBLISH=<soft>` (liste separee par
   des virgules, ou `all`) : code legacy d'avant le moteur, relu a chaque publish (`flux_actions/switch.py`).
4. **Un commit P8 a touche un bridge** (ne devrait pas arriver) : `git revert <commit du logiciel>` (un commit par
   logiciel, liste ci-dessous), rebuild ou relance dev, puis **Installer tous les bridges** pour recopier l'ancien
   bridge, relancer le logiciel. Les verbes "bridge+" (Painter, Mari, ZBrush, Designer, Marvelous) dependent du secret
   du poste (`%APPDATA%/FluxPipeline/bridge_secret.txt`, `dcc/bridge_secret.py`), stable d'une installation a
   l'autre : reinstaller le bridge le recopie a cote du script. Seulement si le secret est corrompu : supprimer ce
   fichier puis reinstaller tous les bridges (un nouveau secret est cree).
5. **Exe installe casse** : reinstaller l'installeur d'avant P8 (garde de cote avant le build P8), puis Installer tous
   les bridges depuis cette version.

**A ne pas faire** : republier plusieurs fois "pour voir" pendant un incident (une version `vNNN` par essai), modifier
un bridge a la main dans les prefs du logiciel, ecrire dans `houdini.env`.

## Commits P8 par logiciel (pour un `git revert` isole)

| Logiciel | Commit | Route |
|---|---|---|
| Maya | `a3d303f9` | `/dcc/maya/publish` |
| Houdini | `5515ad72` | `/dcc/houdini/publish` |
| Nuke | `cf018059` (contient aussi `_soft_flow_publish`, utilise par les suivants) | `/dcc/nuke/publish` |
| Painter | `50dd9b7f` | `/dcc/substance/publish` |
| Designer | `f8e38baf` | `/dcc/designer/bridge/publish` |
| Mari | `fb87c306` | `/dcc/mari/publish` |
| Marvelous | `687e7499` | `/dcc/marvelous/bridge/publish` |
| ZBrush | `339d0986` | `/dcc/zbrush/publish` |

Socle : switch `ecb89d31`, runner et `flux.refuse_publish` `b57129c2`. Revert du commit Nuke = revert des 5 suivants
d'abord (ils appellent `_soft_flow_publish`). Plus simple dans la plupart des cas : laisser le projet en `v1`.

## Tests

`tests/test_flux_flows/test_publish_flows.py` (parite v1 / v2 par la vraie route et les vrais flows, fonction du
Publisher simulee), `test_publish_runner.py`, `test_publish_switch.py`, `tests/dcc_router/test_*_publish_switch.py`.
Aucun ne valide un logiciel : la verification live par logiciel est faite par le mainteneur (prompt P8, section "Verification
live").

Provisoire : le choix v1 / v2 et le chemin v1 sont retires une fois la v2 validee en live sur chaque logiciel
(nouvelle ADR, accord du mainteneur).
