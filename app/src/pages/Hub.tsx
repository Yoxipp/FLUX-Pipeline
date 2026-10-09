import { useSettings }  from '../hooks/useSettings'
import { useProject }   from '../ProjectContext'
import { useProduction } from '../hooks/useProduction'
import { useI18n } from '../i18n'
import { MyTasks } from './home/MyTasks'
import { MyRetakes } from './home/MyRetakes'
import { TeamChat } from './home/TeamChat'


// Home page: left column = "Tes tâches" then "Tes retakes" (one production load
// shared by both), team chat on the right. The shortcut grid repeated the sidebar
// (ADR 0044); the recent activity feed lives in the Activity page.
export function Hub() {
  const { t }         = useI18n()
  const { settings }  = useSettings()
  const user          = settings?.username ?? 'User'
  const username      = settings?.username ?? ''
  const { project }   = useProject()
  const prod          = useProduction(project || null)

  const dateStr = new Date().toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' })

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

        {/* ── tes tâches / tes retakes ── */}
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', minHeight: 0, borderRight: '1px solid var(--rule)' }}>
          <div style={{ flex: 3, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <MyTasks project={project} username={username} prod={prod} />
          </div>
          <div style={{ flex: 2, display: 'flex', flexDirection: 'column', minHeight: 0, borderTop: '1px solid var(--rule)' }}>
            <MyRetakes project={project} username={username} prod={prod} />
          </div>
        </div>

        {/* ── team chat ── */}
        <TeamChat project={project} user={user} />

      </div>
    </div>
  )
}
