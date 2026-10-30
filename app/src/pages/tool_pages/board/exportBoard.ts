// exportBoard.ts — PNG / PDF export of the board without a server or a dependency (ADR 0075 n°5).
// The board is REDRAWN in a canvas from its records (not a screenshot of the DOM): frames,
// notes, cards, shapes, text, strokes, images, FLUX cards (their text), links. The PDF is
// written by hand: one JPEG image per page (DCTDecode), sized to fit A4 landscape or portrait.
// The file goes through Electron (save dialog, IPC), else a browser download.

import { DEFAULT_FONT, FILLS, STROKES, dims, edgePoint, fillOf, fontOf, parsePoints, strokeOf, type Box, type Item } from './model'

const INK = '#2a2f38'
const MAX_SIDE = 8000
const PAD = 24

export interface ExportSource {
  cards: Item[]                        // back to front (frames first)
  links: Item[]
  byId: Map<string, Item>
  media: (it: Item) => string | undefined
  fluxText: (it: Item) => string       // "asset CHAR / bob" or similar
  drawShotboard?: (ctx: CanvasRenderingContext2D, it: Item, b: Box) => void   // ADR 0083 (Shotboard.tsx)
}

function loadImage(url: string): Promise<HTMLImageElement | null> {
  return new Promise(ok => {
    const img = new Image()
    img.crossOrigin = 'anonymous'      // the backend answers CORS: the canvas stays exportable
    img.onload = () => ok(img)
    img.onerror = () => ok(null)
    img.src = url
  })
}

function wrap(ctx: CanvasRenderingContext2D, text: string, width: number): string[] {
  const out: string[] = []
  for (const para of text.split('\n')) {
    let line = ''
    for (const word of para.split(' ')) {
      const next = line ? `${line} ${word}` : word
      if (ctx.measureText(next).width > width && line) { out.push(line); line = word } else line = next
    }
    out.push(line)
  }
  return out
}

function textBlock(ctx: CanvasRenderingContext2D, it: Item, b: Box, centred: boolean, color: string) {
  const size = fontOf(it)
  ctx.font = `${it.bold ? 650 : 400} ${size}px system-ui, sans-serif`
  ctx.fillStyle = color
  ctx.textBaseline = 'top'
  ctx.textAlign = centred ? 'center' : 'left'
  const lines = wrap(ctx, it.text ?? '', b.w - 20)
  const lh = size * 1.35
  const y0 = centred ? b.y + (b.h - lines.length * lh) / 2 : b.y + 10
  lines.forEach((l, i) => { if (y0 + i * lh < b.y + b.h + 200) ctx.fillText(l, centred ? b.x + b.w / 2 : b.x + 10, y0 + i * lh) })
}

function shapePath(ctx: CanvasRenderingContext2D, it: Item, b: Box) {
  ctx.beginPath()
  const s = it.shape ?? 'rect'
  if (s === 'ellipse') ctx.ellipse(b.x + b.w / 2, b.y + b.h / 2, b.w / 2, b.h / 2, 0, 0, Math.PI * 2)
  else if (s === 'diamond') { ctx.moveTo(b.x + b.w / 2, b.y); ctx.lineTo(b.x + b.w, b.y + b.h / 2); ctx.lineTo(b.x + b.w / 2, b.y + b.h); ctx.lineTo(b.x, b.y + b.h / 2); ctx.closePath() }
  else ctx.roundRect(b.x, b.y, b.w, b.h, s === 'round' ? Math.min(16, b.h / 4) : it.type === 'note' ? 2 : it.type === 'shape' ? 2 : 6)
}

function arrow(ctx: CanvasRenderingContext2D, x: number, y: number, fx: number, fy: number) {
  const a = Math.atan2(y - fy, x - fx), s = 11
  ctx.beginPath()
  ctx.moveTo(x, y)
  ctx.lineTo(x - s * Math.cos(a + 0.45), y - s * Math.sin(a + 0.45))
  ctx.lineTo(x - s * Math.cos(a - 0.45), y - s * Math.sin(a - 0.45))
  ctx.closePath()
  ctx.fill()
}

/** The *region* of the board (board units) drawn at *scale*, on a light background. */
export async function renderBoard(src: ExportSource, region: Box, scale = 2): Promise<HTMLCanvasElement> {
  const k = Math.min(scale, MAX_SIDE / Math.max(region.w, region.h))
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(region.w * k))
  canvas.height = Math.max(1, Math.round(region.h * k))
  const ctx = canvas.getContext('2d')!
  ctx.fillStyle = '#f6f6f4'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.scale(k, k)
  ctx.translate(-region.x, -region.y)
  const inView = (b: Box) => b.x < region.x + region.w && b.x + b.w > region.x && b.y < region.y + region.h && b.y + b.h > region.y
  const cards = src.cards.filter(c => inView(dims(c)))
  const images = new Map<string, HTMLImageElement | null>()
  await Promise.all(cards.filter(c => c.type === 'image').map(async c => {
    const url = src.media(c)
    images.set(c.rid, url ? await loadImage(url) : null)
  }))

  for (const it of cards) {
    const b = dims(it)
    ctx.save()
    ctx.lineWidth = 1.5
    switch (it.type) {
      case 'frame':
        ctx.globalAlpha = 0.3
        ctx.fillStyle = fillOf(it)
        ctx.fillRect(b.x, b.y, b.w, b.h)
        ctx.globalAlpha = 1
        ctx.strokeStyle = '#b9bcc2'
        ctx.strokeRect(b.x, b.y, b.w, b.h)
        ctx.font = '600 13px system-ui, sans-serif'
        ctx.fillStyle = '#4a4f58'
        ctx.textBaseline = 'bottom'
        ctx.fillText(it.text ?? '', b.x, b.y - 4)
        break
      case 'ink': {
        const pts = parsePoints(it.points)
        ctx.strokeStyle = strokeOf(it, 'ink')
        ctx.lineWidth = it.stroke_width ?? 3
        ctx.lineCap = it.highlight ? 'butt' : 'round'
        ctx.lineJoin = 'round'
        ctx.globalAlpha = it.highlight ? 0.4 : 1
        ctx.beginPath()
        pts.forEach(([x, y], i) => i ? ctx.lineTo(b.x + x, b.y + y) : ctx.moveTo(b.x + x, b.y + y))
        ctx.stroke()
        break
      }
      case 'image': {
        const img = images.get(it.rid)
        if (img) {
          const r = Math.min(b.w / img.naturalWidth, b.h / img.naturalHeight)
          const w = img.naturalWidth * r, h = img.naturalHeight * r
          ctx.drawImage(img, b.x + (b.w - w) / 2, b.y + (b.h - h) / 2, w, h)
        } else { ctx.strokeStyle = '#b9bcc2'; ctx.strokeRect(b.x, b.y, b.w, b.h) }
        break
      }
      case 'text':
        textBlock(ctx, it, b, false, INK)
        break
      case 'shotboard':
        if (src.drawShotboard) src.drawShotboard(ctx, it, b)
        break
      case 'flux':
        ctx.fillStyle = FILLS.white
        ctx.strokeStyle = '#b9bcc2'
        ctx.beginPath(); ctx.roundRect(b.x, b.y, b.w, b.h, 6); ctx.fill(); ctx.stroke()
        textBlock(ctx, { ...it, text: src.fluxText(it), font_size: DEFAULT_FONT.flux }, b, false, INK)
        break
      default: {   // note, card, shape
        const shape = it.type === 'shape'
        shapePath(ctx, it, b)
        ctx.fillStyle = fillOf(it)
        ctx.fill()
        const stroke = shape ? strokeOf(it, 'ink') : it.stroke && it.stroke !== 'none' ? strokeOf(it) : '#c3c6cc'
        if (stroke !== STROKES.none) { ctx.strokeStyle = stroke; ctx.stroke() }
        textBlock(ctx, it, b, shape, INK)
      }
    }
    ctx.restore()
  }

  for (const l of src.links) {
    const a = l.from ? src.byId.get(l.from) : undefined, c = l.to ? src.byId.get(l.to) : undefined
    if (!a || !c) continue
    const A = dims(a), C = dims(c)
    if (!inView({ x: Math.min(A.x, C.x), y: Math.min(A.y, C.y), w: Math.abs(C.x - A.x) + C.w, h: Math.abs(C.y - A.y) + C.h })) continue
    const pa = edgePoint(A, a.type === 'shape' ? a.shape : undefined, C.x + C.w / 2, C.y + C.h / 2)
    const pc = edgePoint(C, c.type === 'shape' ? c.shape : undefined, A.x + A.w / 2, A.y + A.h / 2)
    ctx.save()
    ctx.strokeStyle = ctx.fillStyle = strokeOf(l, 'grey')
    ctx.lineWidth = 1.5
    ctx.setLineDash(l.dash === 'dashed' ? [8, 5] : l.dash === 'dotted' ? [2, 4] : [])
    ctx.beginPath(); ctx.moveTo(pa.x, pa.y); ctx.lineTo(pc.x, pc.y); ctx.stroke()
    ctx.setLineDash([])
    if (l.arrow_end) arrow(ctx, pc.x, pc.y, pa.x, pa.y)
    if (l.arrow_start) arrow(ctx, pa.x, pa.y, pc.x, pc.y)
    if (l.label) {
      const mx = (pa.x + pc.x) / 2, my = (pa.y + pc.y) / 2
      ctx.font = '12px system-ui, sans-serif'
      const w = ctx.measureText(l.label).width + 12
      ctx.fillStyle = '#ffffff'; ctx.fillRect(mx - w / 2, my - 10, w, 20)
      ctx.strokeRect(mx - w / 2, my - 10, w, 20)
      ctx.fillStyle = INK; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
      ctx.fillText(l.label, mx, my)
    }
    ctx.restore()
  }
  return canvas
}

/** Region around some boxes (a frame: its label above it fits in the padding). */
export function regionOf(boxes: Box[]): Box | null {
  if (!boxes.length) return null
  const x0 = Math.min(...boxes.map(b => b.x)), y0 = Math.min(...boxes.map(b => b.y))
  const x1 = Math.max(...boxes.map(b => b.x + b.w)), y1 = Math.max(...boxes.map(b => b.y + b.h))
  return { x: x0 - PAD, y: y0 - PAD, w: x1 - x0 + 2 * PAD, h: y1 - y0 + 2 * PAD }
}

const toBytes = (canvas: HTMLCanvasElement, type: string, quality?: number) => new Promise<Uint8Array>((ok, ko) =>
  canvas.toBlob(b => b ? b.arrayBuffer().then(a => ok(new Uint8Array(a)), ko) : ko(new Error('canvas vide')), type, quality))

export const pngBytes = (canvas: HTMLCanvasElement) => toBytes(canvas, 'image/png')

/** A PDF with one JPEG page per canvas, fitted in A4 (landscape or portrait like the image). */
export async function pdfBytes(canvases: HTMLCanvasElement[]): Promise<Uint8Array> {
  const enc = new TextEncoder()
  const chunks: Uint8Array[] = []
  const offsets: number[] = []
  let size = 0
  const push = (c: Uint8Array | string) => { const b = typeof c === 'string' ? enc.encode(c) : c; chunks.push(b); size += b.length }
  const obj = (n: number, body: () => void) => { offsets[n] = size; push(`${n} 0 obj\n`); body(); push('\nendobj\n') }
  push('%PDF-1.4\n%\xE2\xE3\xCF\xD3\n')
  const pageIds = canvases.map((_, i) => 3 + i * 3)
  obj(1, () => push('<< /Type /Catalog /Pages 2 0 R >>'))
  obj(2, () => push(`<< /Type /Pages /Kids [${pageIds.map(id => `${id} 0 R`).join(' ')}] /Count ${canvases.length} >>`))
  for (let i = 0; i < canvases.length; i++) {
    const c = canvases[i]
    const jpeg = await toBytes(c, 'image/jpeg', 0.9)
    const land = c.width >= c.height
    const [pw, ph] = land ? [842, 595] : [595, 842]
    const r = Math.min((pw - 40) / c.width, (ph - 40) / c.height)
    const w = c.width * r, h = c.height * r, x = (pw - w) / 2, y = (ph - h) / 2
    const [pid, cid, iid] = [pageIds[i], pageIds[i] + 1, pageIds[i] + 2]
    obj(pid, () => push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pw} ${ph}] /Resources << /XObject << /Im${i} ${iid} 0 R >> >> /Contents ${cid} 0 R >>`))
    const content = `q ${w.toFixed(2)} 0 0 ${h.toFixed(2)} ${x.toFixed(2)} ${y.toFixed(2)} cm /Im${i} Do Q`
    obj(cid, () => push(`<< /Length ${content.length} >>\nstream\n${content}\nendstream`))
    obj(iid, () => {
      push(`<< /Type /XObject /Subtype /Image /Width ${c.width} /Height ${c.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpeg.length} >>\nstream\n`)
      push(jpeg)
      push('\nendstream')
    })
  }
  const xref = size
  const count = 3 + canvases.length * 3
  let table = `xref\n0 ${count}\n0000000000 65535 f \n`
  for (let n = 1; n < count; n++) table += `${String(offsets[n]).padStart(10, '0')} 00000 n \n`
  push(table)
  push(`trailer\n<< /Size ${count} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`)
  const out = new Uint8Array(size)
  let at = 0
  for (const c of chunks) { out.set(c, at); at += c.length }
  return out
}

/** Electron save dialog, else a browser download. The saved path, or null (cancelled). */
export async function saveFile(name: string, bytes: Uint8Array, kind: 'png' | 'pdf'): Promise<string | null> {
  const filters = [kind === 'png' ? { name: 'PNG', extensions: ['png'] } : { name: 'PDF', extensions: ['pdf'] }]
  if (window.electronAPI?.saveBytes) return window.electronAPI.saveBytes(name, filters, bytes)
  const url = URL.createObjectURL(new Blob([bytes.buffer as ArrayBuffer], { type: kind === 'png' ? 'image/png' : 'application/pdf' }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
  return name
}
