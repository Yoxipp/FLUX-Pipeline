// BackendBanner — thin reconnect strip shown when the FastAPI sidecar drops.
//
// Mid-session, if the backend dies or an antivirus locks the exe, the shell
// flips status to 'retrying'/'down' and keeps recovering in the background. This
// strip makes that state visible and offers a manual retry. Flat fill, no glow.

import { RefreshCw, TriangleAlert } from 'lucide-react'
import { useI18n } from '../../i18n'
import { useBackendStatus } from '../../hooks/useBackendStatus'

export function BackendBanner() {
  const { t } = useI18n()
  const { status, restart } = useBackendStatus()

  // 'starting' is the normal cold start (splash covers it); 'ready' is nominal.
  if (status === 'ready' || status === 'starting') return null

  const down = status === 'down'

  return (
    <div
      role="status"
      style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '6px 14px',
        background: 'var(--paper-2)',
        borderBottom: '1px solid var(--rule-2)',
        borderLeft: `2px solid ${down ? 'var(--danger, #d0654f)' : 'var(--color-accent)'}`,
        fontFamily: 'var(--sans)', fontSize: 11, color: 'var(--ink)',
      }}
    >
      <span
        aria-hidden
        style={{
          width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
          background: down ? 'var(--danger, #d0654f)' : 'var(--color-accent)',
        }}
      />
      {down
        ? <TriangleAlert size={13} strokeWidth={1.75} style={{ flexShrink: 0 }} />
        : <RefreshCw size={13} strokeWidth={1.75} style={{ flexShrink: 0, animation: 'flux-spin 1.1s linear infinite' }} />}
      <span style={{ flex: 1 }}>
        {down ? t('backend.down') : t('backend.retrying')}
        {down && <span style={{ color: 'var(--ink-3, #8a8784)', marginLeft: 8 }}>{t('backend.downHint')}</span>}
      </span>
      {down && (
        <button
          onClick={restart}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 5,
            padding: '3px 10px', borderRadius: 5, cursor: 'pointer',
            background: 'transparent', color: 'var(--ink)',
            border: '1px solid var(--rule-2)', fontFamily: 'var(--sans)', fontSize: 11,
          }}
        >
          <RefreshCw size={11} strokeWidth={1.75} /> {t('backend.retry')}
        </button>
      )}
      <style>{'@keyframes flux-spin{to{transform:rotate(360deg)}}'}</style>
    </div>
  )
}
