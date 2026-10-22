import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { Bell, Settings2, ChevronDown, X, Minus, Maximize2, RefreshCw, Pin } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Avatar } from './ui'
import { FluxLogo } from './Logo'
import { Console } from './Console'
import { SlideToConfirm } from './SlideToConfirm'
import { useI18n } from '../../i18n'
import { useShareLatency } from '../../lib/adaptivePoll'

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
        background: hov ? hoverBg : 'var(--rule-3)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        cursor: 'default', flexShrink: 0,
        transition: 'background 0.12s',
      }}
    >
      {hov && <Icon size={7} strokeWidth={2.5} color="rgba(0,0,0,0.65)" />}
    </div>
  )
}


const IS_DETACHED_WINDOW = new URLSearchParams(window.location.search).get('detached') === '1'


export function TitleBar({ username, unreadCount, onUserChange }: Props) {
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
  const share = useShareLatency()
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

      <span style={{ fontFamily: 'var(--mono)', fontWeight: 600, fontSize: 12, letterSpacing: '0.14em', color: 'var(--ink)' }}>FLUX</span>

      <div style={{ flex: 1 }} />

      {/* slow file share: median of the feed polls above 1 s (hidden under 0.7 s) */}
      {share.slow && (
        <span
          className="no-drag"
          title="Le serveur de fichiers répond lentement ; FLUX ralentit ses rafraîchissements."
          style={{
            fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--ink-3)',
            padding: '2px 7px', border: '1px solid var(--rule-2)', borderRadius: 999,
            background: 'var(--paper-2)', whiteSpace: 'nowrap', cursor: 'default',
          }}
        >
          Partage lent ({(share.medianMs / 1000).toFixed(1)} s)
        </span>
      )}

      {/* transient confirmation, shown just left of the refresh button */}
      {refreshDone && (
        <span
          className="no-drag"
          style={{
            fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--accent-hi)',
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
            background: 'var(--paper-2)', border: '1px solid var(--rule-3)',
            borderRadius: 999, fontFamily: 'var(--mono)', fontSize: 10,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: 'var(--accent-hi)', fontWeight: 600,
            boxShadow: 'var(--shadow-xs)', pointerEvents: 'none',
          }}>{unreadCount}</div>
        )}
      </div>

      {/* settings gear: opens the Settings page (User / Projet / Avance, retake 06) */}
      <div
        className="no-drag"
        title={t('titlebar.settings')}
        onClick={() => navigate('/settings')}
        onMouseEnter={() => setSettingsHov(true)}
        onMouseLeave={() => setSettingsHov(false)}
        style={{
          width: 28, height: 28, borderRadius: 7,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: (settingsHov || pathname === '/settings') ? 'var(--ink)' : 'var(--ink-3)',
          background: (settingsHov || pathname === '/settings') ? 'var(--paper-2)' : 'transparent',
          cursor: 'pointer',
          transition: 'background 0.12s, color 0.12s',
        }}
      >
        <Settings2 size={14} strokeWidth={1.75} />
      </div>

      {/* user: avatar only (ADR 0044), the name is the tooltip; click = change user */}
      <div
        className="no-drag"
        onClick={() => onUserChange()}
        title={user}
        style={{
          display: 'flex', alignItems: 'center', gap: 4,
          padding: '3px 6px 3px 4px',
          border: '1px solid var(--rule-2)',
          borderRadius: 999,
          background: 'var(--paper-2)',
          cursor: 'pointer',
          boxShadow: 'var(--shadow-xs)',
          transition: 'border-color 0.12s, background 0.12s',
        }}
        onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--rule-3)'; (e.currentTarget as HTMLElement).style.background = 'var(--paper-2)' }}
        onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--rule-2)'; (e.currentTarget as HTMLElement).style.background = 'var(--paper-2)' }}
      >
        <Avatar ch={user[0].toUpperCase()} size={20} />
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
            <SlideToConfirm label={t('titlebar.slideToClose')} onConfirm={() => { window.electronAPI?.windowClose() }} />
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
