import { useState, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { Bell, Settings2, ChevronDown, X, Minus, Maximize2, FolderOpen, RefreshCw, RotateCcw, ChevronsRight, SlidersHorizontal, Pin } from 'lucide-react'
import { createPortal } from 'react-dom'
import type { LucideIcon } from 'lucide-react'
import { Avatar, Popover, PopoverTrigger, PopoverContent, PopoverClose } from './ui'
import { FluxLogo } from './Logo'
import { Console } from './Console'
import { api } from '../../api/client'
import { useI18n } from '../../i18n'
import { ACCENT_PRESETS, applyAccentPreset } from '../../lib/accentPresets'
import { SOFTWARE } from '../../lib/dccs'
import { useEnabledDccs } from '../../hooks/useEnabledDccs'

interface Props {
  username: string | null
  unreadCount: number
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


// Console log levels the user can recolor + a theme-neutral swatch default shown
// when there is no override yet (picking one writes the override).
const LOG_LEVELS: { key: string; labelKey: string; def: string }[] = [
  { key: 'debug',   labelKey: 'log.debug',   def: '#7a7f87' },
  { key: 'info',    labelKey: 'log.info',    def: '#c8ccd4' },
  { key: 'warning', labelKey: 'log.warning', def: '#f5a623' },
  { key: 'error',   labelKey: 'log.error',   def: '#e5484d' },
]

/* ── popover paramètres ── */
function SettingsPopover({ username }: { username: string }) {
  const { t, lang, setLang } = useI18n()
  const [workspace, setWorkspace]   = useState('')
  const [version, setVersion]       = useState('')
  const [changing, setChanging]     = useState(false)
  const [accentKey, setAccentKey]   = useState('orange')
  const [logColors, setLogColors]   = useState<Record<string, string>>({})
  const { isEnabled: isDccEnabled, setEnabled: setEnabledDccs } = useEnabledDccs()
  const [advancedAsk, setAdvancedAsk] = useState(false)
  const navigate = useNavigate()

  // Every DCC stays listed here; unchecked ones are hidden from Launcher + StatusBar.
  const toggleDcc = (key: string) => {
    const current = SOFTWARE.map(s => s.key).filter(isDccEnabled)
    const next = current.includes(key) ? current.filter(k => k !== key) : [...current, key]
    void setEnabledDccs(next).catch(() => {})
  }

  useEffect(() => {
    api.getSettings().then(s => {
      setWorkspace(s.workspace ?? '')
      const stored = s.theme?.accent ?? 'orange'
      const key = ACCENT_PRESETS.some(p => p.key === stored) ? stored : 'orange'
      setAccentKey(key)
      setLogColors(s.log_colors ?? {})
    }).catch(() => {})
    window.electronAPI?.getAppVersion().then(setVersion).catch(() => {})
  }, [])

  const handleAccent = (key: string) => {
    setAccentKey(key)
    applyAccentPreset(key)
    void api.updateSettings({ theme_accent: key })
  }

  // Persist + broadcast console log-color overrides so the Console updates live.
  const pushLogColors = (next: Record<string, string>) => {
    setLogColors(next)
    window.dispatchEvent(new CustomEvent('flux:log-colors', { detail: next }))
    void api.updateSettings({ log_colors: next })
  }
  const handleLogColor = (level: string, color: string) => pushLogColors({ ...logColors, [level]: color })
  const handleResetLogColors = () => pushLogColors({})

  const handleResetUi = () => {
    try { localStorage.removeItem('flux.ui.publisherRightWidth') } catch { /* blocked storage */ }
    window.dispatchEvent(new Event('flux:reset-ui'))
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
          {t('settings.title')}
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
        <div style={{ fontFamily: 'var(--mono)', fontSize: 8, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--ink-4)', marginBottom: 4 }}>{t('settings.user')}</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Avatar ch={username[0].toUpperCase()} size={20} />
          <span style={{ fontSize: 11, color: 'var(--ink)' }}>{username}</span>
        </div>
      </div>

      {/* workspace */}
      <div style={{ borderTop: '1px solid var(--rule)', paddingTop: 8 }}>
        <div style={{ fontFamily: 'var(--mono)', fontSize: 8, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--ink-4)', marginBottom: 6 }}>{t('settings.workspace')}</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
          <FolderOpen size={12} strokeWidth={1.75} color="var(--ink-4)" />
          <span style={{
            flex: 1, fontSize: 10, fontFamily: 'var(--mono)', color: workspace ? 'var(--ink-2)' : 'var(--ink-4)',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            fontStyle: workspace ? 'normal' : 'italic',
          }}>{workspace || '-'}</span>
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
          {changing ? t('settings.changing') : t('settings.changeDir')}
        </div>
      </div>

      {/* accent color */}
      <div style={{ borderTop: '1px solid var(--rule)', paddingTop: 8 }}>
        <div style={{ fontFamily: 'var(--mono)', fontSize: 8, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--ink-4)', marginBottom: 8 }}>{t('settings.accent')}</div>
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

      {/* couleurs des logs */}
      <div style={{ borderTop: '1px solid var(--rule)', paddingTop: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <div style={{ fontFamily: 'var(--mono)', fontSize: 8, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--ink-4)' }}>{t('settings.logColors')}</div>
          {Object.keys(logColors).length > 0 && (
            <span
              onClick={handleResetLogColors}
              style={{ fontSize: 9, color: 'var(--ink-4)', cursor: 'pointer' }}
              onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = 'var(--accent-hi)' }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = 'var(--ink-4)' }}
            >{t('settings.logColorsReset')}</span>
          )}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {LOG_LEVELS.map(l => (
            <div key={l.key} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <input
                type="color"
                value={logColors[l.key] || l.def}
                onChange={e => handleLogColor(l.key, e.target.value)}
                style={{ width: 26, height: 20, padding: 0, border: '1px solid var(--rule-2)', borderRadius: 5, background: 'transparent', cursor: 'pointer' }}
              />
              <span style={{ fontSize: 11, color: 'var(--ink-2)', flex: 1 }}>{t(l.labelKey)}</span>
              {logColors[l.key] && (
                <span style={{ fontFamily: 'var(--mono)', fontSize: 9, color: 'var(--ink-4)' }}>{logColors[l.key]}</span>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* logiciels (per-user enabled DCCs) */}
      <div style={{ borderTop: '1px solid var(--rule)', paddingTop: 8 }}>
        <div style={{ fontFamily: 'var(--mono)', fontSize: 8, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--ink-4)', marginBottom: 6 }}>{t('settings.dccs')}</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 8px' }}>
          {SOFTWARE.map(s => (
            <label key={s.key} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--ink-2)', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={isDccEnabled(s.key)}
                onChange={() => toggleDcc(s.key)}
                style={{ accentColor: 'var(--accent)', cursor: 'pointer', margin: 0 }}
              />
              {s.name}
            </label>
          ))}
        </div>
      </div>

      {/* interface */}
      <div style={{ borderTop: '1px solid var(--rule)', paddingTop: 8 }}>
        <div style={{ fontFamily: 'var(--mono)', fontSize: 8, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--ink-4)', marginBottom: 6 }}>{t('settings.interface')}</div>
        <div
          onClick={handleResetUi}
          style={{
            display: 'flex', alignItems: 'center', gap: 6,
            padding: '6px 10px', borderRadius: 7,
            border: '1px solid var(--rule-2)', background: 'var(--paper)',
            fontSize: 11, color: 'var(--ink-3)', cursor: 'pointer',
            transition: 'border-color 0.12s, color 0.12s',
          }}
          onMouseEnter={e => { const el = e.currentTarget as HTMLElement; el.style.borderColor = 'var(--accent)'; el.style.color = 'var(--accent-hi)' }}
          onMouseLeave={e => { const el = e.currentTarget as HTMLElement; el.style.borderColor = 'var(--rule-2)'; el.style.color = 'var(--ink-3)' }}
        >
          <RotateCcw size={11} strokeWidth={1.75} />
          {t('settings.resetUi')}
        </div>
      </div>

      {/* langue */}
      <div style={{ borderTop: '1px solid var(--rule)', paddingTop: 8 }}>
        <div style={{ fontFamily: 'var(--mono)', fontSize: 8, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--ink-4)', marginBottom: 6 }}>{t('settings.language')}</div>
        <div style={{ display: 'flex', gap: 6 }}>
          {(['fr', 'en'] as const).map(l => {
            const active = lang === l
            return (
              <div
                key={l}
                onClick={() => setLang(l)}
                style={{
                  flex: 1, textAlign: 'center',
                  padding: '6px 10px', borderRadius: 7,
                  border: '1px solid ' + (active ? 'var(--accent)' : 'var(--rule-2)'),
                  background: active ? 'var(--accent-soft)' : 'var(--paper)',
                  color: active ? 'var(--accent-hi)' : 'var(--ink-3)',
                  fontSize: 11, fontWeight: active ? 600 : 400, cursor: 'pointer',
                  transition: 'border-color 0.12s, color 0.12s, background 0.12s',
                }}
              >
                {l === 'fr' ? 'Français' : 'English'}
              </div>
            )
          })}
        </div>
      </div>

      {/* parametres avances (N8) */}
      <div style={{ borderTop: '1px solid var(--rule)', paddingTop: 8 }}>
        <div
          onClick={() => setAdvancedAsk(true)}
          style={{
            display: 'flex', alignItems: 'center', gap: 6,
            padding: '6px 10px', borderRadius: 7,
            border: '1px solid var(--rule-2)', background: 'var(--paper)',
            fontSize: 11, color: 'var(--ink-3)', cursor: 'pointer',
          }}
        >
          <SlidersHorizontal size={11} strokeWidth={1.75} />
          Parametres avances
        </div>
      </div>
      {advancedAsk && createPortal(
        <AdvancedConfirm
          onCancel={() => setAdvancedAsk(false)}
          onConfirm={() => { setAdvancedAsk(false); navigate('/advanced') }}
        />, document.body)}

      {/* version */}
      {version && (
        <div style={{ borderTop: '1px solid var(--rule)', paddingTop: 8, display: 'flex', justifyContent: 'space-between' }}>
          <div style={{ fontFamily: 'var(--mono)', fontSize: 8, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--ink-4)' }}>{t('settings.version')}</div>
          <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)' }}>{version}</div>
        </div>
      )}

    </div>
  )
}

/* ── "Parametres avances": warning, then type Understand (N8) ── */
const ADVANCED_PHRASE = 'Understand'

function AdvancedConfirm({ onConfirm, onCancel }: { onConfirm: () => void; onCancel: () => void }) {
  const [typed, setTyped] = useState('')
  const match = typed === ADVANCED_PHRASE
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onCancel])
  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', zIndex: 10000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: 'var(--paper)', border: '1px solid var(--rule-2)', borderRadius: 10, padding: '22px 24px', minWidth: 340, maxWidth: 420, boxShadow: 'var(--shadow)' }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)', marginBottom: 10 }}>Parametres avances</div>
        <div style={{ fontSize: 11, color: 'var(--ink-3)', marginBottom: 14, lineHeight: 1.5 }}>
          Modifier ces reglages peut casser le projet (unites USD, stockage des versions, publish).
          A ne toucher que si tu sais ce que tu fais.
        </div>
        <div style={{ fontSize: 11, color: 'var(--ink-2)', marginBottom: 8 }}>
          Tape <code style={{ fontFamily: 'var(--mono)', fontSize: 11, background: 'var(--paper-2)', border: '1px solid var(--rule)', borderRadius: 4, padding: '1px 5px', color: 'var(--ink)' }}>{ADVANCED_PHRASE}</code> pour continuer.
        </div>
        <input
          autoFocus value={typed} onChange={e => setTyped(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && match) onConfirm() }}
          placeholder={ADVANCED_PHRASE} spellCheck={false} autoCapitalize="off" autoCorrect="off"
          style={{ width: '100%', boxSizing: 'border-box', marginBottom: 18, padding: '7px 10px', fontSize: 12, fontFamily: 'var(--mono)',
                   background: 'var(--paper-2)', color: 'var(--ink)', border: `1px solid ${match ? 'var(--accent)' : 'var(--rule-2)'}`, borderRadius: 6, outline: 'none' }}
        />
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <div className="btn ghost" onClick={onCancel} style={{ cursor: 'pointer' }}>Annuler</div>
          <div className="btn primary" onClick={() => { if (match) onConfirm() }}
               style={{ cursor: match ? 'pointer' : 'not-allowed', opacity: match ? 1 : 0.5 }}>
            Ouvrir
          </div>
        </div>
      </div>
    </div>
  )
}

const IS_DETACHED_WINDOW = new URLSearchParams(window.location.search).get('detached') === '1'

/* ── slide-to-confirm quit ── */
function SlideToConfirm({ onConfirm }: { onConfirm: () => void }) {
  const { t } = useI18n()
  const trackW = 300
  const handleW = 50
  const maxX = trackW - handleW - 6
  const [x, setX] = useState(0)
  const [done, setDone] = useState(false)

  const startDrag = (e: React.MouseEvent) => {
    e.preventDefault()
    const origin = e.clientX - x
    const move = (ev: MouseEvent) => setX(Math.min(Math.max(ev.clientX - origin, 0), maxX))
    const up = (ev: MouseEvent) => {
      document.removeEventListener('mousemove', move)
      document.removeEventListener('mouseup', up)
      const nx = Math.min(Math.max(ev.clientX - origin, 0), maxX)
      if (nx >= maxX - 4) { setX(maxX); setDone(true); setTimeout(onConfirm, 120) }
      else setX(0)
    }
    document.addEventListener('mousemove', move)
    document.addEventListener('mouseup', up)
  }

  const pct = maxX > 0 ? x / maxX : 0
  return (
    <div style={{
      position: 'relative', width: trackW, height: 50, borderRadius: 25,
      background: 'var(--bg-deep)', border: '1px solid var(--rule-2)',
      boxShadow: 'var(--shadow-inset)', overflow: 'hidden', userSelect: 'none',
    }}>
      <div style={{
        position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 12, color: 'var(--ink-4)', opacity: 1 - pct, pointerEvents: 'none',
      }}>
        {t('titlebar.slideToClose')}
      </div>
      <div style={{
        position: 'absolute', top: 0, bottom: 0, left: 0, width: x + handleW,
        background: 'var(--accent-soft)', borderRadius: 25, transition: done ? 'width 0.12s' : 'none',
      }} />
      <div
        onMouseDown={startDrag}
        style={{
          position: 'absolute', top: 3, left: x + 3, width: handleW - 6, height: 44,
          borderRadius: '50%', background: 'var(--accent)', cursor: 'grab',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          boxShadow: 'var(--shadow-sm)', transition: x === 0 && !done ? 'left 0.12s' : 'none',
        }}
      >
        <ChevronsRight size={18} strokeWidth={2.5} color="var(--accent-hi)" />
      </div>
    </div>
  )
}

export function TitleBar({ username, unreadCount, onUserChange }: Props) {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [settingsHov,  setSettingsHov]  = useState(false)
  const [bellHov,      setBellHov]      = useState(false)
  const [refreshing,   setRefreshing]   = useState(false)
  const [pinned,       setPinned]       = useState(false)
  const [pinHov,       setPinHov]       = useState(false)
  const [refreshDone,  setRefreshDone]  = useState(false)
  const [confirmClose, setConfirmClose] = useState(false)
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const { t } = useI18n()
  const user = username ?? 'User'

  // Refresh without restart: broadcast a global event that the shell hooks
  // (settings, activity, DCC paths) listen for and re-fetch on.
  const handleRefresh = () => {
    if (refreshing) return
    setRefreshing(true)
    setRefreshDone(false)
    window.dispatchEvent(new Event('flux:refresh'))
    // Spin ~600ms, then flash "Refresh effectué" for 2s just left of the button.
    setTimeout(() => {
      setRefreshing(false)
      setRefreshDone(true)
      setTimeout(() => setRefreshDone(false), 2000)
    }, 600)
  }

  return (
    <div className="drag-region" style={{
      height: 42, padding: '0 14px',
      borderBottom: '1px solid var(--rule)',
      background: 'var(--bg-deep)',
      display: 'flex', alignItems: 'center', gap: 10,
      position: 'relative', flexShrink: 0,
    }}>

      {/* logo — official FLUX mark */}
      <div className="no-drag" style={{
        width: 24, height: 24, flexShrink: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <FluxLogo size={24} />
      </div>

      <div style={{ display: 'flex', alignItems: 'baseline', gap: 7 }}>
        <span style={{ fontFamily: 'var(--mono)', fontWeight: 600, fontSize: 12, letterSpacing: '0.14em', color: 'var(--ink)' }}>FLUX</span>
        <span style={{ fontSize: 11, color: 'var(--ink-3)', letterSpacing: '0.02em' }}>{t('titlebar.tagline')}</span>
      </div>

      <div style={{ flex: 1 }} />

      {/* transient confirmation, shown just left of the refresh button */}
      {refreshDone && (
        <span
          className="no-drag"
          style={{
            fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--accent-hi)',
            whiteSpace: 'nowrap', animation: 'fadeIn 0.15s ease-out',
          }}
        >
          {t('titlebar.refreshDone')}
        </span>
      )}

      {/* refresh (left of the console) */}
      <div
        className="no-drag"
        title={t('titlebar.refresh')}
        onClick={handleRefresh}
        onMouseEnter={e => { const el = e.currentTarget as HTMLElement; el.style.background = 'var(--paper-2)'; el.style.color = 'var(--ink)' }}
        onMouseLeave={e => { const el = e.currentTarget as HTMLElement; el.style.background = 'transparent'; el.style.color = 'var(--ink-3)' }}
        style={{
          width: 28, height: 28, borderRadius: 7,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: 'var(--ink-3)', cursor: 'pointer',
          transition: 'background 0.1s, color 0.1s',
        }}
      >
        <RefreshCw size={14} strokeWidth={1.75} style={refreshing ? { animation: 'spin 0.6s linear infinite' } : undefined} />
      </div>

      {/* pin: keep FLUX above other apps (grey off, accent on) */}
      {window.electronAPI?.windowTogglePin && (
        <div
          className="no-drag"
          title={t(pinned ? 'titlebar.unpin' : 'titlebar.pin')}
          onClick={async () => {
            const next = await window.electronAPI?.windowTogglePin?.()
            if (typeof next === 'boolean') setPinned(next)
          }}
          onMouseEnter={() => setPinHov(true)}
          onMouseLeave={() => setPinHov(false)}
          style={{
            width: 28, height: 28, borderRadius: 7,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: pinned ? 'var(--accent)' : (pinHov ? 'var(--ink)' : 'var(--ink-3)'),
            background: pinHov ? 'var(--paper-2)' : 'transparent',
            cursor: 'pointer',
            transition: 'background 0.1s, color 0.1s',
          }}
        >
          <Pin size={14} strokeWidth={1.75} fill={pinned ? 'currentColor' : 'none'} style={{ transform: 'rotate(45deg)' }} />
        </div>
      )}

      {/* console (left of the bell) */}
      <Console />

      {/* notif bell → Activité */}
      <div className="no-drag" style={{ position: 'relative' }}>
        <div
          title={t('titlebar.notifications')}
          onClick={() => navigate('/activity')}
          onMouseEnter={() => setBellHov(true)}
          onMouseLeave={() => setBellHov(false)}
          style={{
            width: 28, height: 28, borderRadius: 7,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: (bellHov || pathname === '/activity') ? 'var(--ink)' : 'var(--ink-3)',
            background: (bellHov || pathname === '/activity') ? 'var(--paper-2)' : 'transparent',
            cursor: 'pointer',
            transition: 'background 0.1s, color 0.1s',
          }}
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

      {/* settings gear — même highlight que Console / cloche */}
      <Popover onOpenChange={setSettingsOpen}>
        <PopoverTrigger asChild>
          <div
            className="no-drag"
            title={t('titlebar.settings')}
            onMouseEnter={() => setSettingsHov(true)}
            onMouseLeave={() => setSettingsHov(false)}
            style={{
              width: 28, height: 28, borderRadius: 7,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: (settingsOpen || settingsHov) ? 'var(--ink)' : 'var(--ink-3)',
              background: (settingsOpen || settingsHov) ? 'var(--paper-2)' : 'transparent',
              cursor: 'pointer',
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
        {/* A detached page window (U4) closes at once; the slide-to-confirm is only for
            the main window, which quits FLUX. */}
        <WinBtn hoverBg="#ff5f57" icon={X}         action={() => (IS_DETACHED_WINDOW ? window.electronAPI?.windowClose() : setConfirmClose(true))} />
      </div>

      {/* slide-to-confirm quit overlay */}
      {confirmClose && (
        <div
          className="no-drag"
          style={{
            position: 'fixed', inset: 0, zIndex: 9999,
            background: 'rgba(0,0,0,0.55)', backdropFilter: 'blur(2px)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
          onClick={e => { if (e.target === e.currentTarget) setConfirmClose(false) }}
        >
          <div className="card" style={{
            padding: '24px 28px', display: 'flex', flexDirection: 'column',
            alignItems: 'center', gap: 16, boxShadow: 'var(--shadow-md)',
          }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--ink)' }}>{t('titlebar.closeFlux')}</div>
            <div style={{ fontSize: 11, color: 'var(--ink-3)', textAlign: 'center', maxWidth: 300, lineHeight: 1.5 }}>
              {t('titlebar.closeHint')}
            </div>
            <SlideToConfirm onConfirm={() => window.electronAPI?.windowClose()} />
            <div
              onClick={() => setConfirmClose(false)}
              style={{ fontSize: 11, color: 'var(--ink-4)', cursor: 'pointer', padding: '4px 8px' }}
            >
              {t('titlebar.cancel')}
            </div>
          </div>
        </div>
      )}

    </div>
  )
}
