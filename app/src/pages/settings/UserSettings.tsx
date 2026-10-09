// UserSettings.tsx - Settings > User (retake 06): what belongs to the artist or this
// machine, never to the project. Moved from the title bar popover: work profile link
// (ADR 0042), workspace, UI accent, console colors (optionally following the accent),
// enabled software, language, UI reset, version. New: rename / delete one's own user,
// no longer hidden in the user switch menu.

import { useEffect, useState } from 'react'
import { ChevronRight, FolderOpen, Pencil, RefreshCw, RotateCcw, Trash2, UserRound } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../../api/client'
import { Avatar, Btn, SecTitle } from '../../components/shared/ui'
import { useI18n } from '../../i18n'
import { ACCENT_PRESETS, applyAccentPreset } from '../../lib/accentPresets'
import { SOFTWARE } from '../../lib/dccs'
import { useEnabledDccs } from '../../hooks/useEnabledDccs'
import { useWorkProfile } from '../../WorkProfileContext'
import { openWorkProfile } from '../../components/shared/WorkProfileDialog'
import { BridgesInstall } from './BridgesInstall'

// Console log levels the user can recolor + a theme-neutral swatch default shown
// when there is no override yet (picking one writes the override).
const LOG_LEVELS: { key: string; labelKey: string; def: string }[] = [
  { key: 'debug',   labelKey: 'log.debug',   def: '#7a7f87' },
  { key: 'info',    labelKey: 'log.info',    def: '#c8ccd4' },
  { key: 'warning', labelKey: 'log.warning', def: '#f5a623' },
  { key: 'error',   labelKey: 'log.error',   def: '#e5484d' },
]
// The console accepts any CSS color: this one follows the accent live.
const ACCENT_COLOR = 'var(--accent-hi)'

const row = { display: 'flex', alignItems: 'center', gap: 8 } as const
const card = { padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8 } as const
const inputStyle = {
  height: 26, padding: '0 8px', fontSize: 11, background: 'var(--paper-2)', color: 'var(--ink)',
  border: '1px solid var(--rule-2)', borderRadius: 5, outline: 'none', boxSizing: 'border-box',
} as const

export function UserSettings({ username }: { username: string }) {
  const { t, lang, setLang } = useI18n()
  const [workspace, setWorkspace] = useState('')
  const [version, setVersion] = useState('')
  const [changing, setChanging] = useState(false)
  const [accentKey, setAccentKey] = useState('orange')
  const [logColors, setLogColors] = useState<Record<string, string>>({})
  const { isEnabled: isDccEnabled, setEnabled: setEnabledDccs } = useEnabledDccs()
  const workProfile = useWorkProfile()

  useEffect(() => {
    api.getSettings().then(s => {
      setWorkspace(s.workspace ?? '')
      const stored = s.theme?.accent ?? 'orange'
      setAccentKey(ACCENT_PRESETS.some(p => p.key === stored) ? stored : 'orange')
      setLogColors(s.log_colors ?? {})
    }).catch(() => {})
    window.electronAPI?.getAppVersion().then(setVersion).catch(() => {})
  }, [])

  const toggleDcc = (key: string) => {
    const current = SOFTWARE.map(s => s.key).filter(isDccEnabled)
    const next = current.includes(key) ? current.filter(k => k !== key) : [...current, key]
    void setEnabledDccs(next).catch(() => {})
  }
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
  const followsAccent = logColors.info === ACCENT_COLOR
  const toggleFollowAccent = () => {
    const next = { ...logColors }
    if (followsAccent) delete next.info
    else next.info = ACCENT_COLOR
    pushLogColors(next)
  }
  const handleResetUi = () => {
    try { localStorage.removeItem('flux.ui.publisherRightWidth') } catch { /* blocked storage */ }
    window.dispatchEvent(new Event('flux:reset-ui'))
    toast.success(t('settings.resetUi'))
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 620 }}>
      <div style={{ fontSize: 11, color: 'var(--ink-3)' }}>Ces réglages ne concernent que toi (ou ce poste), jamais le projet.</div>

      <SecTitle>{t('settings.user')}</SecTitle>
      <OwnAccount username={username} />

      <SecTitle>Profil de travail</SecTitle>
      <div className="card" style={{ ...card, flexDirection: 'row', alignItems: 'center', cursor: 'pointer' }} role="button" tabIndex={0}
        onClick={openWorkProfile} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openWorkProfile() } }}>
        <UserRound size={13} strokeWidth={1.75} />
        <span style={{ flex: 1, fontSize: 11 }}>{workProfile.activeProfile?.name ?? 'Profil'}</span>
        {workProfile.modified.length > 0 && <span style={{ fontFamily: 'var(--mono)', fontSize: 9, color: 'var(--warn)' }}>modifié</span>}
        <ChevronRight size={12} strokeWidth={1.75} color="var(--ink-4)" />
      </div>

      <SecTitle>{t('settings.workspace')}</SecTitle>
      <div className="card" style={{ ...card, flexDirection: 'row', alignItems: 'center' }}>
        <FolderOpen size={13} strokeWidth={1.75} color="var(--ink-4)" />
        <span style={{ flex: 1, minWidth: 0, fontSize: 10.5, fontFamily: 'var(--mono)', color: workspace ? 'var(--ink-2)' : 'var(--ink-4)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={workspace}>{workspace || '-'}</span>
        <Btn sm ghost disabled={changing} onClick={() => void handleChangeWorkspace()}>
          {changing ? <RefreshCw size={11} style={{ animation: 'spin 1s linear infinite' }} /> : <FolderOpen size={11} />}
          {changing ? t('settings.changing') : t('settings.changeDir')}
        </Btn>
      </div>

      <SecTitle>{t('settings.accent')}</SecTitle>
      <div className="card" style={card}>
        <div style={{ display: 'flex', gap: 6 }}>
          {ACCENT_PRESETS.map(p => {
            const active = accentKey === p.key
            return (
              <button key={p.key} type="button" title={p.label} aria-label={p.label} aria-pressed={active} onClick={() => handleAccent(p.key)}
                style={{ flex: 1, height: 24, borderRadius: 5, background: p.accent, cursor: 'pointer',
                  border: active ? '2px solid var(--ink)' : '2px solid transparent' }} />
            )
          })}
        </div>
      </div>

      <SecTitle>{t('settings.logColors')}</SecTitle>
      <div className="card" style={card}>
        <label style={{ ...row, fontSize: 11, color: 'var(--ink-2)', cursor: 'pointer' }}>
          <input type="checkbox" checked={followsAccent} onChange={toggleFollowAccent} style={{ accentColor: 'var(--accent)', margin: 0 }} />
          Messages de la console à la couleur d'accent
        </label>
        {LOG_LEVELS.map(l => {
          const locked = l.key === 'info' && followsAccent
          return (
            <div key={l.key} style={row}>
              <input type="color" disabled={locked}
                value={/^#/.test(logColors[l.key] ?? '') ? logColors[l.key] : l.def}
                onChange={e => pushLogColors({ ...logColors, [l.key]: e.target.value })}
                style={{ width: 26, height: 20, padding: 0, border: '1px solid var(--rule-2)', borderRadius: 5, background: 'transparent', cursor: locked ? 'default' : 'pointer', opacity: locked ? 0.4 : 1 }} />
              <span style={{ fontSize: 11, color: 'var(--ink-2)', flex: 1 }}>{t(l.labelKey)}{locked && ' · accent'}</span>
            </div>
          )
        })}
        {Object.keys(logColors).length > 0 && (
          <div><Btn sm ghost onClick={() => pushLogColors({})}><RotateCcw size={11} /> {t('settings.logColorsReset')}</Btn></div>
        )}
      </div>

      <SecTitle>{t('settings.dccs')}</SecTitle>
      <div className="card" style={{ ...card, display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '6px 10px' }}>
        {SOFTWARE.map(s => (
          <label key={s.key} style={{ ...row, fontSize: 11, color: 'var(--ink-2)', cursor: 'pointer' }}>
            <input type="checkbox" checked={isDccEnabled(s.key)} onChange={() => toggleDcc(s.key)} style={{ accentColor: 'var(--accent)', margin: 0 }} />
            {s.name}
          </label>
        ))}
      </div>
      <BridgesInstall />

      <SecTitle>{t('settings.language')}</SecTitle>
      <div style={{ display: 'flex', gap: 6 }}>
        {(['fr', 'en'] as const).map(l => (
          <Btn key={l} sm primary={lang === l} ghost={lang !== l} onClick={() => setLang(l)}>{l === 'fr' ? 'Français' : 'English'}</Btn>
        ))}
      </div>

      <SecTitle>{t('settings.interface')}</SecTitle>
      <div><Btn sm ghost onClick={handleResetUi}><RotateCcw size={11} /> {t('settings.resetUi')}</Btn></div>

      {version && <div style={{ fontSize: 10, color: 'var(--ink-4)', fontFamily: 'var(--mono)' }}>{t('settings.version')} {version}</div>}
    </div>
  )
}

// Rename or delete one's own user. The backend refuses to delete the active user, so
// deleting first switches to another (existing or new) user, then removes the old one.
function OwnAccount({ username }: { username: string }) {
  const [mode, setMode] = useState<'idle' | 'rename' | 'delete'>('idle')
  const [value, setValue] = useState('')
  const [others, setOthers] = useState<string[]>([])
  const [next, setNext] = useState('')
  const [typed, setTyped] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (mode !== 'delete') return
    api.listUsers().then(d => {
      const list = d.users.filter(u => u.toUpperCase() !== username.toUpperCase())
      setOthers(list); setNext(list[0] ?? '')
    }).catch(() => setOthers([]))
  }, [mode, username])

  const rename = async () => {
    const target = value.trim().toUpperCase()
    if (!target || target === username) { setMode('idle'); return }
    setBusy(true)
    try {
      const res = await api.renameUser(username, target)
      toast.success(res.message)
      window.location.reload()
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Échec du renommage'); setBusy(false) }
  }
  const remove = async () => {
    const target = next.trim().toUpperCase()
    if (typed !== username || !target) return
    setBusy(true)
    try {
      await api.updateSettings({ username: target })
      const res = await api.deleteUser(username)
      toast.success(res.message)
      window.location.reload()
    } catch (e) { toast.error(e instanceof Error ? e.message : 'Échec de la suppression'); setBusy(false) }
  }

  return (
    <div className="card" style={card}>
      <div style={row}>
        <Avatar ch={(username[0] ?? '?').toUpperCase()} size={22} />
        {mode === 'rename' ? (
          <input autoFocus value={value} onChange={e => setValue(e.target.value.toUpperCase())}
            onKeyDown={e => { if (e.key === 'Enter') void rename(); else if (e.key === 'Escape') setMode('idle') }}
            style={{ ...inputStyle, flex: 1, textTransform: 'uppercase' }} />
        ) : <span style={{ flex: 1, fontSize: 12, color: 'var(--ink)' }}>{username}</span>}
        {mode === 'rename' ? <>
          <Btn sm primary disabled={busy} onClick={() => void rename()}>Renommer</Btn>
          <Btn sm ghost onClick={() => setMode('idle')}>Annuler</Btn>
        </> : mode === 'idle' && <>
          <Btn sm ghost onClick={() => { setValue(username); setMode('rename') }}><Pencil size={11} /> Renommer</Btn>
          <Btn sm ghost onClick={() => { setTyped(''); setMode('delete') }} style={{ color: 'var(--err)' }}><Trash2 size={11} /> Supprimer</Btn>
        </>}
      </div>
      {mode === 'delete' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 11, color: 'var(--ink-3)', lineHeight: 1.5 }}>
          <span>Supprime ton utilisateur et ses données (favoris, préférences). Tes publishs restent dans les projets.</span>
          <label style={row}>Continuer en tant que
            <input list="flux-other-users" value={next} onChange={e => setNext(e.target.value.toUpperCase())} placeholder="NOUVEL ARTISTE"
              style={{ ...inputStyle, width: 180, textTransform: 'uppercase' }} />
            <datalist id="flux-other-users">{others.map(u => <option key={u} value={u} />)}</datalist>
          </label>
          <label style={row}>Tape <code style={{ fontFamily: 'var(--mono)' }}>{username}</code> pour confirmer
            <input value={typed} onChange={e => setTyped(e.target.value)} spellCheck={false}
              style={{ ...inputStyle, width: 180, borderColor: typed === username ? 'var(--err)' : 'var(--rule-2)' }} />
          </label>
          <div style={row}>
            <Btn sm disabled={busy || typed !== username || !next.trim()} onClick={() => void remove()}
              style={{ background: 'var(--err)', color: '#fff', borderColor: 'var(--err)' }}>Supprimer {username}</Btn>
            <Btn sm ghost onClick={() => setMode('idle')}>Annuler</Btn>
          </div>
        </div>
      )}
    </div>
  )
}
