// App.tsx — shell principal : routing, TitleBar, Sidebar, StatusBar.

import { useEffect, useState } from 'react'
import { HashRouter, Route, Routes } from 'react-router-dom'
import { TitleBar }  from './components/shared/TitleBar'
import { Sidebar }   from './components/shared/Sidebar'
import { StatusBar } from './components/shared/StatusBar'
import { useDccStatus }  from './hooks/useDccStatus'
import { useActivity }   from './hooks/useActivity'
import { useSettings }   from './hooks/useSettings'
import { Hub }           from './pages/Hub'
import { Publisher }     from './pages/Publisher'
import { Importer }      from './pages/Importer'
import { Activity }      from './pages/Activity'
import { Projects }      from './pages/Projects'
import { ShelfManager }  from './pages/ShelfManager'
import { FirstLaunch }   from './pages/FirstLaunch'
import { Login }         from './pages/Login'
import type { Settings } from './types'
import { applyAccentPreset } from './lib/accentPresets'
import { Toaster } from 'sonner'

// Inner shell — only mounted after first-launch wizard completes.
// Hooks that poll the backend (useActivity, useDccStatus) live here so they
// never fire while FLUX_ROOT is unset, which would cause backend 500s.
function AppShell({ settings }: { settings: Settings }) {
  const dccStatus          = useDccStatus()
  const { unreadCount }    = useActivity()
  const [_showSettings, setShowSettings] = useState(false)
  const [showLogin, setShowLogin]         = useState(false)

  return (
    <HashRouter>
      <div className="flex flex-col h-screen overflow-hidden" style={{ backgroundColor: 'var(--color-bg)' }}>
        {showLogin && <Login onDone={() => setShowLogin(false)} />}

        <TitleBar
          username={settings?.username ?? null}
          unreadCount={unreadCount}
          onSettings={() => setShowSettings(true)}
          onUserChange={() => setShowLogin(true)}
        />

        <div className="flex flex-1 min-h-0">
          <Sidebar dccStatus={dccStatus} unreadCount={unreadCount} />

          <main className="flex-1 min-h-0 overflow-hidden" style={{ display: 'flex', flexDirection: 'column', background: 'var(--paper)' }}>
            <Routes>
              <Route path="/"          element={<Hub />} />
              <Route path="/publisher" element={<Publisher />} />
              <Route path="/importer"  element={<Importer />} />
              <Route path="/activity"  element={<Activity />} />
              <Route path="/projects"  element={<Projects />} />
              <Route path="/shelf"     element={<ShelfManager />} />
            </Routes>
          </main>
        </div>

        <StatusBar dccStatus={dccStatus} />
      </div>
      <Toaster
        position="bottom-right"
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
        }}
      />
    </HashRouter>
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

  // Backend injoignable — afficher l'erreur plutôt qu'une UI vide
  if (!settings) {
    return (
      <div className="flex flex-col items-center justify-center h-screen gap-3" style={{ backgroundColor: 'var(--color-bg)' }}>
        <span className="text-sm text-red-400">Backend non disponible</span>
        <span className="text-xs text-gray-500">Vérifier les logs : %APPDATA%\Flux\logs\</span>
        <span className="text-xs text-gray-600">Ctrl+Shift+I pour les DevTools</span>
      </div>
    )
  }

  // Premier lancement — pas de workspace configuré
  if (settings.first_launch) {
    return <FirstLaunch />
  }

  return <AppShell settings={settings} />
}
