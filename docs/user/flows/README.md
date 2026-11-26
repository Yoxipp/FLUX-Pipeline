# Flows : documentation du graph

Documentation utilisateur de l'editeur de flows de FLUX (Parametres avances > Actions (YAML) > Ouvrir le graph).
Les specs de build restent dans `docs/notes/prompts/flows_refonte/` ; cette doc decrit ce qui existe pour celui qui s'en sert.

| Fichier | Contenu |
|---|---|
| [01_GLOBAL.md](01_GLOBAL.md) | Ce qu'est un flow, a quoi il sert, comment il s'execute ; creer, editer, enregistrer, lancer, activer |
| [02_DISPO_ET_A_VENIR.md](02_DISPO_ET_A_VENIR.md) | Ce qui marche aujourd'hui et ce qui arrive plus tard, phase par phase |
| [03_INDEX_NODES.md](03_INDEX_NODES.md) | Tous les nodes disponibles, par famille : description et exemple d'utilisation |

## Version HTML (Parametres > Doc > Flows)

`backend/resources/manual/FLUX_Flows.html` est **genere** depuis 01, 02 et 03 (meme style que le manuel FLUX, recherche
de nodes, une carte par node). Il est servi par `GET /system/manual?doc=flows` et copie dans `FLUX_DOC/` comme le manuel.
Apres toute modification d'un fichier de ce dossier, depuis `backend/` :

```
python -m features.system.flows_doc
```

puis commiter le HTML avec les `.md` (`tests/system/test_flows_doc.py` echoue sinon). Ne jamais editer le HTML a la main.
Une ligne qui commence par `<!--` est une note pour les redacteurs : ignoree par la page HTML.

## Lien avec l'editeur

Le bouton (i) d'un node (survol du node, petite barre au-dessus) affiche la section de ce node dans
`03_INDEX_NODES.md`. Le fichier est embarque dans l'app au build (`app/src/pages/flow_editor/nodeDoc.tsx`).
Un node sans section (node Python d'equipe, commande v1) affiche sa doc du registre.

Regles d'ecriture de `03_INDEX_NODES.md` (lues par le parseur, verifiees par
`backend/tests/test_flux_flows/test_nodes_doc.py`) :

* une section par node, titre `### <type> : <Label>` (ex. `### logic.if : If`), type exact du registre ;
* la section va jusqu'au titre suivant (`##` ou `###`) ;
* texte simple : paragraphes, puces `* `, `code` et **gras**. Pas de tableau ni d'image dans une section de node.

Tout node ajoute au registre FLUX (`backend/flux_flows/nodes/*.py`) doit avoir sa section : le test echoue sinon.
