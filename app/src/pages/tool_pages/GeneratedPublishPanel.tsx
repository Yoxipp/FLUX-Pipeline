// GeneratedPublishPanel.tsx — the Publisher panel of a software added as an extension
// (04_PAGES_TOOL §7, decision 20): no hand-written screen, the fields come from the
// interface of its flow publish_<soft> (GET /flows/pages/publish_panel/<soft>), rendered by
// the same PageRenderer as the TOOL pages. Publier = POST /flows/publish_<soft>/run
// {event: publish_request, values} (active flow only, A7), last run state under the button.
// The shipped softwares keep their own Publisher screen. The destination and the publish
// note blocks need the Composer selection (file name, ext, relPath) that the flow does not
// carry yet: they join this panel with the Publisher switch (P8).

import { useCallback, useEffect, useState } from 'react'
import { ExternalLink } from 'lucide-react'
import { flowsApi } from '../../api/flows'
import { useFlowsWs } from '../../hooks/useFlowsWs'
import type { FlowsWsMessage, PageDoc, PageIssue, PageTarget } from '../flow_editor/types'
import { useTr } from '../flow_editor/useTr'
import { PageRenderer } from './PageRenderer'

export function GeneratedPublishPanel({ soft, label, project }: { soft: string; label: string; project?: string }) {
  const { tr } = useTr()
  const [panel, setPanel] = useState<{ flow: string; page: PageDoc; issues: PageIssue[]; target: PageTarget } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    flowsApi.publishPanel(soft, project)
      .then(p => { setPanel(p); setError(null) })
      .catch(err => { setPanel(null); setError((err as Error).message) })
  }, [soft, project])
  useEffect(() => { load() }, [load])
  useFlowsWs(useCallback((msg: FlowsWsMessage) => {
    if ((msg.type === 'activation' || msg.type === 'flow_changed') && msg.flow === `publish_${soft}`) load()
  }, [soft, load]), load)

  const openFlow = () => {
    const route = `/action-graph?flow=${encodeURIComponent(`publish_${soft}`)}`
    if (window.electronAPI?.detachPage) window.electronAPI.detachPage(route)
    else window.location.hash = route
  }

  return (
    <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--ink)' }}>{tr(`Publish ${label}`, `Publish ${label}`)}</span>
        <span className="tag">{tr('extension', 'extension')}</span>
        <span style={{ flex: 1 }} />
        <button type="button" className="btn ghost sm" onClick={openFlow}><ExternalLink size={11} /> {tr('Flow publish', 'Publish flow')}</button>
      </div>
      <div className="tp-note" style={{ color: 'var(--ink-3)' }}>
        {tr(`Panneau genere depuis l'interface du flow publish_${soft} : un TD l'edite dans l'editeur de flows.`,
            `Panel generated from the interface of the flow publish_${soft}: a TD edits it in the flow editor.`)}
      </div>
      {error && <div className="tp-note" style={{ color: 'var(--err)' }}>{error}</div>}
      {panel && <PageRenderer page={panel.page} issues={panel.issues} project={project} target={panel.target} />}
    </div>
  )
}
