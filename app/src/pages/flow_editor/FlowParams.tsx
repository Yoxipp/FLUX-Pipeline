// FlowParams.tsx — Params pane when no node is selected (03_EDITEUR §1): the flow itself.
// P4: label and description of the open document.

import { ParamWidget } from '../../components/shared/ParamWidget'
import { Row } from './ParamsPane'
import type { FlowDoc } from './types'
import { useTr } from './useTr'

const cap = (text: string) => <span style={{ fontSize: 11.5, color: 'var(--ink-3)' }}>{text}</span>

export function FlowParams({ doc, editable, onFields }: {
  doc: FlowDoc | null
  editable: boolean
  onFields: (patch: Partial<FlowDoc>, key: string) => void
}) {
  const { tr } = useTr()
  if (!doc) return <div style={{ fontSize: 11, color: 'var(--ink-4)' }}>{tr('Aucun flow ouvert', 'No flow open')}</div>
  return (
    <>
      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)', marginBottom: 8 }}>{doc.name}</div>
      <Row label={cap(tr('Libelle', 'Label'))}>
        <ParamWidget kind="str" value={doc.label ?? ''} disabled={!editable}
                     onChange={v => onFields({ label: String(v) || undefined }, 'flow:label')} />
      </Row>
      <Row label={cap('Description')}>
        <ParamWidget kind="text" value={doc.description ?? ''} disabled={!editable}
                     onChange={v => onFields({ description: String(v) || undefined }, 'flow:description')} />
      </Row>
      <div style={{ fontSize: 11, color: 'var(--ink-4)', marginTop: 12 }}>
        {tr('Clique un node pour ses parametres. Survole un node pour ses infos, un port pour son type.', 'Click a node for its parameters. Hover a node for its info, a port for its type.')}
      </div>
    </>
  )
}
