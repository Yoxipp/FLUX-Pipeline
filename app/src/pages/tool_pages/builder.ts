// builder.ts — pure reducers of the page editor (04_PAGES_TOOL §5). Each one returns a new
// document and never mutates its input; they are only called on a user action, so a no-op
// rarely reaches the undo pile. No front test runner: checked by reading and in live (P7).

import type { PageDataSpec, PageDoc, PageFolder, PageLayoutItem, PageWidget, PageWidgetKind } from '../flow_editor/types'
import { rowsOf, widgetsOf } from './links'

export const MAX_ROW = 4

// -- ids --------------------------------------------------------------------------------------

const ACCENTS: Record<string, string> = { à: 'a', â: 'a', ä: 'a', á: 'a', ã: 'a', é: 'e', è: 'e', ê: 'e', ë: 'e', í: 'i', ì: 'i', î: 'i', ï: 'i',
  ó: 'o', ò: 'o', ô: 'o', ö: 'o', õ: 'o', ú: 'u', ù: 'u', û: 'u', ü: 'u', ç: 'c', ñ: 'n' }

// Same rule as pages.py suggest_id: "Dossier de destination" -> dossier_de_destination.
export function suggestId(label: string, taken: Set<string> = new Set()): string {
  let text = (label || '').toLowerCase().replace(/[àâäáãéèêëíìîïóòôöõúùûüçñ]/g, c => ACCENTS[c] ?? c)
    .replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '')
  if (!text || !/^[a-z]/.test(text)) text = text ? `w_${text}` : 'widget'
  const base = text.slice(0, 41).replace(/_+$/, '')
  let candidate = base
  for (let n = 2; taken.has(candidate); n++) candidate = `${base.slice(0, 41 - String(n).length - 1)}_${n}`
  return candidate
}

export const ID_RE = /^[a-z][a-z0-9_]{0,40}$/
export const PAGE_ID_RE = /^[a-z][a-z0-9_]{1,40}$/

export function takenIds(doc: PageDoc): Set<string> {
  return new Set([...widgetsOf(doc).map(w => w.id), ...foldersOf(doc.layout).map(f => f.id)])
}

export function foldersOf(items: PageLayoutItem[]): PageFolder[] {
  return items.flatMap(i => 'folder' in i ? [i.folder, ...foldersOf(i.children)] : [])
}

// -- new widgets ------------------------------------------------------------------------------

const LABELS: Record<PageWidgetKind, [string, string]> = {
  button: ['Lancer', 'Run'], float: ['Valeur', 'Value'], int: ['Nombre', 'Number'], text: ['Texte', 'Text'],
  path: ['Fichier', 'File'], dir: ['Dossier', 'Folder'], toggle: ['Option', 'Option'], select: ['Choix', 'Choice'],
  list: ['Liste', 'List'], separator: ['Separateur', 'Separator'], label: ['Texte fixe', 'Static text'],
  feed: ['Fil', 'Feed'], table: ['Tableau', 'Table'], cards: ['Cartes', 'Cards'], calendar: ['Calendrier', 'Calendar'],
  members: ['Membres', 'Members'], board: ['Board', 'Board'],
}

export function kindLabel(kind: PageWidgetKind, lang: string): string {
  return LABELS[kind][lang === 'en' ? 1 : 0]
}

// A collection that suits a data widget, created with it when the page has none (Scratch-like:
// drop a Feed, it works). Board -> kind board; feed -> text + channel; calendar -> title + when.
export function defaultData(kind: PageWidgetKind, taken: Set<string>): PageDataSpec | null {
  const id = (base: string) => { let c = base; for (let n = 2; taken.has(c); n++) c = `${base}_${n}`; return c }
  switch (kind) {
    case 'board': return { id: id('board'), kind: 'board' }
    case 'feed': return { id: id('messages'), fields: [{ id: 'text', type: 'text', label: 'Message' },
      { id: 'channel', type: 'select', label: 'Canal', options: [{ value: 'general', label: 'general' }] }] }
    case 'calendar': return { id: id('events'), fields: [{ id: 'title', type: 'str', label: 'Titre', required: true },
      { id: 'when', type: 'datetime', label: 'Quand' }, { id: 'note', type: 'text', label: 'Note' }] }
    case 'cards': return { id: id('tasks'), fields: [{ id: 'title', type: 'str', label: 'Titre', required: true },
      { id: 'status', type: 'select', label: 'Statut', options: [{ value: 'todo', label: 'A faire' }, { value: 'doing', label: 'En cours' }, { value: 'done', label: 'Fini' }] },
      { id: 'owner', type: 'user', label: 'Qui' }] }
    case 'table': return { id: id('rows'), fields: [{ id: 'name', type: 'str', label: 'Nom' }, { id: 'note', type: 'text', label: 'Note' }] }
    default: return null
  }
}

export function newWidget(kind: PageWidgetKind, doc: PageDoc, lang: string): { widget: PageWidget; data: PageDataSpec | null } {
  const label = kindLabel(kind, lang)
  const widget: PageWidget = { id: suggestId(label, takenIds(doc)), kind, label }
  if (kind === 'select') widget.options = [{ value: 'a', label: 'A' }, { value: 'b', label: 'B' }]
  if (kind === 'label') { widget.text = label; delete widget.label }
  if (kind === 'members') return { widget, data: null }
  let data: PageDataSpec | null = null
  if (['feed', 'table', 'cards', 'calendar', 'board'].includes(kind)) {
    const fit = doc.data.find(d => (kind === 'board') === (d.kind === 'board'))
    data = fit ? null : defaultData(kind, new Set(doc.data.map(d => d.id)))
    widget.source = { data: (fit ?? data)!.id }
    if (kind === 'feed' && data) widget.group_by = 'channel'
    if (kind === 'cards' && data) { widget.group_by = 'status'; widget.editable = true }
    if (kind === 'calendar' && data) widget.title = 'title'
    if (kind === 'table') widget.editable = true
  }
  return { widget, data }
}

// -- tree edits -------------------------------------------------------------------------------

type Items = PageLayoutItem[]

function mapItems(items: Items, fn: (item: PageLayoutItem) => PageLayoutItem | PageLayoutItem[] | null): Items {
  const out: Items = []
  for (const item of items) {
    const res = fn(item)
    if (res === null) continue
    for (const r of Array.isArray(res) ? res : [res]) {
      out.push('folder' in r ? { folder: r.folder, children: mapItems(r.children, fn) } : r)
    }
  }
  return out
}

const withLayout = (doc: PageDoc, layout: Items): PageDoc => ({ ...doc, layout })

// Where the selection sits: the row of a widget, a folder, or nothing (root).
export type Target = { widget: string } | { folder: string } | null

// A new widget: in the selected folder (new row at its end), next to the selected widget
// (same row when there is room, `beside`), else a new row after it, else at the end.
export function addWidget(doc: PageDoc, widget: PageWidget, target: Target, beside = false): PageDoc {
  const row: PageLayoutItem = { row: [widget] }
  if (target && 'folder' in target) {
    return withLayout(doc, mapItems(doc.layout, it => 'folder' in it && it.folder.id === target.folder
      ? { folder: it.folder, children: [...it.children, row] } : it))
  }
  if (target && 'widget' in target) {
    const alone = widget.kind === 'board'
    let done = false
    const layout = mapItems(doc.layout, it => {
      if (done || !('row' in it) || !it.row.some(w => w.id === target.widget)) return it
      done = true
      const full = it.row.length >= MAX_ROW || it.row.some(w => w.kind === 'board')
      if (beside && !full && !alone) {
        const k = it.row.findIndex(w => w.id === target.widget)
        return { row: [...it.row.slice(0, k + 1), widget, ...it.row.slice(k + 1)] }
      }
      return [it, row]
    })
    if (done) return withLayout(doc, layout)
  }
  return withLayout(doc, [...doc.layout, row])
}

export function addFolder(doc: PageDoc, folder: PageFolder, target: Target): PageDoc {
  const item: PageLayoutItem = { folder, children: [] }
  if (target && 'folder' in target) {
    return withLayout(doc, mapItems(doc.layout, it => 'folder' in it && it.folder.id === target.folder
      ? { folder: it.folder, children: [...it.children, item] } : it))
  }
  return withLayout(doc, [...doc.layout, item])
}

export function removeItem(doc: PageDoc, id: string): PageDoc {
  const layout = mapItems(doc.layout, it => {
    if ('folder' in it) return it.folder.id === id ? null : it
    const row = it.row.filter(w => w.id !== id)
    return row.length === it.row.length ? it : row.length ? { row } : null
  })
  return withLayout(doc, layout)
}

// Up / down among the siblings (rows and folders), left / right inside a row.
export function moveItem(doc: PageDoc, id: string, dir: -1 | 1, inRow = false): PageDoc {
  if (inRow) {
    return withLayout(doc, mapItems(doc.layout, it => {
      if (!('row' in it)) return it
      const k = it.row.findIndex(w => w.id === id)
      const j = k + dir
      if (k < 0 || j < 0 || j >= it.row.length) return it
      const row = [...it.row];
      [row[k], row[j]] = [row[j], row[k]]
      return { row }
    }))
  }
  const swap = (items: Items): Items => {
    const k = items.findIndex(it => 'folder' in it ? it.folder.id === id : it.row.some(w => w.id === id))
    if (k >= 0) {
      const j = k + dir
      if (j < 0 || j >= items.length) return items
      const out = [...items];
      [out[k], out[j]] = [out[j], out[k]]
      return out
    }
    return items.map(it => 'folder' in it ? { folder: it.folder, children: swap(it.children) } : it)
  }
  const layout = swap(doc.layout)
  return layout === doc.layout ? doc : withLayout(doc, layout)
}

// Take a widget out of its row into its own row just below ("couper la ligne").
export function splitOut(doc: PageDoc, id: string): PageDoc {
  return withLayout(doc, mapItems(doc.layout, it => {
    if (!('row' in it) || it.row.length < 2 || !it.row.some(w => w.id === id)) return it
    const w = it.row.find(x => x.id === id)!
    return [{ row: it.row.filter(x => x.id !== id) }, { row: [w] }]
  }))
}

export function updateWidget(doc: PageDoc, id: string, patch: Partial<PageWidget>): PageDoc {
  return withLayout(doc, mapItems(doc.layout, it => {
    if (!('row' in it) || !it.row.some(w => w.id === id)) return it
    return { row: it.row.map(w => {
      if (w.id !== id) return w
      const next: PageWidget = { ...w, ...patch }
      for (const k of Object.keys(next) as (keyof PageWidget)[]) if (next[k] === undefined || next[k] === '') delete next[k]
      next.id = next.id ?? w.id
      next.kind = next.kind ?? w.kind
      return next
    }) }
  }))
}

export function updateFolder(doc: PageDoc, id: string, patch: Partial<PageFolder>): PageDoc {
  return withLayout(doc, mapItems(doc.layout, it => 'folder' in it && it.folder.id === id
    ? { folder: { ...it.folder, ...patch }, children: it.children } : it))
}

// Local rename (not linked to a flow): the widget and the on_click.button_id that followed it.
export function renameLocal(doc: PageDoc, old: string, next: string): PageDoc {
  return withLayout(doc, mapItems(doc.layout, it => {
    if ('folder' in it) return it.folder.id === old ? { folder: { ...it.folder, id: next }, children: it.children } : it
    if (!it.row.some(w => w.id === old)) return it
    return { row: it.row.map(w => w.id !== old ? w : {
      ...w, id: next,
      ...(w.kind === 'button' && w.on_click?.button_id === old ? { on_click: { ...w.on_click, button_id: next } } : {}),
    }) }
  }))
}

// -- data collections --------------------------------------------------------------------------

export function addData(doc: PageDoc, spec: PageDataSpec): PageDoc {
  return doc.data.some(d => d.id === spec.id) ? doc : { ...doc, data: [...doc.data, spec] }
}

export function updateData(doc: PageDoc, id: string, patch: Partial<PageDataSpec>): PageDoc {
  return { ...doc, data: doc.data.map(d => d.id === id ? { ...d, ...patch } : d) }
}

export function removeData(doc: PageDoc, id: string): PageDoc {
  return { ...doc, data: doc.data.filter(d => d.id !== id) }
}

// -- lookups -----------------------------------------------------------------------------------

export function findWidget(doc: PageDoc, id: string | null): PageWidget | undefined {
  return id ? widgetsOf(doc).find(w => w.id === id) : undefined
}

export function findFolder(doc: PageDoc, id: string | null): PageFolder | undefined {
  return id ? foldersOf(doc.layout).find(f => f.id === id) : undefined
}

export function rowOf(doc: PageDoc, id: string): PageWidget[] | undefined {
  return rowsOf(doc.layout).find(r => r.some(w => w.id === id))
}

export function emptyPage(id: string, label: string): PageDoc {
  return { page: 1, id, label, icon: 'wrench', data: [], layout: [] }
}

