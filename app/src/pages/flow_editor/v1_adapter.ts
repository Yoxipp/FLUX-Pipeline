// v1_adapter.ts — helpers of the editor's view model shared since P0: family / prefix /
// label of a node type, node height, catalogue entry. The P0 read-only adapter of the v1
// YAML actions (adaptV1Action, adaptV1Catalog) was removed with the old editor in P8.
// Pure functions, no I/O.

import type { Family, FlowViewNode, NodeSpec } from './types'

const HEADER_H = 28
const ROW_H = 20

// v1 command key -> family (02_NODES §1). Unknown keys (team nodes) = action: they may have effects.
const V1_FAMILY: Record<string, Family> = {
  project_context: 'flux', build_output_path: 'flux', select_publish: 'flux', select_dcc_publish: 'flux',
  select_houdini_publish: 'flux', copy_publish: 'flux', notify_activity: 'flux', refresh_component: 'flux',
  refresh_shot_stage: 'flux', usd_check: 'flux', usd_flatten: 'flux', call_function: 'flux',
  copy_file: 'action', move_file: 'action', make_folder: 'action', write_json: 'action', write_text: 'action',
  zip_folder: 'action', convert_image: 'action', conform_texture: 'action', generate_proxy: 'action',
  maya_export: 'dcc', houdini_export: 'dcc',
  format_text: 'operator', join_path: 'operator', log_message: 'operator',
  read_json: 'data', list_files: 'data',
}
const V1_PREFIX: Record<string, string> = { maya_export: 'may', houdini_export: 'hou' }

export function familyOfV1(command: string): Family {
  return V1_FAMILY[command] ?? 'action'
}

export function prefixOfV1(command: string): string | undefined {
  return V1_PREFIX[command]
}

// "select_dcc_publish" -> "SelectDccPublish" (02_NODES §1 labels).
export function pascal(key: string): string {
  return key.split(/[_\s.]+/).filter(Boolean).map(s => s[0].toUpperCase() + s.slice(1)).join('')
}

export function nodeHeight(n: Pick<FlowViewNode, 'hasExec' | 'inputs' | 'outputs'>): number {
  return HEADER_H + ROW_H * ((n.hasExec ? 1 : 0) + Math.max(n.inputs.length, n.outputs.length)) + 8
}

// Catalogue entry as the Shelf and Tab menu show it (v2 nodes, see adaptCatalog in v2_adapter.ts).
export interface CatalogEntry {
  type:   string
  label:  string
  family: Family
  icon?:  string
  prefix?: string
  doc_fr?: string
  doc_en?: string
  origin?: string
  aliases: string[]
  shelf?: number | null   // order on the Shelf; null = not on the Shelf
  spec?:  NodeSpec
}
