import { useEffect, useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { Upload, Download, RefreshCw, XCircle, FolderOpen, FolderTree, Copy, AtSign, Heart, MessageSquare, Bell, Check, UserRound, Eye, X, AlertTriangle, type LucideIcon } from 'lucide-react'
import * as Menu from '@radix-ui/react-dropdown-menu'
import { toast } from 'sonner'
import { api } from '../../api/client'
import { useActivityFeed } from '../../hooks/useFeeds'
import { useProject } from '../../ProjectContext'
import { useSessionState } from '../../hooks/useSessionState'
import { useMentionsFeed } from '../../hooks/useFeeds'
import { useFavorites, eventMatchesFavorite, shotFollowKey } from '../../hooks/useFavorites'
import { useSettings } from '../../hooks/useSettings'
import { useI18n } from '../../i18n'
import { Btn } from './ui'
import { ExpandPicker } from './ExpandPicker'
import { parseFluxFilename } from '../../pages/Production/util'
import type { ActivityEvent } from '../../types'
import { actionToType, REASON_LABEL, type ActivityType } from '../../lib/activityNotify'
import { NOTIFY_OPTIONS } from '../../lib/workProfiles'
import { useWorkProfile } from '../../WorkProfileContext'
import { openWorkProfile } from './WorkProfileDialog'

// The only access to activity (2026-11-06): the popover of the title bar bell.
// Mounted while open only, so a closed panel costs no request.
const HISTORY_PAGE = 200

// Stored dest paths are portable ("$FLUX/rel/path"); expand against the local
// workspace so each teammate opens it on their own drive.
function expandFluxPath(stored: string, workspace: string | null | undefined): string {
  if (!stored) return stored
  if (stored.startsWith('$FLUX/')) return workspace ? `${workspace}/${stored.slice('$FLUX/'.length)}` : stored
  if (stored === '$FLUX') return workspace ?? stored
  return stored // legacy absolute path
}

// Git activity was removed from FLUX — this pipeline no longer surfaces git events.
// Event categories live in lib/activityNotify (shared with the notification toasts).

const TYPE_ICON: Record<ActivityType, LucideIcon> = {
  publish: Upload,
  import:  Download,
  update:  RefreshCw,
  error:   XCircle,
  mention: AtSign,
  comment: MessageSquare,
}

// 'fav' is a special filter — matches whichever events reference a favorited task.
type FilterKey = ActivityType | 'fav' | null
const FILTERS: { labelKey: string; type: FilterKey }[] = [
  { labelKey: 'activity.filter.all',       type: null },
  { labelKey: 'prod.filter.fav',           type: 'fav' },
  { labelKey: 'activity.filter.mentions',  type: 'mention' },
  { labelKey: 'activity.filter.publishes', type: 'publish' },
  { labelKey: 'activity.filter.imports',   type: 'import' },
  { labelKey: 'activity.filter.updates',   type: 'update' },
  { labelKey: 'activity.filter.errors',    type: 'error' },
]

// Retake 04: Self = what concerns the artist (followed shots, favorite and assigned
// tasks, mentions), default; Global = every event of the active project. Both come
// from GET /activity/notifications: the backend decides, the client never filters a
// global log.
type View = 'self' | 'global'

export function ActivityPanel({ onClose }: { onClose: () => void }) {
  const { events: liveEvents, followedShots, markAllRead } = useActivityFeed()
  const { project } = useProject()
  const [view, setView] = useSessionState<View>('activity.view', 'self')
  // Self is fetched with a deeper window than the shared feed (older followed events),
  // again whenever the shared feed or the follow list changes.
  const [selfEvents, setSelfEvents] = useState<ActivityEvent[]>([])
  const routerNavigate = useNavigate()
  // Leaving for another page closes the popover.
  const navigate: typeof routerNavigate = ((...args: Parameters<typeof routerNavigate>) => {
    onClose()
    return routerNavigate(...args)
  }) as typeof routerNavigate
  const { t } = useI18n()
  const { settings } = useSettings()
  const workspace = settings?.workspace
  const [activeFilter, setActiveFilter] = useState<FilterKey>(null)
  const { favorites, toggleKey } = useFavorites()
  const feedHead = liveEvents[0]?.id ?? ''
  useEffect(() => {
    if (view !== 'self' || !project) { setSelfEvents([]); return }
    let alive = true
    api.getNotifications(project, 'self', 300)
      .then(r => { if (alive) setSelfEvents(r.events) })
      .catch(() => { if (alive) setSelfEvents([]) })
    return () => { alive = false }
  }, [view, project, feedHead, favorites])

  // @mentions addressed to the current user are surfaced in the feed too (not
  // only on the home page). They come from the shared feed — no private poller.
  const { mentions } = useMentionsFeed()

  // Older, rotated events pulled on demand from the cold archives (outside the
  // polling path). They are appended below the bounded live feed.
  const [older, setOlder] = useState<ActivityEvent[]>([])
  const [histOffset, setHistOffset] = useState(0)
  const [histMore, setHistMore]     = useState(true)
  const [histLoading, setHistLoading] = useState(false)

  const loadOlder = async () => {
    if (histLoading) return
    setHistLoading(true)
    try {
      const r = await api.getActivityHistory(HISTORY_PAGE, histOffset)
      setOlder(prev => [...prev, ...r.events])
      setHistOffset(o => o + r.events.length)
      setHistMore(r.has_more)
    } catch {
      toast.error(t('activity.historyLoadFail'))
    } finally {
      setHistLoading(false)
    }
  }

  // Self: the personal feed. Global: the project feed + archived history of this project.
  const events = useMemo(() => view === 'self'
    ? selfEvents
    : [...liveEvents, ...older.filter(e => e.project === project)], [view, selfEvents, liveEvents, older, project])

  type FavTarget = { project: string; class: string; name: string; task: string; subtask?: string }
  type Row = {
    t: ActivityType; msg: string; h: string;
    unread: boolean; dest_folder: string; sort: string;
    onClick?: () => void; fav?: boolean; favTarget?: FavTarget; why?: string;
  }

  // Match each event against the user's favorite list. Uses the shared parser
  // (new order → legacy fallback) with an empty known-token set — that keeps
  // it self-contained; the disambiguation edge cases matter only when both
  // orders map to plausible tokens, rare for favorited files.
  const eventFavInfo = useMemo(() => {
    if (favorites.length === 0) return new Map<string, { fav: boolean; target?: FavTarget }>()
    const map = new Map<string, { fav: boolean; target?: FavTarget }>()
    for (const e of events) {
      const file = e.file, project = e.project
      if (!file || !project) { map.set(e.id, { fav: false }); continue }
      const parsed = parseFluxFilename(file)
      if (!parsed) { map.set(e.id, { fav: false }); continue }
      const matched = favorites.some(k => eventMatchesFavorite(k, {
        project, class: parsed.class, name: parsed.name,
        task: parsed.task, instance: parsed.instance,
      }))
      map.set(e.id, matched
        ? { fav: true, target: {
            project, class: parsed.class, name: parsed.name,
            task: parsed.task, subtask: parsed.instance || undefined,
          } }
        : { fav: false })
    }
    return map
  }, [events, favorites])

  const eventRows: Row[] = events.map(e => {
    const info = eventFavInfo.get(e.id) ?? { fav: false }
    return {
      t: actionToType(e.action),
      msg: `${e.user} · ${e.action}${e.file ? ': ' + e.file : ''}`,
      h: e.time,
      unread: !e.read,
      dest_folder: e.dest_folder || '',
      sort: `${e.date} ${e.time}`,
      fav: info.fav || !!e.reason,
      favTarget: info.target,
      why: e.reason ? REASON_LABEL[e.reason] : undefined,
      // Clicking a favorited row jumps into the Production tab focused on
      // that task/subtask, rather than opening the Folder Manager.
      onClick: info.fav && info.target
        ? () => navigate('/production', { state: { openFavorite: info.target } })
        : undefined,
    }
  })

  const mentionRows: Row[] = mentions.map(m => ({
    t: 'mention',
    msg: `${m.from_user} t'a mentionné : ${m.text}`,
    h: m.time,
    unread: !m.read,
    dest_folder: '',
    sort: `${m.date} ${m.time}`,
    onClick: () => navigate('/'),   // mentions live in the team chat (Hub)
  }))

  // Mentions are personal: Self only.
  const allItems = [...eventRows, ...(view === 'self' ? mentionRows : [])].sort((a, b) => b.sort.localeCompare(a.sort))
  const items = !activeFilter
    ? allItems
    : activeFilter === 'fav'
      ? allItems.filter(i => i.fav)
      : allItems.filter(i => i.t === activeFilter)

  // Open the destination/context inside the app (Folder Manager on the asset/scene).
  const openContext = (destFolder: string) => {
    if (!destFolder) return
    navigate('/projects', { state: { openPath: expandFluxPath(destFolder, workspace) } })
  }

  // Reveal the destination in the OS file explorer — the ONLY action that opens a folder.
  const openInFolder = (destFolder: string) => {
    if (!destFolder) return
    void window.electronAPI?.openPath?.(expandFluxPath(destFolder, workspace))
  }

  const copyPath = (destFolder: string) => {
    if (!destFolder) return
    void navigator.clipboard.writeText(expandFluxPath(destFolder, workspace)).then(
      () => toast.success(t('activity.pathCopied')),
      () => toast.error(t('activity.pathCopyFail')),
    )
  }

  return (
    <div style={{ width: 520, maxWidth: 'calc(100vw - 24px)', height: 'min(72vh, 620px)', display: 'flex', flexDirection: 'column', minHeight: 0 }}>

      {/* One toolbar: filters left, actions right (ADR 0044). */}
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6, padding: '8px 10px', borderBottom: '1px solid var(--rule)' }}>
        <ExpandPicker title={t(view === 'self' ? 'activity.view.selfHint' : 'activity.view.globalHint')}
          value={view}
          options={(['self', 'global'] as const).map(v => ({ value: v, label: t(`activity.view.${v}`), title: t(`activity.view.${v}Hint`) }))}
          onChange={v => setView(v as View)}
        />
        <ExpandPicker title="Filtre"
          value={activeFilter ?? 'all'}
          options={FILTERS.map(f => ({ value: f.type ?? 'all', label: t(f.labelKey) }))}
          onChange={v => setActiveFilter(v === 'all' ? null : v as FilterKey)}
        />
        <div style={{ flex: 1 }} />
        <NotificationsMenu />
        <Btn ghost sm onClick={markAllRead}>{t('activity.markAllRead')}</Btn>
      </div>

      {view === 'self' && project && followedShots.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6, padding: '8px 12px', borderBottom: '1px solid var(--rule)' }}>
          <span className="lbl" style={{ marginRight: 4 }}>{t('activity.followed')}</span>
          {followedShots.map(s => (
            <span key={`${s.seq}/${s.shot}`} title={s.exists ? `${s.seq} ${s.shot}` : t('activity.shotGone')}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '2px 4px 2px 8px', borderRadius: 999, border: '1px solid var(--rule-2)', fontFamily: 'var(--mono)', fontSize: 11, color: s.exists ? 'var(--ink-2)' : 'var(--warn)' }}>
              {s.exists ? <Eye size={10} /> : <AlertTriangle size={10} />}{s.seq} {s.shot}
              <button type="button" aria-label={`${t('activity.unfollow')} ${s.seq} ${s.shot}`} title={t('activity.unfollow')}
                onClick={() => void toggleKey(shotFollowKey(project, s.seq, s.shot))}
                style={{ display: 'inline-flex', border: 0, background: 'transparent', color: 'var(--ink-4)', cursor: 'pointer', padding: 2 }}>
                <X size={10} />
              </button>
            </span>
          ))}
        </div>
      )}

      <div style={{ flex: 1, overflowY: 'auto' }}>
        {items.length === 0 && (
          <div style={{ padding: '20px 12px', fontSize: 11, color: 'var(--ink-4)', maxWidth: 520, lineHeight: 1.5 }}>
            {!project ? t('activity.noProject')
              : view === 'self' ? t(followedShots.length ? 'activity.selfEmpty' : 'activity.selfEmptyNoFollow')
              : t('activity.empty')}
          </div>
        )}
        {items.map((r, i) => {
          const Icon = TYPE_ICON[r.t] ?? Upload
          const isError = r.t === 'error'
          const hasPath = !!r.dest_folder
          const clickable = hasPath || !!r.onClick
          return (
            <div
              key={i}
              className="row"
              style={{ padding: '8px 12px', gap: 10, cursor: clickable ? 'pointer' : undefined }}
              // Click opens the destination/context (in-app); mentions open the team chat.
              onClick={r.onClick ? r.onClick : hasPath ? () => openContext(r.dest_folder) : undefined}
              title={hasPath ? `${t('activity.openContext')} : ${r.dest_folder}` : undefined}
            >
              <div style={{
                width: 24, height: 24, borderRadius: 6,
                border: '1px solid ' + (isError ? 'var(--err)' : 'var(--rule-2)'),
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                background: isError ? 'color-mix(in oklch, var(--err) 12%, transparent)' : 'var(--paper-2)',
                color: isError ? 'var(--err)' : 'var(--ink-3)',
                flexShrink: 0,
                boxShadow: 'var(--shadow-xs)',
              }}>
                <Icon size={12} strokeWidth={1.75} />
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 11, color: 'var(--ink)', display: 'flex', alignItems: 'center', gap: 6 }}>
                  {r.fav && (
                    <Heart size={10} strokeWidth={1.75} color="var(--accent-hi)" fill="var(--accent)" style={{ flexShrink: 0 }} />
                  )}
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.msg}</span>
                </div>
                <div className="lbl" style={{ marginTop: 2 }}>
                  <span style={{ textTransform: 'uppercase' }}>{r.t}</span> · {r.h}{r.why && <> · <span style={{ color: 'var(--accent-hi)' }}>{r.why}</span></>}
                </div>
                {hasPath && (
                  <div
                    className="lbl"
                    style={{ marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', direction: 'rtl', textAlign: 'left' }}
                    title={r.dest_folder}
                  >
                    {r.dest_folder}
                  </div>
                )}
              </div>
              {/* Actions are shown whenever the data is available, regardless of type. */}
              {hasPath && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
                  <ActionBtn icon={Copy}       label={t('activity.copyPath')}            onClick={e => { e.stopPropagation(); copyPath(r.dest_folder) }} />
                  <ActionBtn icon={FolderTree} label={t('activity.openInFolderManager')} onClick={e => { e.stopPropagation(); openContext(r.dest_folder) }} />
                  <ActionBtn icon={FolderOpen} label={t('activity.openInFolder')}         onClick={e => { e.stopPropagation(); openInFolder(r.dest_folder) }} />
                </div>
              )}
              {r.unread && (
                <span style={{
                  width: 7, height: 7,
                  background: 'var(--accent)',
                  borderRadius: '50%', flexShrink: 0,
                }} />
              )}
            </div>
          )
        })}
        {/* Load older, rotated history from the cold archives (on demand). */}
        {view === 'global' && histMore && (
          <div style={{ padding: '12px', display: 'flex', justifyContent: 'center' }}>
            <Btn ghost sm onClick={() => void loadOlder()} disabled={histLoading}>
              {histLoading ? t('activity.historyLoading') : t('activity.loadOlder')}
            </Btn>
          </div>
        )}
      </div>
    </div>
  )
}

function ActionBtn({ icon: Icon, label, onClick }: {
  icon: LucideIcon
  label: string
  onClick: (e: React.MouseEvent) => void
}) {
  return (
    <div
      onClick={onClick}
      title={label}
      aria-label={label}
      style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 22, height: 22, borderRadius: 5, border: '1px solid var(--rule-2)', background: 'var(--paper-2)', cursor: 'pointer', color: 'var(--ink-3)', boxShadow: 'var(--shadow-xs)' }}
      onMouseEnter={e => { e.currentTarget.style.background = 'var(--accent)'; e.currentTarget.style.borderColor = 'var(--accent)'; e.currentTarget.style.color = 'var(--on-accent)' }}
      onMouseLeave={e => { e.currentTarget.style.background = 'var(--paper-2)'; e.currentTarget.style.borderColor = 'var(--rule-2)'; e.currentTarget.style.color = 'var(--ink-3)' }}
    >
      <Icon size={11} strokeWidth={1.75} />
    </div>
  )
}

// Which activity events pop a notification (ADR 0043): preset by the work profile,
// overridden here by hand (the profile then shows "modifié").
function NotificationsMenu() {
  const { prefs, setPref, modified, activeProfile } = useWorkProfile()
  const count = NOTIFY_OPTIONS.filter(o => prefs[o.key]).length
  const changed = NOTIFY_OPTIONS.some(o => modified.includes(o.key))
  return (
    <Menu.Root modal={false}>
      <Menu.Trigger className="fm-view-trigger" aria-label="Notifications">
        <Bell size={13} strokeWidth={1.75} />
        <span>Notifications · {count}/{NOTIFY_OPTIONS.length}</span>
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content className="launcher-menu" side="bottom" align="end" sideOffset={4} collisionPadding={10} style={{ minWidth: 280 }}>
          <Menu.Label className="launcher-menu-label">Me notifier pour</Menu.Label>
          {NOTIFY_OPTIONS.map(o => (
            <Menu.CheckboxItem key={o.key} className="launcher-menu-item" checked={prefs[o.key]}
              onSelect={e => e.preventDefault()} onCheckedChange={v => setPref(o.key, v === true)}>
              <span style={{ width: 13, display: 'inline-flex' }}>{prefs[o.key] && <Check size={13} />}</span>
              <span style={{ display: 'flex', flexDirection: 'column' }}>{o.label}<small style={{ color: 'var(--ink-4)', fontSize: 11 }}>{o.hint}</small></span>
            </Menu.CheckboxItem>
          ))}
          <Menu.Separator className="launcher-menu-separator" />
          <Menu.Item className="launcher-menu-item" onSelect={openWorkProfile}>
            <UserRound size={13} />Profil : {activeProfile?.name ?? '-'}{changed && <span style={{ marginLeft: 'auto', color: 'var(--warn)', fontSize: 11 }}>modifié</span>}
          </Menu.Item>
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  )
}
