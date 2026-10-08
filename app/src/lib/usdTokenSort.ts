// usdTokenSort.ts - sort / filter USD components and assemblies by their classification
// tokens (retake 03). Tokens come from tokens.json through GET /usd/library (`tokens`,
// `token_keys`): never a prim name, a vNNN or a LAST pointer.
//
// Order is stable and deterministic: groups by token value (natural order), the
// "no token" group last, then by name inside a group.

export const NO_TOKEN = '__none__'
export const SORT_NAME = 'name'

export interface TokenEntry { name: string; tokens?: Record<string, string> }

const collator = new Intl.Collator('en', { numeric: true, sensitivity: 'base' })

/** Value of *key* on *entry*, or NO_TOKEN when the asset has none (incomplete / unknown). */
export function tokenValue(entry: TokenEntry, key: string): string {
  return entry.tokens?.[key] || NO_TOKEN
}

/** Values of *key* present in *entries*, natural order, NO_TOKEN last if any entry lacks it. */
export function tokenValues(entries: TokenEntry[], key: string): string[] {
  const values = [...new Set(entries.map(e => tokenValue(e, key)))]
  return values.sort(compareValues)
}

function compareValues(a: string, b: string): number {
  if (a === b) return 0
  if (a === NO_TOKEN) return 1
  if (b === NO_TOKEN) return -1
  return collator.compare(a, b) || (a < b ? -1 : 1)
}

function compareNames(a: TokenEntry, b: TokenEntry): number {
  return collator.compare(a.name, b.name) || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0)
}

/**
 * Entries kept by *selected* (values of *key*; empty = all) and sorted by *key*
 * (SORT_NAME = by name only). Selected values absent from *entries* (obsolete) are
 * ignored, so a stale filter never empties the list.
 */
export function sortAndFilter<T extends TokenEntry>(entries: T[], key: string, selected: string[]): T[] {
  let out = entries
  if (key !== SORT_NAME && selected.length) {
    const present = new Set(entries.map(e => tokenValue(e, key)))
    const active = new Set(selected.filter(v => present.has(v)))
    if (active.size) out = out.filter(e => active.has(tokenValue(e, key)))
  }
  return [...out].sort((a, b) =>
    (key === SORT_NAME ? 0 : compareValues(tokenValue(a, key), tokenValue(b, key))) || compareNames(a, b))
}
