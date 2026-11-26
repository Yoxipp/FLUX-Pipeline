# CONTEXT - `backend/features/activity/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee de mai 2026 retiree (lisible au tag `archive/pre-cleanup`).
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

Fil d'activite, chat, @mentions : `activity_writer.py`, `activity_reader.py`, `chat_manager.py`, `history.py` (JSONL append-only sous lock inter-process, rotation vers `CONFIG/archive/`), `read_state.py`. Routes : `routers/activity.py` (ETag via `repository.version_token`).

**`log_publish` (zone fragile, P5 Flows)** : apres l'ecriture d'activite, appelle `flux_flows.events.publish_done` (seul
import de `flux_flows` dans `features/`) pour l'evenement `event.on_publish`. Non bloquant, sans effet sans flow actif
OnPublish, coupe par `FLUX_FLOWS_HOOKS=0` (lu a chaque appel, Parametres avances "Flows apres publish"), une emission
qui leve est loggee sans toucher au publish (`tests/publisher/test_publish_hooks.py`). Commit isole (`git revert` possible).

L'ancienne fiche reste juste pour JSONL/rotation, mais son ETag base sur `stat` est remplace par `version_token`.

Chat par projet (2026-09-27) : `DOSSIER_PROJETS/<projet>/teamChat.json` (`paths.get_project_chat_path`), plus de chat commun. `GET /activity/chat?project=` (sans projet ou projet inconnu : messages vides), `POST /activity/chat {project, message}` (400 nom invalide, 404 projet inconnu). `resolve_chat_path` refuse separateurs et `..`. Les @mentions restent globales par utilisateur et portent un champ `project`. L'ancien `CONFIG/teamChat.json` n'est plus lu (pas de migration : impossible de savoir a quel projet appartient chaque message) ; la migration SQLite prend les chats de chaque projet.

Notifications personnelles (retake 04, ADR 0045) : `notifications.py` (fonctions pures) + `GET /activity/notifications?project=&scope=self|global`. Raison par event : shot suivi (cle favori `<projet>|<SEQ>/<SHOT>|*`), tache favorite, tache assignee (`task_details.assignee`). Artiste = utilisateur courant du backend. Tests : `tests/activity/test_notifications.py`.
