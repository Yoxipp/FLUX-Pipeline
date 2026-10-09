// i18n.tsx — lightweight FR/EN internationalization for the FLUX UI.
//
// Usage:
//   const { t, lang, setLang } = useI18n()
//   <span>{t('nav.home')}</span>
//   <span>{t('activity.entries', { n: 3 })}</span>   // "{n}" placeholders
//
// Strings live in STRINGS keyed by a namespaced id, with the FR and EN value
// co-located so a translator sees both at once. Missing keys fall back to FR,
// then to the key itself (so an un-migrated string is still visible).

import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from './api/client'

export type Lang = 'fr' | 'en'

const LS_KEY = 'flux.lang'

// ── dictionary ────────────────────────────────────────────────────────────────
// Add keys here as strings are migrated. { fr, en } per key.
export const STRINGS: Record<string, { fr: string; en: string }> = {
  // titlebar
  'titlebar.refresh':        { fr: 'Rafraîchir les données',   en: 'Refresh data' },
  'titlebar.pin':            { fr: 'Garder FLUX au premier plan', en: 'Keep FLUX on top' },
  'titlebar.unpin':          { fr: 'Ne plus garder au premier plan', en: 'Stop keeping on top' },
  'titlebar.refreshDone':    { fr: 'Refresh effectué',         en: 'Refresh done' },
  'titlebar.notifications':  { fr: 'Activité & notifications', en: 'Activity & notifications' },
  'titlebar.settings':       { fr: 'Paramètres',               en: 'Settings' },
  'titlebar.closeFlux':      { fr: 'Fermer FLUX ?',            en: 'Close FLUX?' },
  'titlebar.closeHint':      { fr: 'Les logiciels ouverts (Maya, Houdini…) restent ouverts. Pense quand même à sauvegarder tes scènes.', en: 'Open software (Maya, Houdini…) stays open. Remember to save your scenes anyway.' },
  'titlebar.slideToClose':   { fr: 'Glisse pour fermer FLUX',  en: 'Slide to close FLUX' },
  'titlebar.cancel':         { fr: 'Annuler',                  en: 'Cancel' },

  // slide-to-confirm (Production lock / archive, 2026-10-09)
  'confirm.slideToUnlock':   { fr: 'Glisse pour déverrouiller', en: 'Slide to unlock' },
  'confirm.slideToArchive':  { fr: 'Glisse pour archiver',      en: 'Slide to archive' },

  // backend status / reconnect banner
  'backend.starting':        { fr: 'Démarrage du service FLUX…', en: 'Starting the FLUX service…' },
  'backend.retrying':        { fr: 'Reconnexion au service FLUX…', en: 'Reconnecting to the FLUX service…' },
  'backend.down':            { fr: 'Service FLUX indisponible', en: 'FLUX service unavailable' },
  'backend.downHint':        { fr: "Un antivirus (Avast, Defender...) bloque peut-être le service au démarrage. FLUX réessaie automatiquement ; autorise FLUX dans ton antivirus si besoin.", en: 'An antivirus (Avast, Defender...) may be blocking the service at launch. FLUX keeps retrying automatically; allow FLUX in your antivirus if needed.' },
  'backend.retry':           { fr: 'Réessayer maintenant',     en: 'Retry now' },
  'backend.reconnected':     { fr: 'Service FLUX reconnecté',  en: 'FLUX service reconnected' },

  // settings popover
  'settings.title':          { fr: 'Paramètres',               en: 'Settings' },
  'settings.user':           { fr: 'UTILISATEUR',              en: 'USER' },
  'settings.workspace':      { fr: 'WORKSPACE',                en: 'WORKSPACE' },
  'settings.changeDir':      { fr: 'Changer de répertoire…',   en: 'Change directory…' },
  'settings.changing':       { fr: 'Changement…',              en: 'Changing…' },
  'settings.accent':         { fr: "COULEUR D'ACCENT",         en: 'ACCENT COLOR' },
  'settings.dccs':           { fr: 'LOGICIELS',                en: 'SOFTWARE' },
  'settings.bridges.all':     { fr: 'Installer tous les bridges', en: 'Install all bridges' },
  'settings.bridges.hint':    { fr: 'Installe le bridge FLUX dans chaque logiciel détecté sur ce poste (et la librairie Photoshop).', en: 'Installs the FLUX bridge in every software detected on this machine (and the Photoshop library).' },
  'settings.bridges.running': { fr: 'Installation…',            en: 'Installing…' },
  'settings.bridges.ok':      { fr: 'installé',                 en: 'installed' },
  'settings.bridges.skip':    { fr: 'non détecté',              en: 'not detected' },
  'settings.bridges.error':   { fr: 'erreur',                   en: 'error' },
  'settings.bridges.summary': { fr: '{ok} installé(s), {skip} ignoré(s), {error} erreur(s)', en: '{ok} installed, {skip} skipped, {error} error(s)' },
  'settings.bridges.restart': { fr: 'Relance les logiciels ouverts pour charger le bridge.', en: 'Restart open software to load the bridge.' },
  'settings.doc.hint':        { fr: 'Manuel de FLUX',           en: 'FLUX manual' },
  'settings.doc.open':        { fr: 'Ouvrir dans le navigateur', en: 'Open in the browser' },
  'settings.doc.folder':      { fr: 'Dossier FLUX_DOC',         en: 'FLUX_DOC folder' },
  'settings.doc.where':       { fr: 'Le manuel est aussi rangé dans le dossier FLUX_DOC du workspace.', en: 'The manual is also stored in the FLUX_DOC folder of the workspace.' },
  'settings.interface':      { fr: 'INTERFACE',                en: 'INTERFACE' },
  'settings.resetUi':        { fr: "Réinitialiser l'interface", en: 'Reset the interface' },
  'settings.language':       { fr: 'LANGUE',                   en: 'LANGUAGE' },
  'settings.logColors':      { fr: 'COULEURS DES LOGS',        en: 'LOG COLORS' },
  'settings.logColorsReset': { fr: 'Réinitialiser',           en: 'Reset' },
  'settings.version':        { fr: 'VERSION',                  en: 'VERSION' },
  'log.debug':               { fr: 'Debug',                    en: 'Debug' },
  'log.info':                { fr: 'Info',                     en: 'Info' },
  'log.warning':             { fr: 'Warning',                  en: 'Warning' },
  'log.error':               { fr: 'Erreur',                   en: 'Error' },

  // nav / sidebar
  'nav.home':                { fr: 'Accueil',                  en: 'Home' },
  'nav.folderManager':       { fr: 'Folder Manager',           en: 'Folder Manager' },
  'nav.publisher':           { fr: 'Publisher',                en: 'Publisher' },
  'nav.usd':                 { fr: 'USD',                      en: 'USD' },
  'nav.templateEditor':      { fr: 'Éditeur de templates',     en: 'Template Editor' },
  'nav.shelfManager':        { fr: 'Shelf Manager',            en: 'Shelf Manager' },
  'nav.production':          { fr: 'Production',               en: 'Production' },
  'nav.calendar':            { fr: 'Calendrier',               en: 'Calendar' },
  'nav.activity':            { fr: 'Activité',                 en: 'Activity' },
  'nav.actionPublish':       { fr: 'Publish (action)',         en: 'Publish (action)' },
  'nav.production.pin':      { fr: 'Garder Production ouvert', en: 'Keep Production open' },
  'nav.production.unpin':    { fr: 'Ne plus garder Production ouvert', en: 'Stop keeping Production open' },
  'nav.production.modes':    { fr: 'Modes de production',      en: 'Production modes' },

  // production tab
  'prod.mode.asset':         { fr: 'Assets',                   en: 'Assets' },
  'prod.mode.shot':          { fr: 'Shots',                    en: 'Shots' },
  'prod.class.CHAR':         { fr: 'Personnages',              en: 'Characters' },
  'prod.class.PROPS':        { fr: 'Props',                    en: 'Props' },
  'prod.class.ENV':          { fr: 'Environnements',           en: 'Environments' },
  'prod.class.FXRIG':        { fr: 'FX Rigs',                  en: 'FX Rigs' },
  'prod.assetGroup.CHAR':    { fr: 'Charas',                   en: 'Characters' },
  'prod.assetGroup.PROPS':   { fr: 'Props',                    en: 'Props' },
  'prod.assetGroup.ENV':     { fr: 'Enviros',                  en: 'Environments' },
  'prod.assetGroup.count':   { fr: 'assets',                   en: 'assets' },
  'prod.table.expand':       { fr: 'Déplier',                  en: 'Expand' },
  'prod.table.collapse':     { fr: 'Replier',                  en: 'Collapse' },
  'prod.table.subtasks':     { fr: 'Sous-tâches',              en: 'Subtasks' },
  'prod.table.noSubtask':    { fr: 'Aucune sous-tâche',        en: 'No subtask' },
  'prod.sort.deadlineMine':  { fr: 'Deadline + Me concerne',   en: 'Deadline + Mine' },
  'prod.sort.deadlineMineHint': { fr: 'Mes tâches d\'abord, puis la deadline la plus proche', en: 'My tasks first, then the nearest deadline' },
  'prod.preview.source':     { fr: 'Source de l\'aperçu',      en: 'Preview source' },
  'prod.preview.sourceHint': { fr: 'Clic droit : source de l\'aperçu (partagée avec la Timeline)', en: 'Right-click: preview source (shared with the Timeline)' },
  'prod.newAsset':           { fr: 'Nouvel asset',             en: 'New asset' },
  'prod.newGroup':           { fr: 'Nouveau groupe',           en: 'New group' },
  'prod.newTask':            { fr: 'Nouvelle tâche',           en: 'New task' },
  'prod.assetName':          { fr: 'Nom',                      en: 'Name' },
  'prod.taskName':           { fr: 'Libellé',                  en: 'Label' },
  'prod.typeTokens':         { fr: 'Tokens TYPE liés',         en: 'Linked TYPE tokens' },
  'prod.rename':             { fr: 'Renommer',                 en: 'Rename' },
  'prod.duplicate':          { fr: 'Dupliquer',                en: 'Duplicate' },
  'prod.delete':             { fr: 'Supprimer',                en: 'Delete' },
  'prod.emptyGrid':          { fr: 'Aucun asset pour le moment. Sélectionne une catégorie et crée-en un.', en: 'No assets yet. Pick a category and create one.' },
  'prod.selectEntity':       { fr: 'Sélectionne un asset pour voir ses tâches', en: 'Select an asset to see its tasks' },
  'prod.tabTasks':           { fr: 'Tâches',                   en: 'Tasks' },
  'prod.notes':              { fr: 'Notes',                    en: 'Notes' },
  'prod.progress':           { fr: 'Avancée',                  en: 'Progress' },
  'prod.links':              { fr: 'Liens',                    en: 'Links' },
  'prod.retakes':            { fr: 'Retakes',                  en: 'Retakes' },
  'prod.subtasks':           { fr: 'Sous-tâches',              en: 'Subtasks' },
  'prod.addSubtask':         { fr: 'Ajouter une sous-tâche',   en: 'Add a subtask' },
  'prod.recentPublishes':    { fr: 'Publishs récents',         en: 'Recent publishes' },
  'prod.noPublishes':        { fr: 'Aucun publish encore',     en: 'No publishes yet' },
  'prod.autoBadge':          { fr: 'auto',                     en: 'auto' },
  'prod.noProject':          { fr: 'Aucun projet actif — choisis-en un dans le Folder Manager.', en: 'No active project — pick one in the Folder Manager.' },
  'prod.newRetake':          { fr: 'Nouveau retake',           en: 'New retake' },
  'prod.retakeText':         { fr: 'Décris le retake',         en: 'Describe the retake' },
  'prod.retakeAdd':          { fr: 'Ajouter',                  en: 'Add' },
  'prod.retakeClose':        { fr: 'Marquer traité',           en: 'Mark done' },
  'prod.retakeReopen':       { fr: 'Rouvrir',                  en: 'Reopen' },
  'prod.publishesUnmatched': { fr: 'Publishs non reconnus',    en: 'Unrecognised publishes' },
  'prod.filter.fav':         { fr: 'Favoris',                  en: 'Favorites' },
  'prod.newSequence':        { fr: 'Nouvelle séquence',        en: 'New sequence' },
  'prod.newShot':            { fr: 'Nouveau shot',             en: 'New shot' },
  'prod.inheritTasks':       { fr: 'Hériter des tâches de la séquence', en: 'Inherit sequence tasks' },
  'prod.inheritAssets':      { fr: 'Hériter des assets de la séquence', en: 'Inherit sequence assets' },
  'prod.tabAssets':          { fr: 'Assets',                   en: 'Assets' },
  'prod.versionPinned':      { fr: 'épinglé {v}',              en: 'pinned {v}' },
  'prod.versionLast':        { fr: 'Suit LAST (dernière version publiée)', en: 'Follows LAST (latest published version)' },
  'prod.versionNewer':       { fr: 'Plus récente : {v}',       en: 'Newer: {v}' },
  'prod.emptyTimeline':      { fr: 'Aucune séquence. Utilise le menu Edit.', en: 'No sequences yet. Use the Edit menu.' },
  'prod.seqNumber':          { fr: 'Numéro',                   en: 'Number' },
  'prod.shotNumber':         { fr: 'Numéro',                   en: 'Number' },
  'prod.zoom':               { fr: 'Zoom',                     en: 'Zoom' },

  // Template Editor (RETAKES-3)
  'te.title':        { fr: 'Éditeur de templates',            en: 'Template Editor' },
  'te.subtitle':     { fr: 'Presets réutilisables déposables dans le folder manager', en: 'Reusable presets you can drop into the folder manager' },
  'te.project':      { fr: 'Projet',                          en: 'Project' },
  'te.noProject':    { fr: 'Aucun projet sélectionné',        en: 'No project selected' },
  'te.add':          { fr: 'Ajouter un preset',               en: 'Add a preset' },
  'te.empty':        { fr: 'Aucun preset. Ajoutes-en un.',    en: 'No presets yet. Add one.' },
  'te.slotEmpty':    { fr: 'vide',                            en: 'empty' },
  'te.linked':       { fr: 'linké',                           en: 'linked' },
  'te.link':         { fr: 'Linker un fichier',               en: 'Link a file' },
  'te.unlink':       { fr: 'Délinker',                        en: 'Unlink' },
  'te.rename':       { fr: 'Renommer',                        en: 'Rename' },
  'te.remove':       { fr: 'Supprimer le slot',               en: 'Remove slot' },
  'te.dropInto':     { fr: 'Déposer dans…',                   en: 'Drop into…' },
  'te.dropOk':       { fr: 'Déposé',                          en: 'Dropped' },
  'te.linkOk':       { fr: 'Fichier linké',                   en: 'File linked' },
  'te.err':          { fr: 'Échec',                           en: 'Failed' },
  'te.task':         { fr: 'TASK',                            en: 'TASK' },
  'te.soft':         { fr: 'SOFT',                            en: 'SOFT' },
  'te.taskNone':     { fr: '— aucune —',                      en: '— none —' },
  'te.softNone':     { fr: '— aucun —',                       en: '— none —' },
  'te.metaOk':       { fr: 'Assignation mise à jour',         en: 'Assignment updated' },

  // Folder manager quick-drop (RETAKES-3)
  'fm.presetDropOk': { fr: 'déposé ici',                      en: 'dropped here' },
  'fm.presetHint':   { fr: 'Déposer un preset dans ce dossier', en: 'Drop a preset into this folder' },

  // hub
  'hub.hello':               { fr: 'Bonjour',                  en: 'Hello' },
  'hub.yourTasks':           { fr: 'TES TÂCHES',               en: 'YOUR TASKS' },
  'hub.yourRetakes':         { fr: 'TES RETAKES',              en: 'YOUR RETAKES' },
  'hub.noRetake':            { fr: 'Aucun retake sur tes tâches.', en: 'No retake on your tasks.' },
  'hub.sortConcernHint':     { fr: 'Tes tâches en retake (RTK) d’abord, puis la deadline la plus proche, puis la priorité', en: 'Your tasks in retake (RTK) first, then the nearest deadline, then priority' },
  'prod.commentRetake':      { fr: 'Retake',                   en: 'Retake' },
  'prod.commentRetakeHint':  { fr: 'Marquer ce commentaire comme retake : il apparaît dans « Tes retakes » de l’artiste assigné', en: 'Mark this comment as a retake: it shows in the assigned artist’s "Your retakes"' },
  'prod.refNoProject':       { fr: 'Aucun projet actif : dépôt impossible', en: 'No active project: cannot drop' },
  'prod.refNoSeq':           { fr: 'Séquence du plan introuvable : dépôt impossible', en: 'Shot sequence not found: cannot drop' },
  'prod.refResolveFailed':   { fr: 'Chemin de la tâche non résolu ({err}) : dépôt impossible', en: 'Task path not resolved ({err}): cannot drop' },
  'prod.refUnresolved':      { fr: 'Chemin de la tâche non résolu : dépôt impossible', en: 'Task path not resolved: cannot drop' },
  'prod.refNoFile':          { fr: 'Glisse un fichier depuis l’explorateur', en: 'Drag a file from the file explorer' },
  'hub.teamChat':            { fr: 'TEAM CHAT',                en: 'TEAM CHAT' },
  'hub.chatNoProject':       { fr: 'Aucun projet actif : choisis-en un pour voir son chat.', en: 'No active project: pick one to see its chat.' },
  'hub.noMessage':           { fr: 'Aucun message',            en: 'No message' },
  'hub.messagePlaceholder':  { fr: 'Message…  (@ pour mentionner)', en: 'Message…  (@ to mention)' },

  // activity page
  'activity.markAllRead':    { fr: 'Tout marquer lu',          en: 'Mark all read' },
  'activity.loadOlder':      { fr: 'Charger l’historique plus ancien', en: 'Load older history' },
  'activity.historyLoading': { fr: 'Chargement…',              en: 'Loading…' },
  'activity.historyLoadFail':{ fr: 'Échec du chargement de l’historique', en: 'Failed to load history' },
  'activity.filter.all':     { fr: 'Tout',                     en: 'All' },
  'activity.filter.mentions': { fr: 'Mentions',                en: 'Mentions' },
  'activity.filter.publishes': { fr: 'Publishes',              en: 'Publishes' },
  'activity.filter.imports': { fr: 'Imports',                  en: 'Imports' },
  'activity.filter.updates': { fr: 'Updates',                  en: 'Updates' },
  'activity.filter.errors':  { fr: 'Erreurs',                  en: 'Errors' },
  'activity.view.self':     { fr: 'Self',                     en: 'Self' },
  'activity.view.global':   { fr: 'Global',                   en: 'Global' },
  'activity.view.selfHint': { fr: 'Mes shots suivis, mes tâches favorites et assignées, mes mentions', en: 'My followed shots, favorite and assigned tasks, my mentions' },
  'activity.view.globalHint': { fr: 'Toute l’activité du projet actif', en: 'All activity of the active project' },
  'activity.noProject':     { fr: 'Choisis un projet pour voir son activité.', en: 'Pick a project to see its activity.' },
  'activity.selfEmptyNoFollow': { fr: 'Tu ne suis aucun shot. Dans Production, clic droit sur un shot > Suivre le shot. Les tâches qui te sont assignées arrivent ici aussi.', en: 'You follow no shot. In Production, right-click a shot > Follow shot. Tasks assigned to you show up here too.' },
  'activity.selfEmpty':     { fr: 'Rien de nouveau sur tes shots suivis et tes tâches.', en: 'Nothing new on your followed shots and tasks.' },
  'activity.followed':      { fr: 'Shots suivis',             en: 'Followed shots' },
  'activity.unfollow':      { fr: 'Ne plus suivre',           en: 'Unfollow' },
  'activity.shotGone':      { fr: 'Ce shot n’existe plus dans la production du projet', en: 'This shot no longer exists in the project production' },
  'activity.empty':          { fr: 'Aucune activité pour le moment.', en: 'No activity yet.' },
  'activity.openContext':    { fr: 'Ouvrir le contexte',       en: 'Open context' },
  'activity.copyPath':       { fr: 'Copier le chemin',         en: 'Copy path' },
  'activity.openInFolderManager': { fr: 'Ouvrir dans Folder Manager', en: 'Open in Folder Manager' },
  'activity.openInFolder':   { fr: 'Ouvrir dans le dossier',   en: 'Open in folder' },
  'activity.pathCopied':     { fr: 'Chemin copié',             en: 'Path copied' },
  'activity.pathCopyFail':   { fr: 'Impossible de copier le chemin', en: 'Could not copy path' },

  // usd assembler — header + sections
  'usd.sec.target':          { fr: 'Cible',                     en: 'Target' },
  'usd.sec.identity':        { fr: 'Identité',                  en: 'Identity' },
  'usd.sec.layers':          { fr: 'Layers',                    en: 'Layers' },
  'usd.sec.departments':     { fr: 'Départements (faible → fort)', en: 'Departments (weak → strong)' },
  'usd.sec.components':      { fr: 'Components',                en: 'Components' },
  'usd.sec.assemble':        { fr: 'Assemblage',                en: 'Assembly' },
  'usd.sec.composition':     { fr: 'Composition USD',           en: 'USD Composition' },
  'usd.sec.preview':         { fr: 'Aperçu composition',        en: 'Composition preview' },
  'usd.sec.recipeJson':      { fr: 'Recette JSON',              en: 'Recipe JSON' },
  'usd.sec.log':             { fr: 'Log',                       en: 'Log' },

  // usd assembler — target cards
  'usd.target.componentHint': { fr: 'un asset publié',          en: 'a published asset' },
  'usd.target.assemblyHint':  { fr: 'plusieurs components',     en: 'several components' },
  'usd.target.shotHint':      { fr: 'départements + placement', en: 'departments + placement' },

  // usd assembler — fields
  'usd.field.sequence':      { fr: 'Séquence',                  en: 'Sequence' },
  'usd.field.shot':          { fr: 'Shot',                      en: 'Shot' },
  'usd.field.assembly':      { fr: 'Assembly',                  en: 'Assembly' },
  'usd.field.asset':         { fr: 'Asset',                     en: 'Asset' },
  'usd.field.name':          { fr: 'Nom',                       en: 'Name' },

  // usd assembler — layers editor
  'usd.addLayer':            { fr: 'Ajouter un layer',          en: 'Add a layer' },
  'usd.col.slot':            { fr: 'Slot',                      en: 'Slot' },
  'usd.col.asset':           { fr: 'Asset',                     en: 'Asset' },
  'usd.col.task':            { fr: 'Task',                      en: 'Task' },
  'usd.col.version':         { fr: 'Version',                   en: 'Version' },
  'usd.col.instance':        { fr: 'Instance',                  en: 'Instance' },
  'usd.col.variante':        { fr: 'Variante',                  en: 'Variant' },
  'usd.col.translate':       { fr: 'Translate (x y z)',         en: 'Translate (x y z)' },
  'usd.followLast':          { fr: 'Suivre LAST',               en: 'Follow LAST' },
  'usd.version.pick':        { fr: '(version)',                 en: '(version)' },
  'usd.noVersion':           { fr: 'aucune version',            en: 'no version' },
  'usd.noLayer':             { fr: 'Aucun layer. Ajoute au moins un slot (ex. Geo).', en: 'No layer. Add at least one slot (e.g. Geo).' },
  'usd.noComponent':         { fr: 'Aucun component.',          en: 'No component.' },
  'usd.add':                 { fr: 'Ajouter',                   en: 'Add' },

  // usd assembler — action bar
  'usd.project':             { fr: 'Projet',                    en: 'Project' },
  'usd.validation':          { fr: 'Validation',                en: 'Validation' },
  'usd.strict':              { fr: 'Strict',                    en: 'Strict' },
  'usd.permissive':          { fr: 'Permissif',                 en: 'Permissive' },
  'usd.strictHint':          { fr: "Strict : rien n'est écrit si une erreur (ex. asset sans USD publié).\nPermissif : écrit quand même ; les erreurs deviennent des avertissements.", en: 'Strict: nothing is written on an error (e.g. asset with no published USD).\nPermissive: writes anyway; errors become warnings.' },
  'usd.assembleBtn':         { fr: 'Assembler',                 en: 'Assemble' },
  'usd.incompleteHint':      { fr: 'Recette incomplète : ajoute un slot (component), un asset (assembly) ou une séquence et un shot (shot).', en: 'Incomplete recipe: add a slot (component), an asset (assembly) or a sequence and a shot (shot).' },

  // usd assembler — diagram toggle + log + toasts
  'usd.diag.schema':         { fr: 'Schéma',                    en: 'Schema' },
  'usd.diag.timeline':       { fr: 'Timeline pipe',             en: 'Pipe timeline' },
  'usd.tab.content':         { fr: 'Contenu',                   en: 'Content' },
  'usd.tab.versions':        { fr: 'Versions',                  en: 'Versions' },
  'usd.tab.composition':     { fr: 'Composition',               en: 'Composition' },
  'usd.tab.deps':            { fr: 'Dépendances',               en: 'Dependencies' },
  'usd.comp.layers':         { fr: 'Layers utilisés',           en: 'Layers used' },
  'usd.comp.empty':          { fr: 'Rien à composer (générer l\'asset d\'abord)', en: 'Nothing to compose (generate the asset first)' },
  'usd.comp.instanced':      { fr: 'instance (contenu dans le component)', en: 'instance (content lives in the component)' },
  'usd.comp.more':           { fr: '...',                       en: '...' },
  'usd.deps.sources':        { fr: 'Publishs sources',          en: 'Source publishes' },
  'usd.crowd.skeleton':      { fr: 'Squelette (foule)',         en: 'Skeleton (crowd)' },
  'usd.crowd.noSkeleton':    { fr: 'Pas de squelette publie',   en: 'No published skeleton' },
  'usd.crowd.signature':     { fr: 'Signature',                 en: 'Signature' },
  'usd.crowd.joints':        { fr: 'joints',                    en: 'joints' },
  'usd.crowd.sameRig':       { fr: 'Meme rig',                  en: 'Same rig' },
  'usd.crowd.clips':         { fr: 'Clips compatibles',         en: 'Fitting clips' },
  'usd.crowd.none':          { fr: 'aucun',                     en: 'none' },
  'usd.deps.components':     { fr: 'Components utilisés',       en: 'Components used' },
  'usd.versions.current':    { fr: 'courante',                  en: 'current' },
  'usd.lib.components':      { fr: 'Components',                en: 'Components' },
  'usd.lib.assemblies':      { fr: 'Assemblies',                en: 'Assemblies' },
  'usd.lib.search':          { fr: 'Rechercher',                en: 'Search' },
  'usd.lib.sortBy':          { fr: 'Trier par',                 en: 'Sort by' },
  'usd.lib.sortName':        { fr: 'Nom',                       en: 'Name' },
  'usd.lib.noToken':         { fr: 'Sans token',                en: 'No token' },
  'usd.lib.obsoleteToken':   { fr: "Ce token n'existe plus dans le projet : clic pour le retirer du filtre", en: 'This token no longer exists in the project: click to drop it from the filter' },
  'usd.lib.clearFilter':     { fr: 'Tout afficher',             en: 'Show all' },
  'usd.lib.refresh':         { fr: 'Actualiser',                en: 'Refresh' },
  'usd.lib.empty':           { fr: 'Rien de publié pour ce filtre', en: 'Nothing published for this filter' },
  'usd.lib.emptyAssets':     { fr: 'Nouveau component, puis New link dans ses blocks.', en: 'New component, then New link in its blocks.' },
  'usd.lib.noProject':       { fr: 'Aucun projet sélectionné',  en: 'No project selected' },
  'usd.lib.pick':            { fr: 'Sélectionne un élément à gauche', en: 'Select an item on the left' },
  'usd.lib.state.ok':        { fr: 'À jour',                    en: 'Up to date' },
  'usd.lib.state.empty':     { fr: 'Sans fichier',              en: 'No file' },
  'usd.comp.new':            { fr: 'Nouveau component',         en: 'New component' },
  'usd.comp.noCreatable':    { fr: 'Tous les assets ont déjà un component ou sont des décors', en: 'Every asset already has a component or is a decor' },
  'usd.comp.pickAsset':      { fr: 'Asset (token NAME)',        en: 'Asset (NAME token)' },
  'usd.comp.addBlock':       { fr: 'Block',                     en: 'Block' },
  'usd.comp.blockName':      { fr: 'Nom du block',              en: 'Block name' },
  'usd.comp.deferred':          { fr: 'Chargement a part (lourd)', en: 'Load apart (heavy)' },
  'usd.comp.legacySublayer':    { fr: 'Ancien component : ce link est un sublayer. Clique pour le repasser en automatique.', en: 'Older component: this link is a sublayer. Click to make it automatic.' },
  'usd.comp.legacySublayerShort': { fr: 'Sublayer (ancien)', en: 'Sublayer (old)' },
  'usd.comp.removeBlock':    { fr: 'Retirer le block et ses links', en: 'Remove the block and its links' },
  'usd.comp.defaultVariant': { fr: 'Variante par défaut',       en: 'Default variant' },
  'usd.comp.variantName':    { fr: 'nom',                       en: 'name' },
  'usd.comp.proxyHint':      { fr: 'Remplace le proxy des autres links du block', en: 'Stands in as proxy for the other links of the block' },
  'usd.comp.proxyOfBlock':   { fr: 'Tout le block',              en: 'Whole block' },
  'usd.comp.proxyOfHint':    { fr: 'Fichier du component dont ce link est le proxy', en: 'File of the component this link is the proxy of' },
  'usd.comp.proxyKinds':     { fr: 'Proxy : géométrie ou groom seulement', en: 'Proxy: geometry or groom only' },
  'usd.comp.pickFile':       { fr: 'Fichier',                   en: 'File' },
  'usd.comp.noPublish':      { fr: 'Aucun publish',             en: 'No publish' },
  'usd.comp.otherFile':      { fr: 'Autre fichier...',          en: 'Other file...' },
  'usd.comp.manualPath':     { fr: 'chemin dans le projet (ex. assets/chara/X/model/part.usd)', en: 'path in the project (e.g. assets/chara/X/model/part.usd)' },
  'usd.comp.needExt':        { fr: 'Le format doit être identifiable : une extension est obligatoire', en: 'The format must be identifiable: an extension is required' },
  'usd.comp.manual':         { fr: 'ajout manuel',              en: 'added by hand' },
  'usd.comp.notFound':       { fr: 'introuvable',               en: 'not found' },
  'usd.comp.targets':        { fr: 'Cibles',                    en: 'Targets' },
  'usd.comp.activeHint':     { fr: 'Actif par défaut dans le component', en: 'Active by default in the component' },
  'usd.comp.cancel':         { fr: 'Annuler',                   en: 'Cancel' },
  'usd.comp.save':           { fr: 'Enregistrer',               en: 'Save' },
  'usd.comp.legacy':         { fr: 'Ancien format (component automatique) : réécrit au nouveau format à la prochaine mise à jour', en: 'Old format (automatic component): rewritten in the new format on the next update' },
  'usd.kind.geometry':       { fr: 'géométrie',                 en: 'geometry' },
  'usd.kind.groom':          { fr: 'groom',                     en: 'groom' },
  'usd.kind.shader':         { fr: 'shader',                    en: 'shader' },
  'usd.kind.rig':            { fr: 'rig',                       en: 'rig' },
  'usd.kind.animation':      { fr: 'animation',                 en: 'animation' },
  'usd.kind.other':          { fr: 'autre',                     en: 'other' },
  'usd.lib.state.stale':     { fr: 'Mise à jour dispo',         en: 'Update available' },
  'usd.lib.departments':     { fr: 'Départements',              en: 'Departments' },
  'usd.lib.versions':        { fr: 'Versions',                  en: 'Versions' },
  'usd.lib.usedBy':          { fr: 'Utilisé par',               en: 'Used by' },
  'usd.lib.unused':          { fr: 'Aucune assembly',           en: 'No assembly' },
  'usd.lib.update':          { fr: 'Mettre à jour',             en: 'Update' },
  'usd.lib.copyPath':        { fr: 'Copier le chemin LAST',     en: 'Copy LAST path' },
  'usd.lib.copied':          { fr: 'Chemin copié',              en: 'Path copied' },
  'usd.lib.openFolder':      { fr: 'Dossier',                   en: 'Folder' },
  'usd.lib.openProduction':  { fr: 'Production',                en: 'Production' },
  'usd.lib.instances':       { fr: 'Instances',                 en: 'Instances' },
  'usd.lib.followLast':      { fr: 'LAST',                      en: 'LAST' },
  'usd.lib.frozen':          { fr: 'figé',                      en: 'frozen' },
  'usd.lib.broken':          { fr: 'lien cassé',                en: 'broken link' },
  'usd.lib.brokenCount':     { fr: '{n} lien(s) cassé(s)',      en: '{n} broken link(s)' },
  'usd.lib.notComponent':    { fr: 'hors component',            en: 'not a component' },
  'usd.lib.noInstance':      { fr: 'Aucune instance',           en: 'No instance' },
  'usd.showDiag':            { fr: 'Afficher', en: 'Show' },
  'usd.hideDiag':            { fr: 'Masquer', en: 'Hide' },
  'usd.lib.changeLink':      { fr: 'Changer le link',           en: 'Change link' },
  'usd.lib.apply':           { fr: 'Appliquer',                 en: 'Apply' },
  'usd.lib.variant':         { fr: 'Variante',                  en: 'Variant' },
  'usd.lib.followLatest':    { fr: 'Dernier (LAST)',            en: 'Latest (LAST)' },
  'usd.lib.relinked':        { fr: '{name} pointe vers {target}', en: '{name} now points to {target}' },
  'usd.lib.add':             { fr: 'Ajouter',                   en: 'Add' },
  'usd.lib.count':           { fr: 'Qté',                       en: 'Qty' },
  'usd.lib.duplicate':       { fr: 'Dupliquer',                 en: 'Duplicate' },
  'usd.lib.rename':          { fr: 'Renommer',                  en: 'Rename' },
  'usd.lib.remove':          { fr: 'Retirer',                   en: 'Remove' },
  'usd.lib.newAssembly':     { fr: 'Nouvelle assembly',         en: 'New assembly' },
  'usd.lib.assemblyName':    { fr: 'Nom (ex. TOWN)',            en: 'Name (e.g. TOWN)' },
  'usd.lib.blank':           { fr: 'Vide',                      en: 'Empty' },
  'usd.lib.copyOf':          { fr: 'Copie de {name}',           en: 'Copy of {name}' },
  'usd.lib.create':          { fr: 'Créer',                     en: 'Create' },
  'usd.lib.allLast':         { fr: 'Tout suivre LAST',          en: 'All follow LAST' },
  'usd.lib.freezeAll':       { fr: 'Tout figer',                en: 'Freeze all' },
  'usd.lib.legacy':          { fr: 'Ancien format : devient une assembly versionnée à la première modification', en: 'Old format: becomes a versioned assembly on first edit' },
  'usd.lib.layout':          { fr: 'Placement',                 en: 'Layout' },
  'usd.lib.noLayout':        { fr: 'aucun placement publié (se fait dans le DCC)', en: 'no layout published (done in the DCC)' },
  'usd.lib.publishLayout':   { fr: 'Publier le placement depuis', en: 'Publish layout from' },
  'usd.lib.layoutHelp':      { fr: 'Lit la position de chaque instance dans la scène ouverte (Houdini : node LOP sélectionné ou /stage, Maya : groupe importé)', en: 'Reads each instance position from the open scene (Houdini: selected LOP node or /stage, Maya: imported group)' },
  'usd.lib.layoutPublished': { fr: 'Placement {layout} ({n} instances) : {name} {version}', en: 'Layout {layout} ({n} instances): {name} {version}' },
  'usd.lib.saved':           { fr: '{name} {version}',          en: '{name} {version}' },
  'usd.lib.noChange':        { fr: 'Aucun changement',          en: 'No change' },
  'usd.log.waiting':         { fr: 'En attente',                en: 'Waiting' },
  'usd.toast.success':       { fr: 'Assemblage {kind} réussi',  en: '{kind} assembly succeeded' },
  'usd.toast.error':         { fr: 'Assemblage {kind} échoué',  en: '{kind} assembly failed' },
  'usd.preview.noLayer':     { fr: 'aucun layer',               en: 'no layer' },

  // usd assembler — diagram shared
  'usd.d.onDisk':            { fr: 'SUR LE DISQUE · .usd SÉPARÉS', en: 'ON DISK · SEPARATE .usd' },
  'usd.d.oneStage':          { fr: "À L'OUVERTURE · 1 STAGE",    en: 'ON OPEN · 1 STAGE' },
  'usd.d.strong':            { fr: 'fort',                      en: 'strong' },
  'usd.d.weakBase':          { fr: 'faible · base',             en: 'weak · base' },
  'usd.d.sublayersStrongWeak': { fr: 'sublayers (fort → faible)', en: 'sublayers (strong → weak)' },

  // usd assembler — component diagram
  'usd.d.comp.aria':         { fr: 'Component : les layers de tâches (model, skel, anim) empilés en sublayers fort vers faible composent un seul component CHAR_DAVID.', en: 'Component: task layers (model, skel, anim) stacked as sublayers strong to weak compose a single CHAR_DAVID component.' },
  'usd.d.comp.baseNote':     { fr: 'sublayers (fort → faible) · model = géo de base', en: 'sublayers (strong → weak) · model = base geo' },
  'usd.d.comp.composed':     { fr: 'géo + skel + anim composés en un prim', en: 'geo + skel + anim composed into one prim' },
  'usd.d.comp.perTask':      { fr: 'une layer par tâche, publiée séparément', en: 'one layer per task, published separately' },
  'usd.d.comp.variants':     { fr: 'variants : lod / look / purpose', en: 'variants: lod / look / purpose' },

  // usd assembler — assembly diagram
  'usd.d.asm.aria':          { fr: 'Assembly : plusieurs fichiers component (CHAR_DAVID, CHAR_SEAN) référencés composent un seul assembly ENV_set.', en: 'Assembly: several component files (CHAR_DAVID, CHAR_SEAN) referenced compose a single ENV_set assembly.' },
  'usd.d.asm.referenced':    { fr: 'components référencés + placés', en: 'components referenced + placed' },
  'usd.d.asm.reusable':      { fr: '1 unité réutilisable dans tous les shots', en: '1 reusable unit across all shots' },

  // usd assembler — shot diagram
  'usd.d.shot.aria':         { fr: "Shot : chaque département (layout, anim, fx, lighting) publie sa propre layer, empilées fort vers faible ; tout le monde ouvre le même shot et édite sa layer.", en: 'Shot: each department (layout, anim, fx, lighting) publishes its own layer, stacked strong to weak; everyone opens the same shot and edits their layer.' },
  'usd.d.shot.lighting':     { fr: 'Lighting (4) · fort',       en: 'Lighting (4) · strong' },
  'usd.d.shot.fx':           { fr: 'FX / CFX (3)',              en: 'FX / CFX (3)' },
  'usd.d.shot.anim':         { fr: 'Anim (2)',                  en: 'Anim (2)' },
  'usd.d.shot.layout':       { fr: 'Layout (1) · faible',       en: 'Layout (1) · weak' },
  'usd.d.shot.published':    { fr: "publié layout → anim → fx → lighting · chacun surcharge l'amont", en: 'published layout → anim → fx → lighting · each overrides upstream' },
  'usd.d.shot.composeSub':   { fr: 'references + sublayers (par dept)', en: 'references + sublayers (per dept)' },
  'usd.d.shot.everyone':     { fr: 'tout le monde ouvre CE fichier', en: 'everyone opens THIS file' },
  'usd.d.shot.editsOwn':     { fr: 'chacun édite SA layer department (edit target)', en: 'each edits ITS OWN department layer (edit target)' },
  'usd.d.shot.order':        { fr: 'amont → aval : layout, anim, fx, lighting', en: 'upstream → downstream: layout, anim, fx, lighting' },
  'usd.d.shot.republish':    { fr: 'corriger le CHAR = republier CHAR_DAVID.usda', en: 'fix the CHAR = republish CHAR_DAVID.usda' },
  'usd.d.layoutRefs':        { fr: 'layout references',         en: 'layout references' },

  // usd assembler — pipeline timeline
  'usd.tl.group.upstream':   { fr: 'AMONT · assets (hors shot)', en: 'UPSTREAM · assets (outside shot)' },
  'usd.tl.group.inShot':     { fr: 'DANS LE SHOT · même fichier, 1 layer par dept', en: 'IN THE SHOT · same file, 1 layer per dept' },
  'usd.tl.group.render':     { fr: 'RENDER',                    en: 'RENDER' },
  'usd.tl.opens':            { fr: 'ouvre',                     en: 'opens' },
  'usd.tl.s1.role':          { fr: 'Model / Rig',               en: 'Model / Rig' },
  'usd.tl.s1.open':          { fr: 'sa scène asset (Maya)',     en: 'its asset scene (Maya)' },
  'usd.tl.s1.out':           { fr: 'publie  CHAR_DAVID.usda  (géo + skel + variants)', en: 'publishes  CHAR_DAVID.usda  (geo + skel + variants)' },
  'usd.tl.s2.role':          { fr: 'Set-dress',                 en: 'Set-dress' },
  'usd.tl.s2.open':          { fr: 'sa scène de dressing',      en: 'its set-dress scene' },
  'usd.tl.s2.out':           { fr: 'publie  ENV_set.usda  (assembly du décor)', en: 'publishes  ENV_set.usda  (set assembly)' },
  'usd.tl.s3.role':          { fr: 'Layout',                    en: 'Layout' },
  'usd.tl.s3.out':           { fr: 'édite  ..._layout.usda  · references CHAR + ENV + caméra', en: 'edits  ..._layout.usda  · references CHAR + ENV + camera' },
  'usd.tl.s4.role':          { fr: 'Anim',                      en: 'Anim' },
  'usd.tl.s4.out':           { fr: 'édite  ..._anim.usda  · SkelAnimation en override', en: 'edits  ..._anim.usda  · SkelAnimation as override' },
  'usd.tl.s5.role':          { fr: 'FX / CFX',                  en: 'FX / CFX' },
  'usd.tl.s5.out':           { fr: 'édite  ..._fx.usda  · muscles / cloth / sim', en: 'edits  ..._fx.usda  · muscles / cloth / sim' },
  'usd.tl.s6.role':          { fr: 'Lighting',                  en: 'Lighting' },
  'usd.tl.s6.out':           { fr: 'édite  ..._lighting.usda  · surcharge le rig de séquence', en: 'edits  ..._lighting.usda  · overrides the sequence rig' },
  'usd.tl.s7.role':          { fr: 'Comp',                      en: 'Comp' },
  'usd.tl.s7.open':          { fr: 'le shot composé (farm Tractor)', en: 'the composed shot (Tractor farm)' },
  'usd.tl.s7.out':           { fr: 'Nuke',                      en: 'Nuke' },
  'usd.tl.rule':             { fr: "Règle : amont → aval. Chaque dept hérite (compose) de l'amont et surcharge dans SA layer ; personne ne modifie le fichier d'un autre. Corriger le CHAR = republier CHAR_DAVID.usda, tous les shots suivent.", en: 'Rule: upstream → downstream. Each dept inherits (composes) upstream and overrides in ITS OWN layer; nobody edits another dept file. Fix the CHAR = republish CHAR_DAVID.usda, all shots follow.' },
}

// ── runtime ───────────────────────────────────────────────────────────────────

function translate(key: string, lang: Lang, vars?: Record<string, string | number>): string {
  const entry = STRINGS[key]
  let s = entry ? (entry[lang] ?? entry.fr) : key
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.replace(new RegExp(`\\{${k}\\}`, 'g'), String(v))
  return s
}

interface I18nContextValue {
  lang: Lang
  setLang: (l: Lang) => void
  t: (key: string, vars?: Record<string, string | number>) => string
}

const I18nContext = createContext<I18nContextValue | null>(null)

function readInitialLang(): Lang {
  try {
    const stored = localStorage.getItem(LS_KEY)
    if (stored === 'fr' || stored === 'en') return stored
  } catch { /* blocked storage */ }
  return 'fr'
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(readInitialLang)

  // Sync the initial language from the backend settings once (may override the cache).
  useEffect(() => {
    api.getSettings().then(s => {
      if (s.language === 'fr' || s.language === 'en') {
        setLangState(s.language)
        try { localStorage.setItem(LS_KEY, s.language) } catch { /* blocked */ }
      }
    }).catch(() => { /* backend not up — keep cached */ })
  }, [])

  useEffect(() => { document.documentElement.lang = lang }, [lang])

  const setLang = useCallback((l: Lang) => {
    setLangState(l)
    try { localStorage.setItem(LS_KEY, l) } catch { /* blocked */ }
    void api.updateSettings({ language: l }).catch(() => { /* keep local choice */ })
  }, [])

  const t = useCallback(
    (key: string, vars?: Record<string, string | number>) => translate(key, lang, vars),
    [lang],
  )

  return <I18nContext.Provider value={{ lang, setLang, t }}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext)
  if (!ctx) throw new Error('useI18n must be used within a LanguageProvider')
  return ctx
}

/** Inline FR/EN pair for one-off UI strings: `tr('Tout', 'All')`. Prefer a STRINGS key when the
 *  text is shared between pages. `locale` is the BCP 47 tag for dates and numbers. */
export function useTr() {
  const { lang } = useI18n()
  return {
    lang,
    tr: (fr: string, en: string) => (lang === 'en' ? en : fr),
    locale: lang === 'en' ? 'en-GB' : 'fr-FR',
  }
}
