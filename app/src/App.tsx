// App.tsx — shell principal : routing, TitleBar, Sidebar, StatusBar.

import { useEffect, useRef, useState } from 'react'
import { StartPageRedirect, WorkProfileProvider, useWorkProfile } from './WorkProfileContext'
import { notificationReason } from './lib/activityNotify'
import { useProject } from './ProjectContext'
import { WorkProfileDialog } from './components/shared/WorkProfileDialog'
import { HashRouter, Route, Routes, useNavigate } from 'react-router-dom'
import { TitleBar }  from './components/shared/TitleBar'
import { Sidebar }   from './components/shared/Sidebar'
import { StatusBar } from './components/shared/StatusBar'
import { BackendBanner } from './components/shared/BackendBanner'
import { useBackendStatus } from './hooks/useBackendStatus'
import { useDccStatus }  from './hooks/useDccStatus'
import { useActivity }   from './hooks/useActivity'
import { FeedsProvider, useActivityFeed, useMentionsFeed } from './hooks/useFeeds'
import { useFavorites, eventMatchesFavorite } from './hooks/useFavorites'
import { useSettings }   from './hooks/useSettings'
import { parseFluxFilename } from './pages/Production/util'
import { Hub }           from './pages/Hub'
import { PageErrorBoundary } from './components/shared/PageErrorBoundary'
import { Publisher }     from './pages/Publisher'
import { ActionPublish } from './pages/ActionPublish'
import { ActionGraph }   from './pages/ActionGraph'
import { Activity }      from './pages/Activity'
import { Projects }      from './pages/Projects'
import { ShelfManager }  from './pages/ShelfManager'
import { UsdPage }       from './pages/usd/UsdPage'
import { TemplateEditor } from './pages/TemplateEditor'
import { Production }    from './pages/Production/Production'
import { Calendar }      from './pages/Calendar'
import { AdvancedSettings } from './pages/AdvancedSettings'
import { DiskUsage } from './pages/DiskUsage'
import { FirstLaunch }   from './pages/FirstLaunch'
import { Login }         from './pages/Login'
import type { Settings } from './types'
import { applyAccentPreset } from './lib/accentPresets'
import { useI18n } from './i18n'
import { Toaster, toast } from 'sonner'

// Watches the current user's unread @mentions and pops a floating toast
// (bottom-right) whenever a NEW one arrives. Silent on first load so it never
// replays the backlog. Must live inside the router (uses navigate).
function MentionWatcher() {
  const navigate = useNavigate()
  const { mentions, loaded } = useMentionsFeed()
  const { prefs } = useWorkProfile()
  const enabled = useRef(prefs.notifyMention)
  enabled.current = prefs.notifyMention
  const seen = useRef<Set<string> | null>(null)
  useEffect(() => {
    if (!loaded) return
    // First real snapshot seeds `seen` silently so the backlog isn't replayed.
    if (seen.current === null) { seen.current = new Set(mentions.map(m => m.id)); return }
    for (const m of mentions) {
      if (seen.current.has(m.id)) continue
      seen.current.add(m.id)
      if (m.read) continue   // already-read history that scrolled in — don't toast
      if (!enabled.current) continue   // turned off in the work profile (ADR 0043)
      toast(`${m.from_user} t'a mentionné`, {
        description: m.text,
        position: 'bottom-right',
        duration: 6000,
        action: { label: 'Voir', onClick: () => navigate('/') },
      })
      // Native Windows notification (bottom-right + system sound), even when
      // FLUX isn't the focused window.
      void window.electronAPI?.showNotification?.(`${m.from_user} t'a mentionné`, m.text)
    }
  }, [mentions, loaded, navigate])
  return null
}

// Polls the activity feed and pops a floating toast + native notification for
// every NEW event the work profile asks for (ADR 0043): followed (favorite) tasks,
// and optionally publishes / comments / errors of other artists in the active
// project. Silent on the very first poll so the backlog isn't replayed.
function FavoriteWatcher() {
  const navigate = useNavigate()
  const { favorites } = useFavorites()
  const { events, loaded } = useActivityFeed()
  const { prefs } = useWorkProfile()
  const { project } = useProject()
  const { settings } = useSettings()
  const seen = useRef<Set<string> | null>(null)
  const favRef = useRef<string[]>(favorites)
  useEffect(() => { favRef.current = favorites }, [favorites])
  const ctxRef = useRef({ prefs, project, username: settings?.username ?? '' })
  ctxRef.current = { prefs, project, username: settings?.username ?? '' }
  useEffect(() => {
    if (!loaded) return
    // First real snapshot seeds `seen` silently so the backlog isn't replayed.
    if (seen.current === null) { seen.current = new Set(events.map(e => e.id)); return }
    for (const e of events) {
      if (seen.current.has(e.id)) continue
      seen.current.add(e.id)
      if (!e.file || !e.project) continue
      const parsed = parseFluxFilename(e.file)
      const favs = favRef.current
      const match = !!parsed && favs.some(k => eventMatchesFavorite(k, {
        project: e.project!, class: parsed.class, name: parsed.name,
        task: parsed.task, instance: parsed.instance,
      }))
      const reason = notificationReason(e, { ...ctxRef.current, followed: match })
      if (!reason) continue
      const title = reason === 'followed'
        ? e.action === 'comment' ? `${e.user} · commentaire sur favori` : `${e.user} · ${e.action} sur favori`
        : reason === 'error' ? `${e.user} · erreur` : `${e.user} · ${e.action}`
      const body  = e.file
      toast(title, {
        description: body,
        position: 'bottom-right',
        duration: 6000,
        action: { label: 'Activity', onClick: () => navigate('/activity') },
      })
      void window.electronAPI?.showNotification?.(title, body)
    }
  }, [events, loaded, navigate])
  return null
}

// Inner shell — only mounted after first-launch wizard completes.
// Hooks that poll the backend (useActivity, useDccStatus) live here so they
// never fire while FLUX_ROOT is unset, which would cause backend 500s.
// A page dragged out of the main window (U4): no sidebar, no status bar, no
// notification watchers (the main window already shows them).
const DETACHED = new URLSearchParams(window.location.search).get('detached') === '1'

function AppShell({ settings }: { settings: Settings }) {
  const dccStatus          = useDccStatus()
  const { unreadCount }    = useActivity()
  const [showLogin, setShowLogin]         = useState(false)

  return (
    <HashRouter>
      <WorkProfileProvider>
      {!DETACHED && <StartPageRedirect />}
      <div className="flex flex-col h-screen overflow-hidden" style={{ backgroundColor: 'var(--color-bg)' }}>
        {showLogin && <Login onDone={() => setShowLogin(false)} />}

        <TitleBar
          username={settings?.username ?? null}
          unreadCount={unreadCount}
          onUserChange={() => setShowLogin(true)}
        />

        <BackendBanner />

        <div className="flex flex-1 min-h-0">
          {!DETACHED && <Sidebar dccStatus={dccStatus} unreadCount={unreadCount} />}

          <main className="flex-1 min-h-0 overflow-hidden" style={{ display: 'flex', flexDirection: 'column', background: 'var(--paper)' }}>
            <PageErrorBoundary>
            <Routes>
              <Route path="/"          element={<Hub />} />
              <Route path="/publisher" element={<Publisher />} />
              <Route path="/action-publish" element={<ActionPublish />} />
              <Route path="/action-graph" element={<ActionGraph />} />
              <Route path="/activity"  element={<Activity />} />
              <Route path="/projects"  element={<Projects />} />
              <Route path="/shelf"     element={<ShelfManager />} />
              <Route path="/usd"       element={<UsdPage />} />
              <Route path="/templates" element={<TemplateEditor />} />
              <Route path="/production" element={<Production />} />
              <Route path="/calendar"  element={<Calendar />} />
              <Route path="/advanced"  element={<AdvancedSettings />} />
              <Route path="/disk"      element={<DiskUsage />} />
            </Routes>
            </PageErrorBoundary>
          </main>
        </div>

        {!DETACHED && <StatusBar dccStatus={dccStatus} />}
        {!DETACHED && <MentionWatcher />}
        {!DETACHED && <FavoriteWatcher />}
        <WorkProfileDialog />
      </div>
      <Toaster
        position="top-center"
        theme="dark"
        toastOptions={{
          style: {
            background: 'var(--paper-2)',
            color: 'var(--ink)',
            border: '1px solid var(--rule-2)',
            fontFamily: 'var(--sans)',
            fontSize: 11,
            boxShadow: 'var(--shadow-md)',
          },
          classNames: {
            success: 'flux-toast-ok',
            warning: 'flux-toast-warn',
            error:   'flux-toast-err',
          },
        }}
      />
      </WorkProfileProvider>
    </HashRouter>
  )
}

// Full-screen reconnect state, shown when settings can't load because the backend
// is not reachable. Auto-recovers: useBackendStatus dispatches 'flux:refresh' on
// 'ready', which makes useSettings re-fetch and this screen unmount.
function BackendDownScreen() {
  const { t } = useI18n()
  const { status, restart } = useBackendStatus()
  const reconnecting = status === 'starting' || status === 'retrying'
  return (
    <div className="flex flex-col items-center justify-center h-screen gap-3" style={{ backgroundColor: 'var(--color-bg)' }}>
      <span className="text-sm" style={{ color: reconnecting ? 'var(--ink, #cac8c5)' : '#e0836f' }}>
        {reconnecting ? t('backend.retrying') : t('backend.down')}
      </span>
      <span className="text-xs text-gray-500" style={{ maxWidth: 440, textAlign: 'center', lineHeight: 1.5 }}>
        {t('backend.downHint')}
      </span>
      <button
        onClick={restart}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 6, marginTop: 4,
          padding: '6px 14px', borderRadius: 6, cursor: 'pointer',
          background: 'var(--paper-2, #1b1a18)', color: 'var(--ink, #cac8c5)',
          border: '1px solid var(--rule-2, #2a2826)', fontFamily: 'var(--sans)', fontSize: 12,
        }}
      >
        {t('backend.retry')}
      </button>
      <span className="text-xs text-gray-600">Ctrl+Shift+I · DevTools · %APPDATA%\Flux\logs\</span>
    </div>
  )
}

export function App() {
  const { settings, loading } = useSettings()

  // Apply theme CSS vars from settings
  useEffect(() => {
    if (!settings?.theme) return
    const root = document.documentElement
    root.style.setProperty('--color-bg',      settings.theme.bg)
    root.style.setProperty('--color-surface', settings.theme.surface)
    root.style.setProperty('--color-fg',      settings.theme.fg)
    root.style.setProperty('--color-accent',  settings.theme.accent)
    // Restore accent preset (stored as preset key, e.g. "blue")
    applyAccentPreset(settings.theme.accent)
  }, [settings])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen" style={{ backgroundColor: 'var(--color-bg)' }}>
        <span className="text-sm text-gray-500">Chargement…</span>
      </div>
    )
  }

  // Backend injoignable : écran de reconnexion piloté par le statut du shell.
  // Le hook redéclenche un refresh dès que le backend revient (recovery auto),
  // donc cet écran se referme tout seul sans relancer FLUX.
  if (!settings) {
    return <BackendDownScreen />
  }

  // Premier lancement — pas de workspace configuré
  if (settings.first_launch) {
    return <FirstLaunch />
  }

  return (
    <FeedsProvider>
      <AppShell settings={settings} />
    </FeedsProvider>
  )
}
