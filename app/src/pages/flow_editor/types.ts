// types.ts — TS types of the Flows editor (03_EDITEUR §9). P0 holds the view model
// only; FlowDoc / FlowLink / Issue / RunRecord arrive with the v2 format (P1+).

export type Family =
  | 'event' | 'data' | 'logic' | 'operator' | 'action'
  | 'flux' | 'session' | 'dcc' | 'bridge' | 'subflow'

// "exec", "any", "bool", "int", "float", "str", "path", "dir", "list[T]", "dict",
// "session[<soft>]", "publish", "dcc_node", "pattern".
export type PortType = string

export interface PortSpec {
  name:     string
  type:     PortType
  required?: boolean
  doc_fr?:  string
  doc_en?:  string
  example?: string
  value?:   unknown       // literal value of an input (shown greyed)
  wiredFrom?: string      // "<node label>.<port>" when the input is linked
}

// One node as the editor draws it.
export interface FlowViewNode {
  id:       string
  type:     string        // registry type id ("flux.legacy_command" for v1)
  label:    string
  family:   Family
  icon?:    string
  prefix?:  string        // DCC prefix badge: hou, may...
  doc_fr?:  string
  doc_en?:  string
  hasExec:  boolean       // exec in + then out
  inputs:   PortSpec[]
  outputs:  PortSpec[]
  position: { x: number; y: number }
  meta?:    Record<string, string>   // shown in Params (step, module...)
}

export interface FlowViewEdge {
  id:     string
  kind:   'exec' | 'data'
  source: string
  sourcePort: string
  target: string
  targetPort: string
  type:   PortType
}

export interface FlowView {
  name:  string
  description?: string
  nodes: FlowViewNode[]
  edges: FlowViewEdge[]
  readOnly: boolean
  origin?: string
}
