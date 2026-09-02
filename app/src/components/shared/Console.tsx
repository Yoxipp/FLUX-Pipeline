import { useState, useEffect, useRef, useCallback } from 'react'
import { Terminal, Copy, Trash2, X, Check } from 'lucide-react'
import { api, type LogRecord } from '../../api/client'

/* Backend log console — polls /logs, shows the sidecar (and mirrored Maya) logs.
   Opened from a TitleBar button left of the notification bell. */

const POLL_MS = 2000
const MAX_RECORDS = 1000

type FilterKey = 'all' | 'info' | 'warn' | 'error'
const FILTERS: { key: FilterKey; label: string; min: number }[] = [
  { key: 'all',   label: 'Tout',   min: 0 },
  { key: 'info',  label: 'Info',   min: 20 },
  { key: 'warn',  label: 'Warn',   min: 30 },
  { key: 'error', label: 'Erreur', min: 40 },
]

// Default level colors (theme-aware CSS vars for info/debug). User overrides from
// Settings replace a level's color; critical stays fixed and non-configurable.
const DEFAULT_LEVEL_COLORS: Record<LevelKey, string> = {
  error:   '#e5484d',
  warning: '#f5a623',
  info:    'var(--ink-2)',
  debug:   'var(--ink-4)',
}
type LevelKey = 'error' | 'warning' | 'info' | 'debug'

function levelKey(levelno: number): LevelKey {
  if (levelno >= 40) return 'error'
  if (levelno >= 30) return 'warning'
  if (levelno >= 20) return 'info'
  return 'debug'
}

function levelColor(levelno: number, overrides: Record<string, string>): string {
  if (levelno >= 50) return '#ff5f57'          // critical stays distinct
  const key = levelKey(levelno)
  return overrides[key] || DEFAULT_LEVEL_COLORS[key]
}

function fmtTime(ts: number): string {
  const d = new Date(ts * 1000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

export function Console() {
  const [open, setOpen]         = useState(false)
  const [records, setRecords]   = useState<LogRecord[]>([])
  const [filter, setFilter]     = useState<FilterKey>('all')
  const [copied, setCopied]     = useState(false)
  const [hov, setHov]           = useState(false)
  const [logColors, setLogColors] = useState<Record<string, string>>({})

  // Load console color overrides from settings; live-update when Settings edits them.
  useEffect(() => {
    let alive = true
    api.getSettings().then(s => { if (alive) setLogColors(s.log_colors ?? {}) }).catch(() => {})
    const onChange = (e: Event) => setLogColors(((e as CustomEvent).detail as Record<string, string>) ?? {})
    window.addEventListener('flux:log-colors', onChange as EventListener)
    return () => { alive = false; window.removeEventListener('flux:log-colors', onChange as EventListener) }
  }, [])

  const lastId       = useRef(0)   // highest id fetched
  const seenErrorId  = useRef(0)   // highest id acknowledged (badge baseline)
  const scrollRef    = useRef<HTMLDivElement | null>(null)
  const atBottom     = useRef(true)

  // Poll for new records regardless of open state (keeps the error badge live).
  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const { records: fresh } = await api.getLogs(lastId.current)
        if (!alive || fresh.length === 0) return
        lastId.current = fresh[fresh.length - 1].id
        setRecords(prev => {
          const merged = [...prev, ...fresh]
          return merged.length > MAX_RECORDS ? merged.slice(-MAX_RECORDS) : merged
        })
      } catch {
        /* backend not up yet — ignore and retry next tick */
      }
    }
    void tick()
    const h = setInterval(() => void tick(), POLL_MS)
    return () => { alive = false; clearInterval(h) }
  }, [])

  const shown = records.filter(r => r.levelno >= FILTERS.find(f => f.key === filter)!.min)

  const errorCount = records.reduce(
    (n, r) => (r.id > seenErrorId.current && r.levelno >= 40 ? n + 1 : n), 0,
  )

  // Auto-scroll to bottom when new lines arrive and the user is already at the bottom.
  useEffect(() => {
    if (open && atBottom.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [shown.length, open])

  const openDrawer = () => {
    seenErrorId.current = lastId.current   // clear the badge
    setOpen(true)
    requestAnimationFrame(() => {
      if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    })
  }

  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
  }

  const handleCopy = useCallback(() => {
    const text = shown
      .map(r => `${fmtTime(r.ts)}  ${r.level.padEnd(8)} ${r.logger}: ${r.msg}`)
      .join('\n')
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    }).catch(() => {})
  }, [shown])

  const handleClear = () => {
    void api.clearLogs().catch(() => {})
    setRecords([])
    lastId.current = 0
    seenErrorId.current = 0
  }

  return (
    <>
      {/* trigger button */}
      <div className="no-drag" style={{ position: 'relative' }}>
        <div
          title="Console"
          onClick={() => (open ? setOpen(false) : openDrawer())}
          onMouseEnter={() => setHov(true)}
          onMouseLeave={() => setHov(false)}
          style={{
            width: 28, height: 28, borderRadius: 7,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: hov || open ? 'var(--ink)' : 'var(--ink-3)',
            background: hov || open ? 'var(--paper-2)' : 'transparent',
            cursor: 'pointer', transition: 'background 0.1s, color 0.1s',
          }}
        >
          <Terminal size={14} strokeWidth={1.75} />
        </div>
        {errorCount > 0 && (
          <div style={{
            position: 'absolute', top: 2, right: 2,
            minWidth: 14, height: 14, padding: '0 3px',
            background: 'rgba(229,72,77,0.18)', border: '1px solid #e5484d',
            borderRadius: 999, fontFamily: 'var(--mono)', fontSize: 8,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: '#ff8a86', fontWeight: 600, pointerEvents: 'none',
          }}>{errorCount > 99 ? '99+' : errorCount}</div>
        )}
      </div>

      {/* drawer + backdrop */}
      {open && (
        <>
          <div
            onClick={() => setOpen(false)}
            style={{
              position: 'fixed', inset: '42px 0 0 0', zIndex: 40,
              background: 'rgba(0,0,0,0.28)',
            }}
          />
          <div style={{
            position: 'fixed', top: 42, right: 0, bottom: 0, width: 480, maxWidth: '92vw',
            zIndex: 41, display: 'flex', flexDirection: 'column',
            background: 'var(--bg-deep)', borderLeft: '1px solid var(--rule)',
            boxShadow: '-8px 0 24px rgba(0,0,0,0.35)',
          }}>
            {/* header */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '10px 12px', borderBottom: '1px solid var(--rule)', flexShrink: 0,
            }}>
              <Terminal size={13} strokeWidth={1.75} color="var(--accent-hi)" />
              <span style={{
                fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.11em',
                textTransform: 'uppercase', color: 'var(--ink-2)',
              }}>Console</span>

              <div style={{ flex: 1 }} />

              {FILTERS.map(f => {
                const active = filter === f.key
                return (
                  <div
                    key={f.key}
                    onClick={() => setFilter(f.key)}
                    style={{
                      fontFamily: 'var(--mono)', fontSize: 9, letterSpacing: '0.05em',
                      padding: '3px 7px', borderRadius: 5, cursor: 'pointer',
                      color: active ? 'var(--ink)' : 'var(--ink-4)',
                      background: active ? 'var(--paper-2)' : 'transparent',
                      border: '1px solid ' + (active ? 'var(--rule-2)' : 'transparent'),
                      transition: 'color 0.1s, background 0.1s',
                    }}
                  >{f.label}</div>
                )
              })}

              <IconBtn title={copied ? 'Copié' : 'Copier'} onClick={handleCopy}>
                {copied ? <Check size={13} strokeWidth={2} color="#28c940" /> : <Copy size={13} strokeWidth={1.75} />}
              </IconBtn>
              <IconBtn title="Vider" onClick={handleClear}>
                <Trash2 size={13} strokeWidth={1.75} />
              </IconBtn>
              <IconBtn title="Fermer" onClick={() => setOpen(false)}>
                <X size={14} strokeWidth={2} />
              </IconBtn>
            </div>

            {/* body */}
            <div
              ref={scrollRef}
              onScroll={onScroll}
              style={{
                flex: 1, overflowY: 'auto', padding: '8px 0',
                fontFamily: 'var(--mono)', fontSize: 11, lineHeight: 1.5,
                userSelect: 'text', WebkitUserSelect: 'text', cursor: 'text',
              }}
            >
              {shown.length === 0 ? (
                <div style={{ padding: '20px 14px', color: 'var(--ink-4)', fontSize: 11 }}>
                  Aucun message.
                </div>
              ) : shown.map(r => (
                <div key={r.id} style={{
                  display: 'flex', gap: 8, padding: '1px 12px',
                  alignItems: 'baseline', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                }}>
                  <span style={{ color: 'var(--ink-4)', flexShrink: 0 }}>{fmtTime(r.ts)}</span>
                  <span style={{
                    color: levelColor(r.levelno, logColors), flexShrink: 0, width: 58,
                    fontWeight: r.levelno >= 40 ? 600 : 400,
                  }}>{r.level}</span>
                  <span style={{ color: 'var(--ink)', flex: 1 }}>
                    <span style={{ color: 'var(--ink-4)' }}>{r.logger} </span>
                    {r.msg}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </>
  )
}

function IconBtn({ title, onClick, children }: {
  title: string; onClick: () => void; children: React.ReactNode
}) {
  const [hov, setHov] = useState(false)
  return (
    <div
      title={title}
      onClick={onClick}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        width: 26, height: 26, borderRadius: 6,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: hov ? 'var(--ink)' : 'var(--ink-3)',
        background: hov ? 'var(--paper-2)' : 'transparent',
        cursor: 'pointer', transition: 'background 0.1s, color 0.1s',
      }}
    >{children}</div>
  )
}
