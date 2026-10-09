// TextureMapTable — the maps of a texturing app (Painter maps / shader channels, Mari
// channels), one row each: tick it, then its format, bit depth and size (2026-09-25:
// "par map la taille, la profondeur, le format ; pas de 32 bits proposé pour du png").
// Same table for Painter and Mari. "Défaut" = the format picked above / the app's own
// depth and size (the format list's first entry is the format picked above). The depths
// a format holds come from the backend (GET /dcc/texture/formats).

import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import { Btn, Select, SelectContent, SelectItem, SelectTrigger } from '../../components/shared/ui'

export type MapOpts = { format: string; bit_depth: string; size: string }
export type MapRow = { id: string; label: string; detail?: string }

const DEFAULT = '__default__'
const FALLBACK_FORMATS: Record<string, string[]> = {
  exr: ['32f', '16f'], tif: ['16', '8', '32f'], png: ['16', '8'], tga: ['8'], jpg: ['8'],
}
const DEPTH_LABEL: Record<string, string> = { '8': '8 bit', '16': '16 bit', '16f': '16 bit float', '32f': '32 bit float' }
const SIZE_LABEL: Record<string, string> = { '512': '512', '1024': '1K', '2048': '2K', '4096': '4K', '8192': '8K' }

let formatsCache: Record<string, string[]> | null = null

export function useTextureFormats(): Record<string, string[]> {
  const [formats, setFormats] = useState<Record<string, string[]>>(formatsCache ?? FALLBACK_FORMATS)
  useEffect(() => {
    if (formatsCache) return
    api.getTextureFormats()
      .then(r => { formatsCache = r.formats; setFormats(r.formats) })
      .catch(() => undefined)
  }, [])
  return formats
}

/** Settings sent to the backend: only what differs from "Défaut", for the ticked maps. */
export function mapParams(rows: MapRow[], checked: Set<string>, opts: Record<string, MapOpts>):
  Record<string, { format?: string; bit_depth?: string; size?: number }> {
  const out: Record<string, { format?: string; bit_depth?: string; size?: number }> = {}
  for (const r of rows) {
    const o = opts[r.id]
    if (!o || !checked.has(r.id)) continue
    if (o.format || o.bit_depth || o.size) {
      out[r.id] = { format: o.format || undefined, bit_depth: o.bit_depth || undefined, size: o.size ? Number(o.size) : undefined }
    }
  }
  return out
}

export function TextureMapTable({
  rows, checked, setChecked, opts, setOpts, defaultFormat, sizeDefaultLabel, header,
}: {
  rows: MapRow[]
  checked: Set<string>
  setChecked: (fn: (prev: Set<string>) => Set<string>) => void
  opts: Record<string, MapOpts>
  setOpts: (fn: (prev: Record<string, MapOpts>) => Record<string, MapOpts>) => void
  defaultFormat: string                 // the format picked above, without the dot
  sizeDefaultLabel: string              // "Taille Mari" / "Taille du texture set"
  header?: React.ReactNode
}) {
  const formats = useTextureFormats()
  const fmtNames = Object.keys(formats)
  const empty: MapOpts = { format: '', bit_depth: '', size: '' }

  const setRow = (ids: string[], patch: Partial<MapOpts>) => setOpts(prev => {
    const next = { ...prev }
    for (const id of ids) {
      const cur = { ...(next[id] ?? empty), ...patch }
      // A depth the new format cannot hold goes back to "Défaut".
      const fmt = cur.format || defaultFormat
      if (cur.bit_depth && !(formats[fmt] ?? []).includes(cur.bit_depth)) cur.bit_depth = ''
      next[id] = cur
    }
    return next
  })

  const selects = (o: MapOpts, ids: string[], disabled: boolean) => {
    const fmt = o.format || defaultFormat
    const depths = formats[fmt] ?? []
    return (
      <>
        <Select value={o.format || DEFAULT} onValueChange={v => setRow(ids, { format: v === DEFAULT ? '' : v })} disabled={disabled}>
          <SelectTrigger style={{ height: 24, width: 74, fontSize: 11 }} />
          <SelectContent>
            <SelectItem value={DEFAULT}>{`.${defaultFormat}`}</SelectItem>
            {fmtNames.map(f => <SelectItem key={f} value={f}>{`.${f}`}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={o.bit_depth || DEFAULT} onValueChange={v => setRow(ids, { bit_depth: v === DEFAULT ? '' : v })} disabled={disabled}>
          <SelectTrigger style={{ height: 24, width: 92, fontSize: 11 }} />
          <SelectContent>
            <SelectItem value={DEFAULT}>Défaut</SelectItem>
            {depths.map(d => <SelectItem key={d} value={d}>{DEPTH_LABEL[d] ?? d}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={o.size || DEFAULT} onValueChange={v => setRow(ids, { size: v === DEFAULT ? '' : v })} disabled={disabled}>
          <SelectTrigger style={{ height: 24, width: 92, fontSize: 11 }} />
          <SelectContent>
            <SelectItem value={DEFAULT}>{sizeDefaultLabel}</SelectItem>
            {Object.entries(SIZE_LABEL).map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}
          </SelectContent>
        </Select>
      </>
    )
  }

  const ticked = rows.filter(r => checked.has(r.id)).map(r => r.id)
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
        {header}
        <Btn ghost style={{ height: 26 }} onClick={() => setChecked(() => new Set(rows.map(r => r.id)))}>Tout</Btn>
        <Btn ghost style={{ height: 26 }} onClick={() => setChecked(() => new Set())}>Aucun</Btn>
        <span style={{ fontSize: 11, color: 'var(--ink-3)', fontFamily: 'var(--mono)' }}>{checked.size} / {rows.length}</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4, fontSize: 10.5, color: 'var(--ink-4)',
                    textTransform: 'uppercase', letterSpacing: '0.06em' }}>
        <span style={{ flex: 1 }}>Map</span>
        <span style={{ width: 74 }}>Format</span>
        <span style={{ width: 92 }}>Profondeur</span>
        <span style={{ width: 92 }}>Taille</span>
      </div>
      {/* Same settings for every ticked map at once. */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6, paddingBottom: 6, borderBottom: '1px solid var(--rule)' }}>
        <span style={{ flex: 1, minWidth: 0, fontSize: 11, color: 'var(--ink-3)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
          title="Réglage appliqué à toutes les maps cochées">Toutes</span>
        {selects(empty, ticked, ticked.length === 0)}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {rows.map(r => {
          const on = checked.has(r.id)
          return (
            <div key={r.id} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div title={r.id}
                onClick={() => setChecked(prev => { const n = new Set(prev); if (n.has(r.id)) n.delete(r.id); else n.add(r.id); return n })}
                style={{
                  flex: 1, minWidth: 0, padding: '4px 10px', borderRadius: 6, cursor: 'pointer',
                  fontFamily: 'var(--mono)', fontSize: 11, fontWeight: on ? 600 : 400,
                  border: on ? '1px solid var(--accent)' : '1px solid var(--rule-2)',
                  background: on ? 'var(--accent-soft)' : 'var(--paper-2)',
                  color: on ? 'var(--accent-hi)' : 'var(--ink-3)',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}>
                {r.label}{r.detail ? <span style={{ color: 'var(--ink-4)', fontWeight: 400 }}> {r.detail}</span> : null}
              </div>
              {selects(opts[r.id] ?? empty, [r.id], !on)}
            </div>
          )
        })}
      </div>
    </div>
  )
}
