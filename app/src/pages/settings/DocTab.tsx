// DocTab.tsx - Settings > Doc (retake F3, ADR 0049): one sub-tab per manual, embedded in
// the page (GET /system/manual, ?doc=flows for the Flows manual built from docs/user/flows/),
// plus buttons to open the shown manual in the system browser or reveal the FLUX_DOC folder.
// The sub-tab is in the URL (?tab=doc&doc=flows) so a page can link straight to it.

import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { BookOpen, ExternalLink, FolderOpen } from 'lucide-react'
import { api, FLOWS_MANUAL_URL, MANUAL_URL } from '../../api/client'
import { Btn } from '../../components/shared/ui'
import { useI18n } from '../../i18n'

type Doc = 'flux' | 'flows'

export function DocTab() {
  const { t } = useI18n()
  const [params, setParams] = useSearchParams()
  const doc: Doc = params.get('doc') === 'flows' ? 'flows' : 'flux'
  const [info, setInfo] = useState<{ path: string; flows_path: string; doc_dir: string } | null>(null)
  useEffect(() => { api.getManualInfo().then(setInfo).catch(() => setInfo(null)) }, [])
  const open = (p?: string) => { if (p) void window.electronAPI?.openPath?.(p) }
  const pick = (next: Doc) => setParams(p => { p.set('doc', next); return p }, { replace: true })
  const path = doc === 'flows' ? info?.flows_path : info?.path

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 24px', borderBottom: '1px solid var(--rule)' }}>
        <BookOpen size={14} strokeWidth={1.75} color="var(--ink-3)" />
        <Btn sm primary={doc === 'flux'} ghost={doc !== 'flux'} title={t('settings.doc.hint')} onClick={() => pick('flux')}>{t('settings.doc.flux')}</Btn>
        <Btn sm primary={doc === 'flows'} ghost={doc !== 'flows'} title={t('settings.doc.flowsHint')} onClick={() => pick('flows')}>{t('settings.doc.flows')}</Btn>
        <span style={{ flex: 1, fontSize: 11, color: 'var(--ink-2)', marginLeft: 8 }}>{t('settings.doc.where')}</span>
        <Btn sm ghost disabled={!path} onClick={() => open(path)}><ExternalLink size={11} /> {t('settings.doc.open')}</Btn>
        <Btn sm ghost disabled={!info?.doc_dir} onClick={() => open(info?.doc_dir)}><FolderOpen size={11} /> {t('settings.doc.folder')}</Btn>
      </div>
      <iframe key={doc} title={doc === 'flows' ? t('settings.doc.flowsHint') : t('settings.doc.hint')}
        src={doc === 'flows' ? FLOWS_MANUAL_URL : MANUAL_URL}
        style={{ flex: 1, minHeight: 0, width: '100%', border: 'none', background: 'var(--paper)' }} />
    </div>
  )
}
