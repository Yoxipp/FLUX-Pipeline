// links.ts — pure helpers of the page <-> flow links (04_PAGES_TOOL §4). No React, no fetch:
// the logic is checked by reading and in live (no front test runner, P7).

import type { FlowDoc } from '../flow_editor/types'

export interface ParamRename { old: string; next: string }

// Interface inputs renamed between the saved document and the one being saved: same
// slot, same type, another id, and neither id on the other side (an add + remove is
// not a rename). The pages bound to `old` follow (POST /flows/pages/rename_param).
export function renamedInputs(before: FlowDoc | null | undefined, after: FlowDoc): ParamRename[] {
  const was = before?.interface?.inputs ?? []
  const now = after.interface?.inputs ?? []
  const wasIds = new Set(was.map(i => i.id))
  const nowIds = new Set(now.map(i => i.id))
  const out: ParamRename[] = []
  was.forEach((input, k) => {
    const next = now[k]
    if (next && next.id !== input.id && next.type === input.type && !nowIds.has(input.id) && !wasIds.has(next.id)) {
      out.push({ old: input.id, next: next.id })
    }
  })
  return out
}
