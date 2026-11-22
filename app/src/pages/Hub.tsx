import { useSettings }  from '../hooks/useSettings'
import { useProject }   from '../ProjectContext'
import { useProduction } from '../hooks/useProduction'
import { useI18n, useTr } from '../i18n'
import { MyTasks } from './home/MyTasks'
import { MyRetakes } from './home/MyRetakes'


// Home page: two columns "Tes tâches" | "Tes retakes" (one production load shared by both).
// The team chat left the home page (ADR 0091): it is a TOOL widget now. The shortcut grid repeated the sidebar
// (ADR 0044); the recent activity feed lives in the title bar bell.
export function Hub() {
  const { t }         = useI18n()
  const { locale }    = useTr()
  const { settings }  = useSettings()
  const user          = settings?.username ?? 'User'
  const username      = settings?.username ?? ''
  const { project }   = useProject()
  const prod          = useProduction(project || null)

  const dateStr = new Date().toLocaleDateString(locale, { weekday: 'long', day: 'numeric', month: 'long' })

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>

      {/* header: one line */}
      <div style={{ padding: '14px 22px 12px', borderBottom: '1px solid var(--rule)', flexShrink: 0, display: 'flex', alignItems: 'baseline', gap: 12 }}>
        <div style={{ fontSize: 17, fontWeight: 600, color: 'var(--ink)' }}>
          {t('hub.hello')}, <span style={{ color: 'var(--accent-hi)' }}>{user}</span>
        </div>
        <div style={{ fontSize: 11, color: 'var(--ink-3)', textTransform: 'capitalize' }}>{dateStr}</div>
      </div>

      {/* body */}
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>

        {/* ── two columns: tes tâches | tes retakes, each scrolls ── */}
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', minHeight: 0, borderRight: '1px solid var(--rule)' }}>
          <MyTasks project={project} username={username} prod={prod} />
        </div>
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <MyRetakes project={project} username={username} prod={prod} />
        </div>

      </div>
    </div>
  )
}
