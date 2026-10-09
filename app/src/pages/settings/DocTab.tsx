// DocTab.tsx - Settings > Doc (retake F3, ADR 0049): the FLUX manual embedded in the
// page (GET /system/manual, the FLUX_DOC copy or the bundled one), plus buttons to
// open it in the system browser or reveal the FLUX_DOC folder.

import { useEffect, useState } from 'react'
import { BookOpen, ExternalLink, FolderOpen } from 'lucide-react'
import { api, MANUAL_URL } from '../../api/client'
import { Btn } from '../../components/shared/ui'
import { useI18n } from '../../i18n'

export function DocTab() {
  const { t } = useI18n()
  const [info, setInfo] = useState<{ path: string; doc_dir: string } | null>(null)
  useEffect(() => { api.getManualInfo().then(setInfo).catch(() => setInfo(null)) }, [])
  const open = (p?: string) => { if (p) void window.electronAPI?.openPath?.(p) }

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 24px', borderBottom: '1px solid var(--rule)' }}>
        <BookOpen size={14} strokeWidth={1.75} color="var(--ink-3)" />
        <span style={{ flex: 1, fontSize: 11, color: 'var(--ink-2)' }}>{t('settings.doc.where')}</span>
        <Btn sm ghost disabled={!info?.path} onClick={() => open(info?.path)}><ExternalLink size={11} /> {t('settings.doc.open')}</Btn>
        <Btn sm ghost disabled={!info?.doc_dir} onClick={() => open(info?.doc_dir)}><FolderOpen size={11} /> {t('settings.doc.folder')}</Btn>
      </div>
      <iframe title={t('settings.doc.hint')} src={MANUAL_URL}
        style={{ flex: 1, minHeight: 0, width: '100%', border: 'none', background: 'var(--paper)' }} />
    </div>
  )
}
