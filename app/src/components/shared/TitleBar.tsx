import { useState, useEffect } from 'react'
import { Bell, Settings2, ChevronDown, X, Minus, Maximize2, FolderOpen, RefreshCw } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Avatar, Popover, PopoverTrigger, PopoverContent, PopoverClose } from './ui'
import { api } from '../../api/client'
import { ACCENT_PRESETS, applyAccentPreset } from '../../lib/accentPresets'

interface Props {
  username: string | null
  unreadCount: number
  onSettings: () => void
  onUserChange: () => void
}

/* ── bouton traffic light ── */
function WinBtn({ hoverBg, icon: Icon, action }: {
  hoverBg: string; icon: LucideIcon; action: () => void
}) {
  const [hov, setHov] = useState(false)
  return (
    <div
      onClick={action}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        width: 13, height: 13, borderRadius: '50%',
        background: hov ? hoverBg : 'var(--ink-4)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        cursor: 'default', flexShrink: 0,
        transition: 'background 0.12s',
      }}
    >
      {hov && <Icon size={7} strokeWidth={2.5} color="rgba(0,0,0,0.65)" />}
    </div>
  )
}


/* ── popover paramètres ── */
function SettingsPopover({ username }: { username: string }) {
  const [workspace, setWorkspace]   = useState('')
  const [version, setVersion]       = useState('')
  const [changing, setChanging]     = useState(false)
  const [accentKey, setAccentKey]   = useState('orange')

  useEffect(() => {
    api.getSettings().then(s => {
      setWorkspace(s.workspace ?? '')
      const stored = s.theme?.accent ?? 'orange'
      const key = ACCENT_PRESETS.some(p => p.key === stored) ? stored : 'orange'
      setAccentKey(key)
    }).catch(() => {})
    window.electronAPI?.getAppVersion().then(setVersion).catch(() => {})
  }, [])

  const handleAccent = (key: string) => {
    setAccentKey(key)
    applyAccentPreset(key)
    void api.updateSettings({ theme_accent: key })
  }

  const handleChangeWorkspace = async () => {
    const path = await window.electronAPI?.openFolder()
    if (!path) return
    setChanging(true)
    try {
      await api.updateSettings({ workspace: path })
      window.location.reload()
    } catch {
      setChanging(false)
    }
  }

  return (
    <div style={{ width: 280, display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.11em', textTransform: 'uppercase', color: 'var(--ink-2)' }}>
          Paramètres
        </div>
        <PopoverClose
          style={{ cursor: 'pointer', width: 20, height: 20, borderRadius: 5, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--ink-3)', background: 'transparent', border: 'none' }}
          onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'var(--paper)' }}
          onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent' }}
        >
          <X size={12} strokeWidth={2} />
        </PopoverClose>
      </div>

      {/* utilisateur courant */}
      <div style={{ borderTop: '1px solid var(--rule)', paddingTop: 8 }}>
        <div style={{ fontFamily: 'var(--mono)', fontSize: 8, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--ink-4)', marginBottom: 4 }}>UTILISATEUR</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Avatar ch={username[0].toUpperCase()} size={20} />
          <span style={{ fontSize: 11, color: 'var(--ink)' }}>{username}</span>
        </div>
      </div>

      {/* workspace */}
      <div style={{ borderTop: '1px solid var(--rule)', paddingTop: 8 }}>
        <div style={{ fontFamily: 'var(--mono)', fontSize: 8, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--ink-4)', marginBottom: 6 }}>WORKSPACE</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
          <FolderOpen size={12} strokeWidth={1.75} color="var(--ink-4)" />
          <span style={{
            flex: 1, fontSize: 10, fontFamily: 'var(--mono)', color: workspace ? 'var(--ink-2)' : 'var(--ink-4)',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            fontStyle: workspace ? 'normal' : 'italic',
          }}>{workspace || '—'}</span>
        </div>
        <div
          onClick={() => !changing && void handleChangeWorkspace()}
          style={{
            display: 'flex', alignItems: 'center', gap: 6,
            padding: '6px 10px', borderRadius: 7,
            border: '1px solid var(--rule-2)',
            background: 'var(--paper)',
            fontSize: 11, color: 'var(--ink-3)',
            cursor: changing ? 'default' : 'pointer',
            opacity: changing ? 0.5 : 1,
            transition: 'border-color 0.12s, color 0.12s',
          }}
          onMouseEnter={e => { if (!changing) { const el = e.currentTarget as HTMLElement; el.style.borderColor = 'var(--accent)'; el.style.color = 'var(--accent-hi)' } }}
          onMouseLeave={e => { if (!changing) { const el = e.currentTarget as HTMLElement; el.style.borderColor = 'var(--rule-2)'; el.style.color = 'var(--ink-3)' } }}
        >
          {changing
            ? <RefreshCw size={11} strokeWidth={1.75} style={{ animation: 'spin 1s linear infinite' }} />
            : <FolderOpen size={11} strokeWidth={1.75} />
          }
          {changing ? 'Changement…' : 'Changer de répertoire…'}
        </div>
      </div>

      {/* accent color */}
      <div style={{ borderTop: '1px solid var(--rule)', paddingTop: 8 }}>
        <div style={{ fontFamily: 'var(--mono)', fontSize: 8, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--ink-4)', marginBottom: 8 }}>COULEUR D'ACCENT</div>
        <div style={{ display: 'flex', gap: 6 }}>
          {ACCENT_PRESETS.map(p => {
            const active = accentKey === p.key
            return (
              <div
                key={p.key}
                title={p.label}
                onClick={() => handleAccent(p.key)}
                style={{
                  flex: 1,
                  height: 22,
                  borderRadius: 5,
                  background: p.accent,
                  border: active ? '2px solid var(--ink)' : '2px solid transparent',
                  outline: active ? '1px solid ' + p.accent : 'none',
                  outlineOffset: 1,
                  cursor: 'pointer',
                  transition: 'border-color 0.12s, transform 0.08s',
                  transform: active ? 'scaleY(1.12)' : 'scaleY(1)',
                  boxShadow: active ? '0 2px 8px rgba(0,0,0,0.4)' : 'none',
                }}
              />
            )
          })}
        </div>
      </div>

      {/* version */}
      {version && (
        <div style={{ borderTop: '1px solid var(--rule)', paddingTop: 8, display: 'flex', justifyContent: 'space-between' }}>
          <div style={{ fontFamily: 'var(--mono)', fontSize: 8, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--ink-4)' }}>VERSION</div>
          <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)' }}>{version}</div>
        </div>
      )}
    </div>
  )
}

export function TitleBar({ username, unreadCount, onSettings, onUserChange }: Props) {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const user = username ?? 'User'

  return (
    <div className="drag-region" style={{
      height: 42, padding: '0 14px',
      borderBottom: '1px solid var(--rule)',
      background: 'var(--bg-deep)',
      display: 'flex', alignItems: 'center', gap: 10,
      position: 'relative', flexShrink: 0,
    }}>

      {/* logo */}
      <div className="no-drag" style={{
        width: 22, height: 22,
        background: 'var(--accent-soft)',
        border: '1px solid var(--accent)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontFamily: 'var(--mono)', fontWeight: 700, fontSize: 11,
        color: 'var(--accent-hi)', borderRadius: 6, flexShrink: 0,
        boxShadow: 'var(--shadow-xs)',
      }}>F</div>

      <div style={{ display: 'flex', alignItems: 'baseline', gap: 7 }}>
        <span style={{ fontFamily: 'var(--mono)', fontWeight: 600, fontSize: 12, letterSpacing: '0.14em', color: 'var(--ink)' }}>FLUX</span>
        <span style={{ fontSize: 11, color: 'var(--ink-3)', letterSpacing: '0.02em' }}>Pipeline Tool</span>
      </div>

      <div style={{ flex: 1 }} />

      {/* notif bell */}
      <div className="no-drag" style={{ position: 'relative' }}>
        <div style={{
          width: 28, height: 28, borderRadius: 7,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: 'var(--ink-3)', cursor: 'pointer',
          transition: 'background 0.1s, color 0.1s',
        }}
          onMouseEnter={e => { const el = e.currentTarget as HTMLElement; el.style.background = 'var(--paper-2)'; el.style.color = 'var(--ink)' }}
          onMouseLeave={e => { const el = e.currentTarget as HTMLElement; el.style.background = 'transparent'; el.style.color = 'var(--ink-3)' }}
        >
          <Bell size={14} strokeWidth={1.75} />
        </div>
        {unreadCount > 0 && (
          <div style={{
            position: 'absolute', top: 2, right: 2,
            minWidth: 14, height: 14, padding: '0 3px',
            background: 'var(--accent-soft)', border: '1px solid var(--accent)',
            borderRadius: 999, fontFamily: 'var(--mono)', fontSize: 8,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: 'var(--accent-hi)', fontWeight: 600,
            boxShadow: 'var(--shadow-xs)', pointerEvents: 'none',
          }}>{unreadCount}</div>
        )}
      </div>

      {/* settings gear */}
      <Popover onOpenChange={open => { setSettingsOpen(open); if (open) onSettings() }}>
        <PopoverTrigger asChild>
          <div
            className="no-drag"
            style={{
              width: 28, height: 28,
              border: '1px solid ' + (settingsOpen ? 'var(--rule-2)' : 'transparent'),
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: settingsOpen ? 'var(--ink)' : 'var(--ink-3)',
              background: settingsOpen ? 'var(--paper-2)' : 'transparent',
              borderRadius: 7, cursor: 'pointer',
              transition: 'background 0.12s, color 0.12s',
            }}
          >
            <Settings2 size={14} strokeWidth={1.75} />
          </div>
        </PopoverTrigger>
        <PopoverContent side="bottom" align="end" sideOffset={6} style={{ width: 'auto' }}>
          <SettingsPopover username={user} />
        </PopoverContent>
      </Popover>

      {/* user pill */}
      <div
        className="no-drag"
        onClick={() => onUserChange()}
        style={{
          display: 'flex', alignItems: 'center', gap: 6,
          padding: '3px 10px 3px 4px',
          border: '1px solid var(--rule-2)',
          borderRadius: 999,
          background: 'var(--paper-2)',
          cursor: 'pointer',
          boxShadow: 'var(--shadow-xs)',
          transition: 'border-color 0.12s, background 0.12s',
        }}
        onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--accent)'; (e.currentTarget as HTMLElement).style.background = 'var(--accent-soft)' }}
        onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--rule-2)'; (e.currentTarget as HTMLElement).style.background = 'var(--paper-2)' }}
      >
        <Avatar ch={user[0].toUpperCase()} size={20} />
        <span style={{ fontSize: 11, color: 'var(--ink)', fontWeight: 500 }}>{user}</span>
        <ChevronDown size={10} strokeWidth={2} color="var(--ink-3)" />
      </div>

      {/* ── traffic lights ── */}
      <div className="no-drag" style={{ display: 'flex', gap: 7, alignItems: 'center', marginLeft: 4, flexShrink: 0 }}>
        <WinBtn hoverBg="#ffbd2e" icon={Minus}     action={() => window.electronAPI?.windowMinimize()} />
        <WinBtn hoverBg="#28c940" icon={Maximize2} action={() => window.electronAPI?.windowMaximize()} />
        <WinBtn hoverBg="#ff5f57" icon={X}         action={() => window.electronAPI?.windowClose()} />
      </div>

    </div>
  )
}
