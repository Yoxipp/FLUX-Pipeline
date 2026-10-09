// BridgesInstall.tsx - Settings > User > Logiciels: "Installer tous les bridges"
// (retake F1). One call installs the FLUX bridge of every DCC detected on this machine
// (POST /dcc/bridges/install-all), then shows the per-software result. The per-software
// install stays in the Sidebar launcher menu. Dispatches 'flux:bridges-changed' so a
// listener (Sidebar plug icons) can refresh its autostart state.

import { useState } from 'react'
import { Plug } from 'lucide-react'
import { toast } from 'sonner'
import { api, type BridgeInstallResult } from '../../api/client'
import { Btn } from '../../components/shared/ui'
import { useI18n } from '../../i18n'
import { SOFTWARE } from '../../lib/dccs'

const COLOR: Record<BridgeInstallResult['status'], string> = {
  ok: 'var(--ok)', skip: 'var(--ink-4)', error: 'var(--err)',
}

export function BridgesInstall() {
  const { t } = useI18n()
  const [running, setRunning] = useState(false)
  const [results, setResults] = useState<BridgeInstallResult[] | null>(null)
  const nameOf = (key: string) => SOFTWARE.find(s => s.key === key)?.name ?? key

  const run = async () => {
    setRunning(true)
    try {
      const { results: res } = await api.installAllBridges()
      setResults(res)
      const count = (s: BridgeInstallResult['status']) => res.filter(r => r.status === s).length
      const summary = t('settings.bridges.summary', { ok: count('ok'), skip: count('skip'), error: count('error') })
      if (count('error')) toast.error(summary)
      else toast.success(summary)
      window.dispatchEvent(new CustomEvent('flux:bridges-changed'))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="card" style={{ padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <Plug size={14} strokeWidth={1.75} color="var(--ink-3)" />
        <span style={{ flex: 1, fontSize: 11, color: 'var(--ink-2)' }}>{t('settings.bridges.hint')}</span>
        <Btn sm ghost disabled={running} onClick={() => void run()}>
          {running ? t('settings.bridges.running') : t('settings.bridges.all')}
        </Btn>
      </div>
      {results && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {results.map(r => (
            <div key={r.dcc} style={{ display: 'flex', gap: 8, fontSize: 11.5, alignItems: 'baseline' }}>
              <span style={{ width: 80, color: 'var(--ink-2)' }}>{nameOf(r.dcc)}</span>
              <span style={{ width: 70, color: COLOR[r.status] }}>{t(`settings.bridges.${r.status}`)}</span>
              {r.status !== 'skip' && (
                <span style={{ flex: 1, color: 'var(--ink-3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={r.message}>
                  {r.message}
                </span>
              )}
            </div>
          ))}
          {results.some(r => r.status === 'ok') && (
            <div style={{ fontSize: 11.5, color: 'var(--ink-3)', marginTop: 4 }}>{t('settings.bridges.restart')}</div>
          )}
        </div>
      )}
    </div>
  )
}
