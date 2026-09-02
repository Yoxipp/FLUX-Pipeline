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
  'titlebar.tagline':        { fr: 'Pipeline Tool',            en: 'Pipeline Tool' },
  'titlebar.refresh':        { fr: 'Rafraîchir les données',   en: 'Refresh data' },
  'titlebar.refreshDone':    { fr: 'Refresh effectué',         en: 'Refresh done' },
  'titlebar.notifications':  { fr: 'Activité & notifications', en: 'Activity & notifications' },
  'titlebar.settings':       { fr: 'Paramètres',               en: 'Settings' },
  'titlebar.closeFlux':      { fr: 'Fermer FLUX ?',            en: 'Close FLUX?' },
  'titlebar.closeHint':      { fr: 'Les logiciels ouverts (Maya, Houdini…) restent ouverts. Pense quand même à sauvegarder tes scènes.', en: 'Open software (Maya, Houdini…) stays open. Remember to save your scenes anyway.' },
  'titlebar.slideToClose':   { fr: 'Glisse pour fermer FLUX',  en: 'Slide to close FLUX' },
  'titlebar.cancel':         { fr: 'Annuler',                  en: 'Cancel' },

  // settings popover
  'settings.title':          { fr: 'Paramètres',               en: 'Settings' },
  'settings.user':           { fr: 'UTILISATEUR',              en: 'USER' },
  'settings.workspace':      { fr: 'WORKSPACE',                en: 'WORKSPACE' },
  'settings.changeDir':      { fr: 'Changer de répertoire…',   en: 'Change directory…' },
  'settings.changing':       { fr: 'Changement…',              en: 'Changing…' },
  'settings.accent':         { fr: "COULEUR D'ACCENT",         en: 'ACCENT COLOR' },
  'settings.interface':      { fr: 'INTERFACE',                en: 'INTERFACE' },
  'settings.resetUi':        { fr: "Réinitialiser l'interface", en: 'Reset the interface' },
  'settings.language':       { fr: 'LANGUE',                   en: 'LANGUAGE' },
  'settings.version':        { fr: 'VERSION',                  en: 'VERSION' },

  // nav / sidebar
  'nav.home':                { fr: 'Accueil',                  en: 'Home' },
  'nav.folderManager':       { fr: 'Folder Manager',           en: 'Folder Manager' },
  'nav.publisher':           { fr: 'Publisher',                en: 'Publisher' },
  'nav.usdAssembler':        { fr: 'USD Assembleur',           en: 'USD Assembler' },
  'nav.shelfManager':        { fr: 'Shelf Manager',            en: 'Shelf Manager' },
  'nav.activity':            { fr: 'Activité',                 en: 'Activity' },

  // hub
  'hub.hello':               { fr: 'Bonjour',                  en: 'Hello' },
  'hub.recentActivity':      { fr: 'ACTIVITÉ RÉCENTE',         en: 'RECENT ACTIVITY' },
  'hub.noRecentActivity':    { fr: 'Aucune activité récente',  en: 'No recent activity' },
  'hub.teamChat':            { fr: 'TEAM CHAT',                en: 'TEAM CHAT' },
  'hub.noMessage':           { fr: 'Aucun message',            en: 'No message' },
  'hub.messagePlaceholder':  { fr: 'Message…  (@ pour mentionner)', en: 'Message…  (@ to mention)' },
  'hub.shortcuts':           { fr: 'RACCOURCIS',               en: 'SHORTCUTS' },
  'hub.sc.folderManager':    { fr: 'Naviguer & importer',      en: 'Browse & import' },
  'hub.sc.publisher':        { fr: 'Exporter un asset',        en: 'Export an asset' },
  'hub.sc.usd':              { fr: 'Composer des layers',      en: 'Compose layers' },
  'hub.sc.shelf':            { fr: 'Installer / màj',          en: 'Install / update' },
  'hub.sc.activity':         { fr: 'Historique équipe',        en: 'Team history' },
  'hub.dccConnection':       { fr: 'CONNEXION DCC',            en: 'DCC CONNECTION' },
  'hub.noDcc':               { fr: 'Aucun DCC connecté',       en: 'No DCC connected' },

  // activity page
  'activity.title':          { fr: 'Activité & Notifications', en: 'Activity & Notifications' },
  'activity.markAllRead':    { fr: 'Tout marquer lu',          en: 'Mark all read' },
  'activity.filter.all':     { fr: 'Tout',                     en: 'All' },
  'activity.filter.publishes': { fr: 'Publishes',              en: 'Publishes' },
  'activity.filter.imports': { fr: 'Imports',                  en: 'Imports' },
  'activity.filter.updates': { fr: 'Updates',                  en: 'Updates' },
  'activity.filter.errors':  { fr: 'Erreurs',                  en: 'Errors' },
  'activity.entries':        { fr: '{n} entrées',              en: '{n} entries' },
  'activity.empty':          { fr: 'Aucune activité pour le moment.', en: 'No activity yet.' },
  'activity.openContext':    { fr: 'Ouvrir le contexte',       en: 'Open context' },
  'activity.copyPath':       { fr: 'Copier le chemin',         en: 'Copy path' },
  'activity.openInFolderManager': { fr: 'Ouvrir dans Folder Manager', en: 'Open in Folder Manager' },
  'activity.openInFolder':   { fr: 'Ouvrir dans le dossier',   en: 'Open in folder' },
  'activity.pathCopied':     { fr: 'Chemin copié',             en: 'Path copied' },
  'activity.pathCopyFail':   { fr: 'Impossible de copier le chemin', en: 'Could not copy path' },
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
