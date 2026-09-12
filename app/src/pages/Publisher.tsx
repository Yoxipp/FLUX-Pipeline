import { useState, useEffect, useCallback, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { Trash2, FolderOpen, X } from 'lucide-react'
import { SoftwareSelector } from '../components/shared/SoftwareSelector'
import { Btn, SecTitle, FolderIcon, Check, Pill, Select, SelectTrigger, SelectContent, SelectItem } from '../components/shared/ui'
import { ExportOptions } from '../components/shared/ExportOptions'
import { schemaForExt, defaultOptions } from '../lib/mayaExportOptions'
import { houdiniSchemaForExt } from '../lib/houdiniExportOptions'
import { zbrushSchemaForExt, defaultZbrushOptions } from '../lib/zbrushExportOptions'
import { api } from '../api/client'
import { useProject } from '../ProjectContext'
import { useSettings } from '../hooks/useSettings'
import { readActiveInstancePort } from '../hooks/useActiveInstances'
import { toast } from 'sonner'

// Publish endpoints return version_str already prefixed with "v" (format_version
// -> "v001"), but the fallback path can return a bare "001". Normalise to exactly
// one leading "v" so toasts never show "vv001" (nor a bare "001").
function versionLabel(versionStr: string): string {
  return `v${String(versionStr ?? '').replace(/^v/i, '')}`
}

// ── Resizable right panel (per-viewer UI pref) ────────────────────────────────
const RIGHT_WIDTH_KEY = 'flux.ui.publisherRightWidth'
const RIGHT_WIDTH_DEFAULT = 460
const RIGHT_WIDTH_MIN = 320

function readStoredWidth(): number {
  try {
    const v = parseInt(localStorage.getItem(RIGHT_WIDTH_KEY) || '', 10)
    if (!Number.isNaN(v)) return v
  } catch { /* private mode / blocked storage */ }
  return RIGHT_WIDTH_DEFAULT
}

// The best-known Houdini point attributes, proposed when adding an attribute row.
const COMMON_HOU_ATTRS = [
  'boneCapture', 'curveu', 'uv', 'N', 'Cd', 'pscale', 'v', 'orient', 'up', 'width', 'rest', 'id', 'name', 'mask',
]

// Editable combobox for an attribute name: free text + a dropdown of common attrs.
function AttrCombo({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [open, setOpen] = useState(false)
  const q = value.trim().toLowerCase()
  const matches = q ? COMMON_HOU_ATTRS.filter(a => a.toLowerCase().includes(q)) : COMMON_HOU_ATTRS
  return (
    <div style={{ position: 'relative', flex: 1, minWidth: 0 }}>
      <input
        value={value}
        placeholder="nom de l'attribut point"
        onChange={e => { onChange(e.target.value); setOpen(true) }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        style={{
          width: '100%', height: 26, background: 'var(--bg-deep)', border: '1px solid var(--rule-2)',
          borderRadius: 5, padding: '0 8px', fontFamily: 'var(--mono)', fontSize: 11,
          color: 'var(--ink)', boxShadow: 'var(--shadow-inset)', outline: 'none',
        }}
      />
      {open && matches.length > 0 && (
        <div className="card" style={{
          position: 'absolute', top: 29, left: 0, width: '100%', zIndex: 30,
          maxHeight: 180, overflowY: 'auto', padding: 3, boxShadow: 'var(--shadow-md)',
        }}>
          {matches.map(a => (
            <div
              key={a}
              onMouseDown={e => { e.preventDefault(); onChange(a); setOpen(false) }}
              className="row"
              style={{ padding: '5px 8px', fontSize: 11, cursor: 'pointer', borderRadius: 4, color: 'var(--ink-2)', fontFamily: 'var(--mono)' }}
            >
              {a}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Utilities ────────────────────────────────────────────────────────────────

/** Click-to-copy monospaced command block. */
function CopyBlock({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div
      onClick={() => {
        void navigator.clipboard.writeText(text)
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
      }}
      title="Cliquer pour copier"
      style={{
        fontFamily: 'var(--mono)', fontSize: 8,
        color: copied ? 'var(--ok)' : 'var(--accent-hi)',
        background: 'var(--bg-deep)', border: `1px solid ${copied ? 'var(--ok)' : 'var(--rule-2)'}`,
        borderRadius: 4, padding: '5px 8px', cursor: 'pointer',
        wordBreak: 'break-all', lineHeight: 1.6, userSelect: 'all',
        transition: 'color 0.2s, border-color 0.2s',
      }}
    >
      {copied ? '✓ Copié !' : text}
    </div>
  )
}

// One step of the Maya reconnect guide — uses the UI sans font, not mono.
function MayaStep({ n, done, title, desc }: { n: number; done: boolean; title: string; desc: string }) {
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
      <div style={{
        width: 20, height: 20, borderRadius: '50%', flexShrink: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: done ? 'var(--ok)' : 'var(--accent)', color: 'white',
        fontFamily: 'var(--sans)', fontSize: 10, fontWeight: 700,
      }}>{done ? '✓' : n}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 1, minWidth: 0 }}>
        <span style={{ fontFamily: 'var(--sans)', fontSize: 12, fontWeight: 600, color: 'var(--ink)' }}>{title}</span>
        <span style={{ fontFamily: 'var(--sans)', fontSize: 11, color: 'var(--ink-4)', lineHeight: 1.4, wordBreak: 'break-all' }}>{desc}</span>
      </div>
    </div>
  )
}

function formatToken(raw: string): string {
  return raw
    .normalize('NFD').replace(/\p{Mn}/gu, '')
    .toUpperCase()
    .replace(/[\s-]/g, '_')
    .replace(/[^A-Z0-9_]/g, '')
    .replace(/_+/g, '_')
    .replace(/^_|_$/g, '')
}

function formatSeqLabel(raw: string): string {
  const n = parseInt(raw.replace(/[^0-9]/g, ''), 10)
  if (isNaN(n)) return raw.toUpperCase()
  return `SEQ${String(n).padStart(3, '0')}`
}

function formatShotLabel(raw: string): string {
  const n = parseInt(raw.replace(/[^0-9]/g, ''), 10)
  if (isNaN(n)) return raw.toUpperCase()
  return `SHOT${String(n).padStart(3, '0')}`
}

// Houdini ROP node type → export extension.
// Keys are lowercased; lookup normalises raw type names (strips ::version suffix, lowercases).
const NODE_TYPE_TO_EXT: Record<string, string> = {
  // Geometry
  rop_geometry:           '.bgeo',
  geometry:               '.bgeo',
  filecache:              '.bgeo',
  // Alembic
  rop_alembic:            '.abc',
  alembic:                '.abc',
  // USD
  usdexport:              '.usd',
  usd_rop:                '.usd',
  usdrender:              '.usd',
  lopnet:                 '.usd',
  // Renders
  ifd:                    '.exr',
  karma:                  '.exr',
  karma_rop:              '.exr',
  karma_old:              '.exr',
  opengl:                 '.exr',
  rop_comp:               '.exr',
  rop_opengl:             '.exr',
  // FBX
  filmboxcharacterimport: '.fbx',
  rop_fbx:                '.fbx',
  // HIP
  rop_hip:                '.hip',
}

function resolveNodeExt(rawType: string): string | undefined {
  // Strip namespace (Driver/) and version suffix (::2), lowercase
  const normalised = rawType.split('/').pop()!.split('::')[0].toLowerCase()
  return NODE_TYPE_TO_EXT[normalised]
}

// Export formats offered per software — only what each DCC can actually write.
// USD comes in three flavours: .usd (auto), .usda (ascii), .usdc (binary crate).
const USD_FORMATS = ['.usd', '.usda', '.usdc']

const EXPORT_FORMATS_BY_DCC: Record<string, string[]> = {
  Maya:           ['.abc', '.fbx', '.obj', '.ma', '.mb', ...USD_FORMATS],
  Houdini:        ['.abc', '.bgeo', '.vdb', '.obj', '.fbx', '.exr', '.hip', ...USD_FORMATS],
  Nuke:           ['.exr', '.dpx', '.tif', '.png', '.mov', '.nk'],
  'Substance P.': ['.png', '.exr', '.tga', '.tif', '.jpg'],
  ZBrush:         ['.ztl', '.obj', '.fbx'],
  Marvelous:      ['.obj', '.fbx', '.abc', '.zprj'],
  Photoshop:      ['.psd', '.png', '.tif', '.jpg', '.exr'],
}

// Fallback (e.g. "Fichier local"): a broad, DCC-agnostic superset.
const DEFAULT_EXPORT_FORMATS = ['.abc', '.fbx', '.obj', '.exr', '.png', '.tif', ...USD_FORMATS]

function formatsForDcc(dcc: string): string[] {
  return EXPORT_FORMATS_BY_DCC[dcc] ?? DEFAULT_EXPORT_FORMATS
}

// ── Types ─────────────────────────────────────────────────────────────────────

type PublishMode = 'asset' | 'shot'

interface ComposerSel {
  [key: string]: string
  category: string   // asset: CHAR / PROPS / ENV / FX
  name:     string
  task:     string   // asset: GEO / SHADING / GROOM / RIG / CFX / MULT
  instance: string
  variante: string
  seq:      string   // shot
  shot:     string   // shot
}

const EMPTY_SEL: ComposerSel = { category: '', name: '', task: '', instance: '', variante: '', seq: '', shot: '' }

// Texture-map tokens recognised for autogroup. A file named "<Mesh>_<Token>[...]"
// (e.g. Mesh_BCol.exr, Mesh_ZDisp.1001.exr) publishes under INSTANCE = <Token>.
// the maintainer's convention (extend freely): BCol, Rough, Disp, ZDisp, Bump, Norm, SSS, Iso.
const MAP_TOKENS = [
  'BCOL', 'ROUGH', 'ZDISP', 'DISP', 'BUMP', 'NORM', 'SSS', 'ISO',
  'METAL', 'SPEC', 'AO', 'EMISS', 'OPACITY', 'TRANS',
]

// Image/texture extensions kept when importing a whole folder (no dot, lowercase).
const TEXTURE_EXTS = [
  'exr', 'png', 'jpg', 'jpeg', 'tif', 'tiff', 'tga', 'tx', 'hdr', 'bmp', 'webp', 'psd',
]

// Basename without directory or extension(s) — strips a UDIM/frame tail too
// (Mesh_BCol.1001.exr -> "Mesh_BCol", Mesh_Disp.exr -> "Mesh_Disp").
function fileStem(path: string): string {
  const base = path.replace(/\\/g, '/').split('/').pop() || path
  return base.split('.')[0] || base
}

// Derive the INSTANCE (map token) for a texture file. Prefers a recognised
// MAP_TOKENS match anywhere in the name; otherwise falls back to the last
// underscore segment (so any suffix still groups sensibly). Uppercased.
function parseMapToken(path: string): string {
  const stem = fileStem(path).toUpperCase()
  const segs = stem.split(/[_\-]/).filter(Boolean)
  for (const tok of MAP_TOKENS) {
    if (segs.includes(tok)) return tok
  }
  return segs.length > 1 ? segs[segs.length - 1] : (segs[0] || 'null')
}

// Publisher category → pipeline CLASS token. "FX" is a display label for FXRIG.
const CATEGORY_TO_CLASS: Record<string, string> = { CHAR: 'CHAR', PROPS: 'PROPS', ENV: 'ENV', FX: 'FXRIG' }
const ASSET_CATEGORIES = ['CHAR', 'PROPS', 'ENV', 'FX'] as const
// Coarse task = TYPE token (fixed order); label shown title-cased, value uppercase.
const ASSET_TASKS: { value: string; label: string }[] = [
  { value: 'GEO', label: 'Geo' }, { value: 'ANIM', label: 'Anim' }, { value: 'SHADING', label: 'Shading' },
  { value: 'GROOM', label: 'Groom' }, { value: 'RIG', label: 'Rig' }, { value: 'CFX', label: 'Cfx' },
  { value: 'MULT', label: 'Mult' }, { value: 'REF', label: 'Ref' },
]

// Info popover copy for each token (explanation · expected · concrete example).
interface TokenInfo { title: string; desc: string; expected: string; example: string }
const TOKEN_INFO: Record<string, TokenInfo> = {
  category: { title: 'Catégorie', desc: "Le type d'asset dans le pipeline.", expected: 'CHAR, PROPS, ENV ou FX', example: 'CHAR → assets/chara' },
  name:     { title: 'Name', desc: "Le nom de l'asset. Seuls les noms de la catégorie choisie sont proposés.", expected: 'Nom court, sans espace', example: 'JEROME' },
  task:     { title: 'Task', desc: "L'étape de production — détermine le sous-dossier de l'asset.", expected: 'Geo, Shading, Groom, Rig, Cfx, Mult ou Ref', example: 'Rig → assets/chara/JEROME/rig' },
  instance: { title: 'Instance', desc: 'Sous-variante fonctionnelle. Suggestions basées sur Catégorie + Name + Task.', expected: 'Champ libre (null par défaut)', example: 'CHAR_RIG_JEROME_null_LAST' },
  variante: { title: 'Variante', desc: 'Déclinaison optionnelle. Suggestions basées sur Catégorie + Name + Task + Instance.', expected: 'Champ libre (optionnel)', example: 'CHAR_RIG_JEROME_null_HERO_LAST' },
  seq:      { title: 'Sequence', desc: 'La séquence du plan.', expected: 'Numéro → SEQ###', example: 'SEQ001' },
  shot:     { title: 'Shot', desc: 'Le plan dans la séquence.', expected: 'Numéro → SHOT###', example: 'SHOT010' },
  shotName: { title: 'Name', desc: 'La classe du plan (task shot). Suggestions basées sur Sequence + Shot.', expected: 'Champ libre', example: 'ANIM, LAYOUT, FX, CFX…' },
  shotVariante: { title: 'Variante', desc: 'Remplace Instance en mode Shot. Suggestions basées sur Sequence + Shot + Name.', expected: 'Champ libre', example: 'ANIM_SEQ001_SHOT010_block_LAST' },
}

// ── PublishComposer ───────────────────────────────────────────────────────────

// Circled "i" with a click popover — explanation / expected value / concrete example.
function InfoDot({ info }: { info: TokenInfo }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [open])
  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-flex' }}>
      <div
        onClick={e => { e.stopPropagation(); setOpen(o => !o) }}
        title="Infos"
        style={{
          width: 13, height: 13, borderRadius: '50%', flexShrink: 0,
          border: '1px solid ' + (open ? 'var(--accent)' : 'var(--rule-2)'),
          color: open ? 'var(--accent-hi)' : 'var(--ink-4)',
          background: open ? 'var(--accent-soft)' : 'transparent',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontFamily: 'var(--sans)', fontSize: 9, fontWeight: 700, fontStyle: 'italic',
          cursor: 'pointer', lineHeight: 1,
        }}
      >i</div>
      {open && (
        <div style={{
          position: 'absolute', top: 'calc(100% + 6px)', left: 0, zIndex: 600, width: 210,
          padding: '10px 12px', background: 'var(--paper)', border: '1px solid var(--rule-2)',
          borderRadius: 8, boxShadow: 'var(--shadow-md)', fontFamily: 'var(--sans)',
        }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--ink)', marginBottom: 4 }}>{info.title}</div>
          <div style={{ fontSize: 11, color: 'var(--ink-3)', lineHeight: 1.45, marginBottom: 6 }}>{info.desc}</div>
          <div style={{ fontSize: 10, color: 'var(--ink-4)' }}>Attendu : <span style={{ color: 'var(--ink-2)' }}>{info.expected}</span></div>
          <div style={{ fontSize: 10, color: 'var(--ink-4)', marginTop: 2 }}>Ex. : <span style={{ fontFamily: 'var(--mono)', color: 'var(--accent-hi)' }}>{info.example}</span></div>
        </div>
      )}
    </div>
  )
}

// A composer module: label + info dot, then a value box — a fixed dropdown or a
// free-text combobox whose dropdown lists contextual suggestions (`options`).
function ModuleBox({ label, info, value, placeholder, options, fixed, onChange, onArchiveOption }: {
  label: string; info: TokenInfo; value: string; placeholder?: string
  options: string[]; fixed?: boolean; onChange: (v: string) => void
  // When set, each option gets a small cross that archives that token (ghost or
  // not) into ARCHIVE/ after confirmation. Only wired on per-project dropdowns.
  onArchiveOption?: (v: string) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [open])
  const q = value.trim().toLowerCase()
  const shown = fixed ? options : (q ? options.filter(o => o.toLowerCase().includes(q)) : options)
  const filled = !!value
  return (
    <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 3 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, paddingLeft: 2 }}>
        <span style={{ fontSize: 8, fontFamily: 'var(--mono)', color: 'var(--ink-4)', textTransform: 'uppercase', letterSpacing: '0.1em' }}>{label}</span>
        <InfoDot info={info} />
      </div>
      <div ref={ref} style={{ position: 'relative' }}>
        {fixed ? (
          <div
            onClick={() => setOpen(o => !o)}
            className="scale-hover"
            style={{
              height: 30, padding: '0 8px', display: 'flex', alignItems: 'center', cursor: 'pointer',
              borderRadius: 5, border: '1px solid ' + (filled ? 'var(--accent)' : 'var(--rule-2)'),
              background: filled ? 'var(--accent-soft)' : 'var(--bg-deep)', boxShadow: 'var(--shadow-inset)',
              fontFamily: 'var(--mono)', fontSize: 10, color: filled ? 'var(--accent-hi)' : 'var(--ink-4)',
              fontWeight: filled ? 600 : 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}
          >{value || placeholder || '-'}</div>
        ) : (
          <input
            value={value}
            placeholder={placeholder}
            onChange={e => { onChange(e.target.value); setOpen(true) }}
            onFocus={() => setOpen(true)}
            style={{
              width: '100%', height: 30, padding: '0 8px', boxSizing: 'border-box',
              borderRadius: 5, border: '1px solid ' + (filled ? 'var(--accent)' : 'var(--rule-2)'),
              background: 'var(--bg-deep)', boxShadow: 'var(--shadow-inset)', outline: 'none',
              fontFamily: 'var(--mono)', fontSize: 10, color: filled ? 'var(--accent-hi)' : 'var(--ink)',
              fontWeight: filled ? 600 : 400,
            }}
          />
        )}
        {open && shown.length > 0 && (
          <div style={{
            position: 'absolute', top: 'calc(100% + 3px)', left: 0, zIndex: 500, minWidth: '100%',
            maxHeight: 180, overflowY: 'auto', background: 'var(--paper)',
            border: '1px solid var(--rule-2)', borderRadius: 5, boxShadow: 'var(--shadow)',
          }}>
            {shown.map(o => (
              <div
                key={o}
                onMouseDown={e => { e.preventDefault(); onChange(o); setOpen(false) }}
                style={{
                  padding: '5px 8px', fontSize: 10, fontFamily: 'var(--mono)', cursor: 'pointer', whiteSpace: 'nowrap',
                  color: o === value ? 'var(--accent-hi)' : 'var(--ink-2)',
                  background: o === value ? 'var(--accent-soft)' : 'transparent',
                  display: 'flex', alignItems: 'center', gap: 6,
                }}
              >
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis' }}>{o}</span>
                {onArchiveOption && (
                  <button
                    title="Archiver ce token (déplace le dossier vers ARCHIVE/)"
                    onMouseDown={e => { e.preventDefault(); e.stopPropagation(); setOpen(false); onArchiveOption(o) }}
                    style={{
                      flexShrink: 0, width: 15, height: 15, borderRadius: 3, border: 'none',
                      background: 'transparent', color: 'var(--ink-4)', cursor: 'pointer',
                      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                    }}
                    onMouseEnter={e => (e.currentTarget.style.color = 'var(--err)')}
                    onMouseLeave={e => (e.currentTarget.style.color = 'var(--ink-4)')}
                  ><X size={10} strokeWidth={2} /></button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

interface ComposerProps {
  project: string
  tokens:  Record<string, Record<string, string>>
  seqs:    string[]
  shots:   string[]
  mode:    PublishMode
  sel:     ComposerSel
  onModeSwitch: () => void
  onSelect:     (key: string, value: string) => void
  onArchiveToken: (field: 'name' | 'instance' | 'seq' | 'shot', value: string) => void
}

function PublishComposer({ project, tokens, seqs, shots, mode, sel, onModeSwitch, onSelect, onArchiveToken }: ComposerProps) {
  // Asset names for the selected category (filtered by its CLASS path)
  const cls = CATEGORY_TO_CLASS[sel.category] ?? ''
  const classPath = (tokens.CLASS?.[cls] ?? '').replace(/\\/g, '/')
  const names = classPath
    ? Object.keys(tokens.NAME ?? {}).filter(k => (tokens.NAME?.[k] ?? '').replace(/\\/g, '/').startsWith(classPath + '/'))
    : []

  // Contextual suggestions, scanned from disk (never global)
  const [instanceSug, setInstanceSug] = useState<string[]>([])
  const [varianteSug, setVarianteSug] = useState<string[]>([])
  const [shotNameSug, setShotNameSug] = useState<string[]>([])

  useEffect(() => {
    if (mode !== 'asset' || !project || !sel.category || !sel.name || !sel.task) { setInstanceSug([]); return }
    let ok = true
    api.suggestTokens({ project, field: 'instance', mode: 'asset', class_token: cls, name: sel.name, type_token: sel.task })
      .then(d => { if (ok) setInstanceSug(d.suggestions) }).catch(() => { if (ok) setInstanceSug([]) })
    return () => { ok = false }
  }, [mode, project, cls, sel.category, sel.name, sel.task])

  useEffect(() => {
    let ok = true
    if (mode === 'asset') {
      if (!project || !sel.category || !sel.name || !sel.task) { setVarianteSug([]); return }
      api.suggestTokens({ project, field: 'variante', mode: 'asset', class_token: cls, name: sel.name, type_token: sel.task, instance: sel.instance || 'null' })
        .then(d => { if (ok) setVarianteSug(d.suggestions) }).catch(() => { if (ok) setVarianteSug([]) })
    } else {
      if (!project || !sel.seq || !sel.shot || !sel.name) { setVarianteSug([]); return }
      api.suggestTokens({ project, field: 'variante', mode: 'shot', seq: sel.seq, shot: sel.shot, name: sel.name })
        .then(d => { if (ok) setVarianteSug(d.suggestions) }).catch(() => { if (ok) setVarianteSug([]) })
    }
    return () => { ok = false }
  }, [mode, project, cls, sel.category, sel.name, sel.task, sel.instance, sel.seq, sel.shot])

  useEffect(() => {
    if (mode !== 'shot' || !project || !sel.seq || !sel.shot) { setShotNameSug([]); return }
    let ok = true
    api.suggestTokens({ project, field: 'name', mode: 'shot', seq: sel.seq, shot: sel.shot })
      .then(d => { if (ok) setShotNameSug(d.suggestions) }).catch(() => { if (ok) setShotNameSug([]) })
    return () => { ok = false }
  }, [mode, project, sel.seq, sel.shot])

  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 6 }}>
      {/* Asset / Shot toggle */}
      <div onClick={onModeSwitch} className="scale-hover" style={{
        width: 52, flexShrink: 0, height: 30,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        border: '1px solid var(--rule-2)', borderRadius: 5,
        background: mode === 'shot' ? 'var(--accent-soft)' : 'var(--bg-deep)',
        cursor: 'pointer', fontSize: 8, fontFamily: 'var(--mono)',
        color: mode === 'shot' ? 'var(--accent-hi)' : 'var(--ink-3)',
        fontWeight: 700, letterSpacing: '0.08em', userSelect: 'none', boxShadow: 'var(--shadow-xs)',
      }}>{mode === 'asset' ? 'ASSET' : 'SHOT'}</div>

      {mode === 'asset' ? (
        <>
          <ModuleBox label="Catégorie" info={TOKEN_INFO.category} value={sel.category} fixed options={[...ASSET_CATEGORIES]} placeholder="—" onChange={v => onSelect('category', v)} />
          <ModuleBox
            label="Name" info={TOKEN_INFO.name} value={sel.name} options={names}
            placeholder={sel.category ? 'nom…' : 'catégorie ?'} onChange={v => onSelect('name', v)}
            onArchiveOption={sel.category ? (v => onArchiveToken('name', v)) : undefined}
          />
          <ModuleBox label="Task" info={TOKEN_INFO.task} value={sel.task} fixed options={ASSET_TASKS.map(t => t.value)} placeholder="—" onChange={v => onSelect('task', v)} />
          <ModuleBox
            label="Instance" info={TOKEN_INFO.instance} value={sel.instance} options={instanceSug}
            placeholder="null" onChange={v => onSelect('instance', v)}
            onArchiveOption={(sel.category && sel.name && sel.task) ? (v => onArchiveToken('instance', v)) : undefined}
          />
          <ModuleBox label="Variante" info={TOKEN_INFO.variante} value={sel.variante} options={varianteSug} placeholder="(option)" onChange={v => onSelect('variante', v)} />
        </>
      ) : (
        <>
          <ModuleBox
            label="Sequence" info={TOKEN_INFO.seq} value={sel.seq} options={seqs}
            placeholder="SEQ001" onChange={v => onSelect('seq', v)}
            onArchiveOption={v => onArchiveToken('seq', v)}
          />
          <ModuleBox
            label="Shot" info={TOKEN_INFO.shot} value={sel.shot} options={shots}
            placeholder="SHOT010" onChange={v => onSelect('shot', v)}
            onArchiveOption={sel.seq ? (v => onArchiveToken('shot', v)) : undefined}
          />
          <ModuleBox label="Name" info={TOKEN_INFO.shotName} value={sel.name} options={shotNameSug} placeholder="task…" onChange={v => onSelect('name', v)} />
          <ModuleBox label="Variante" info={TOKEN_INFO.shotVariante} value={sel.variante} options={varianteSug} placeholder="null" onChange={v => onSelect('variante', v)} />
        </>
      )}
    </div>
  )
}

// ── Publisher ─────────────────────────────────────────────────────────────────

export function Publisher() {
  const { settings } = useSettings()
  const location = useLocation()
  const [dcc, setDcc]           = useState('Maya')
  const { project, projects, setProject } = useProject()
  const [tokens, setTokens]     = useState<Record<string, Record<string, string>>>({})

  // Composer state
  const [mode, setMode]       = useState<PublishMode>('asset')
  const [sel, setSel]         = useState<ComposerSel>(EMPTY_SEL)
  const [seqs, setSeqs]   = useState<string[]>([])
  const [shots, setShots] = useState<string[]>([])

  // Export config (shared for all DCCs)
  const [exportExt, setExportExt]   = useState('.abc')
  const [isSequence, setIsSequence] = useState(false)
  const [frameStart, setFrameStart] = useState(1)
  const [frameEnd, setFrameEnd]     = useState(100)
  const [frameStep, setFrameStep]   = useState(1)

  // Per-format export options (Maya). Reset to the format's defaults whenever the
  // active extension changes — defaults reproduce the pre-options export exactly.
  const [mayaExportOpts, setMayaExportOpts] = useState<Record<string, unknown>>(() => defaultOptions(schemaForExt('.abc')))
  const [houExportOpts, setHouExportOpts] = useState<Record<string, unknown>>(() => defaultOptions(houdiniSchemaForExt('.abc')))
  // Houdini export attribute filter (F): keep-only / remove named point attributes.
  const [houAttrMode, setHouAttrMode] = useState<'none' | 'keep' | 'remove'>('none')
  const [houAttrNames, setHouAttrNames] = useState<string[]>([])

  // Resizable right panel (draggable splitter). Width persists per viewer; a
  // "Reset interface" action in the settings fires 'flux:reset-ui' to restore it.
  const splitContainerRef = useRef<HTMLDivElement>(null)
  const [rightWidth, setRightWidth] = useState<number>(() => readStoredWidth())
  // Node path we last auto-suggested a format for, so the Houdini poll suggests a
  // format once per newly-selected node instead of clobbering a manual override
  // (e.g. rop_geometry → .obj) on every 3s tick.
  const autoExtForNodeRef = useRef<string | null>(null)

  useEffect(() => {
    try { localStorage.setItem(RIGHT_WIDTH_KEY, String(rightWidth)) } catch { /* blocked storage */ }
  }, [rightWidth])

  useEffect(() => {
    const onReset = () => setRightWidth(RIGHT_WIDTH_DEFAULT)
    window.addEventListener('flux:reset-ui', onReset)
    return () => window.removeEventListener('flux:reset-ui', onReset)
  }, [])

  const startSplitDrag = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    const startX = e.clientX
    const startW = rightWidth
    const rect = splitContainerRef.current?.getBoundingClientRect()
    const maxW = rect ? Math.max(360, rect.width - 360) : 900
    const onMove = (ev: MouseEvent) => {
      const dx = ev.clientX - startX
      setRightWidth(Math.min(Math.max(startW - dx, RIGHT_WIDTH_MIN), maxW))
    }
    const onUp = () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }, [rightWidth])

  // Source / description / state
  const [sourcePath, setSourcePath]   = useState('')
  // Local-file source: multiple files can be picked at once (texture sets). The
  // first also fills sourcePath so the single-file path/name UI still works.
  const [localFiles, setLocalFiles]   = useState<string[]>([])
  // Autogroup: derive each file's INSTANCE (map token) from its filename so a
  // whole texture set publishes into one folder per map. Off = one instance for all.
  const [autoGroup, setAutoGroup]     = useState(true)
  const [description, setDescription] = useState('')
  const [publishing, setPublishing]   = useState(false)
  // Optional published-name override (local file). null = follow the token composer.
  const [nameOverride, setNameOverride] = useState<string | null>(null)

  // ZBrush-specific
  const [zbrushConnected, setZbrushConnected] = useState(false)
  const [zbrushVersion, setZbrushVersion]     = useState<string | null>(null)
  // Per-format ZBrush export options, rendered via <ExportOptions> in the right
  // panel like Maya/Houdini. Reset to the format defaults when the format changes.
  const [zbrushExportOpts, setZbrushExportOpts] = useState<Record<string, unknown>>(
    () => defaultZbrushOptions('.obj'),
  )


  // Houdini-specific
  const [ropNodePath, setRopNodePath]             = useState('')
  const [houdiniConnected, setHoudiniConnected]   = useState(false)
  const [houdiniVersion, setHoudiniVersion]       = useState<string | null>(null)
  const [detectedNodeType, setDetectedNodeType]   = useState<string | null>(null)

  // Maya-specific
  const [mayaConnected, setMayaConnected]           = useState(false)
  const [mayaScope, setMayaScope]                   = useState<'scene' | 'selection'>('scene')
  const [lightUsd, setLightUsd]                     = useState(false)   // Maya UsdSkel light export
  const [lightInclude, setLightInclude]             = useState({ geo: true, skel: true, anim: true, weights: true, uv: true })
  const [mayaConnectCmd, setMayaConnectCmd]         = useState<string | null>(null)
  const [mayaAutostartInstalled, setMayaAutostartInstalled] = useState<boolean | null>(null)
  const [mayaStartupFile, setMayaStartupFile]       = useState<string | null>(null)

  // Projects come from the shared ProjectContext (useProject) — no local fetch.

  // Tokens for selected project
  const reloadTokens = useCallback(() => {
    if (!project) { setTokens({}); return }
    api.getTokens(project).then(d => setTokens(d.tokens)).catch(() => setTokens({}))
  }, [project])
  useEffect(() => { reloadTokens() }, [reloadTokens])

  // Ghost-token archive flow (composer cross): confirmation before moving the
  // token's folder to ARCHIVE/ and dropping it from tokens.json.
  const [tokenArchive, setTokenArchive] = useState<{
    field: 'name' | 'instance' | 'seq' | 'shot'
    params: { field: 'name' | 'instance' | 'seq' | 'shot'; class_token?: string; name?: string; task?: string; instance?: string; seq?: string; shot?: string }
    label: string
    info: { rel_path: string; exists: boolean; file_count: number } | null
    busy: boolean
  } | null>(null)

  const requestTokenArchive = useCallback((
    field: 'name' | 'instance' | 'seq' | 'shot',
    params: { field: 'name' | 'instance' | 'seq' | 'shot'; class_token?: string; name?: string; task?: string; instance?: string; seq?: string; shot?: string },
    label: string,
  ) => {
    setTokenArchive({ field, params, label, info: null, busy: false })
    api.getTokenFolder(project, params)
      .then(info => setTokenArchive(p => (p ? { ...p, info } : p)))
      .catch(() => setTokenArchive(p => (p ? { ...p, info: { rel_path: '', exists: false, file_count: 0 } } : p)))
  }, [project])

  const confirmTokenArchive = useCallback(async () => {
    setTokenArchive(p => (p ? { ...p, busy: true } : p))
    let ok = true
    try {
      await api.archiveToken(project, tokenArchive!.params)
    } catch (e) {
      ok = false
      toast.error(e instanceof Error ? e.message : String(e))
    }
    if (!ok) { setTokenArchive(p => (p ? { ...p, busy: false } : p)); return }
    toast.success('Token archivé')
    setTokenArchive(null)
    reloadTokens()
    window.dispatchEvent(new Event('flux:refresh'))
  }, [project, tokenArchive, reloadTokens])

  // "Publish here" from Production — prefill project + mode + composer once.
  useEffect(() => {
    const prefill = (location.state as {
      prefill?: { project?: string; mode?: PublishMode; sel?: Record<string, string> }
    } | null)?.prefill
    if (!prefill) return
    if (prefill.project && prefill.project !== project) setProject(prefill.project)
    if (prefill.mode) setMode(prefill.mode)
    if (prefill.sel) setSel({ ...EMPTY_SEL, ...prefill.sel })
  }, [location.key]) // eslint-disable-line react-hooks/exhaustive-deps

  // Sequences (shot mode)
  useEffect(() => {
    if (!project || mode !== 'shot') { setSeqs([]); return }
    api.getSequences(project).then(d => setSeqs(d.sequences)).catch(() => setSeqs([]))
  }, [project, mode])

  // Shots for selected SEQ
  useEffect(() => {
    if (!project || mode !== 'shot' || !sel.seq) { setShots([]); return }
    api.getShots(project, sel.seq)
      .then(d => setShots(d.shots.map(s => s.split('/')[1] ?? s)))
      .catch(() => setShots([]))
  }, [project, mode, sel.seq])

  // ZBrush connection — single effect handles both navigation state and manual DCC switch.
  // Merged to avoid race condition where the dcc-change cleanup (→ false) overwrites
  // the navigation-state set (→ true) that fired in the same render cycle.
  useEffect(() => {
    // Sidebar navigated here after detecting the freeze — mark connected immediately, no ping.
    if (location.state?.zbrushConnected) {
      setDcc('ZBrush')
      setZbrushConnected(true)
      return
    }
    // Manual DCC switch — one-shot ping, no polling interval.
    if (dcc !== 'ZBrush') { setZbrushConnected(false); setZbrushVersion(null); return }
    let cancelled = false
    api.pingDcc('zbrush')
      .then(p => { if (!cancelled) { setZbrushConnected(p.connected); setZbrushVersion(p.version ?? null) } })
      .catch(() => { if (!cancelled) setZbrushConnected(false) })
    return () => { cancelled = true }
  }, [dcc, location.key]) // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch the Maya connect command once on mount (backend path is stable)
  useEffect(() => {
    api.getMayaConnectCmd().then(r => setMayaConnectCmd(r.cmd)).catch(() => {})
  }, [])

  // Re-check autostart status whenever Maya panel is active — catches Sidebar install/uninstall
  useEffect(() => {
    if (dcc !== 'Maya') return
    api.getDccAutostart('maya')
      .then(r => { setMayaAutostartInstalled(r.installed); setMayaStartupFile(r.startup_file ?? null) })
      .catch(() => { setMayaAutostartInstalled(false) })
  }, [dcc])

  // Maya connection — poll every 3 s when Maya DCC is active (commandPort can open any time)
  useEffect(() => {
    if (dcc !== 'Maya') { setMayaConnected(false); return }
    let cancelled = false
    const poll = async () => {
      try {
        const p = await api.pingDcc('maya')
        if (!cancelled) setMayaConnected(p.connected)
      } catch {
        if (!cancelled) setMayaConnected(false)
      }
    }
    void poll()
    const id = setInterval(() => void poll(), 3000)
    return () => { cancelled = true; clearInterval(id) }
  }, [dcc])

  // Reset exportExt when switching DCC if current format isn't in the new list
  useEffect(() => {
    const formats = formatsForDcc(dcc)
    if (!formats.includes(exportExt)) setExportExt(formats[0])
  }, [dcc]) // eslint-disable-line react-hooks/exhaustive-deps

  // Reset export options to the active format's defaults whenever it changes.
  useEffect(() => {
    setMayaExportOpts(defaultOptions(schemaForExt(exportExt)))
    setHouExportOpts(defaultOptions(houdiniSchemaForExt(exportExt)))
    setZbrushExportOpts(defaultZbrushOptions(exportExt))
  }, [exportExt])

  // Houdini polling — connection + selected node + auto-format
  useEffect(() => {
    if (dcc !== 'Houdini') return
    let cancelled = false
    const poll = async () => {
      try {
        const ping = await api.pingDcc('houdini')
        if (cancelled) return
        setHoudiniConnected(ping.connected)
        setHoudiniVersion(ping.version)
        if (!ping.connected) {
          // Drop stale node context so a later publish doesn't target a dead node.
          setRopNodePath('')
          setDetectedNodeType(null)
          autoExtForNodeRef.current = null
        }
        if (ping.connected) {
          const state = await api.getHoudiniState()
          if (cancelled) return
          if (state.selected_nodes?.length > 0) {
            const nodePath = state.selected_nodes[0]
            setRopNodePath(nodePath)

            // Primary: type from state (updated server)
            let rawType: string | undefined = (state.selected_node_types ?? {})[nodePath]

            // Fallback: infer from node name in path — works with any server version.
            // e.g. "/out/rop_alembic1" → name "rop_alembic1" → matches key "rop_alembic"
            if (!rawType) {
              const nodeName = nodePath.split('/').pop()?.toLowerCase() ?? ''
              const sortedKeys = Object.keys(NODE_TYPE_TO_EXT).sort((a, b) => b.length - a.length)
              rawType = sortedKeys.find(key => nodeName.includes(key))
            }

            setDetectedNodeType(rawType ?? null)
            // Suggest the node's default format only when the selection changes,
            // so a manual override (e.g. rop_geometry → .obj) survives later polls.
            if (nodePath !== autoExtForNodeRef.current) {
              autoExtForNodeRef.current = nodePath
              const ext = rawType ? resolveNodeExt(rawType) : undefined
              if (ext) setExportExt(ext)
            }
          } else {
            setDetectedNodeType(null)
            autoExtForNodeRef.current = null
          }
        }
      } catch { /* Houdini offline */ }
    }
    void poll()
    const id = setInterval(() => void poll(), 3000)
    return () => { cancelled = true; clearInterval(id) }
  }, [dcc])

  // ── Composer callbacks ──────────────────────────────────────────────────────

  const handleModeSwitch = useCallback(() => {
    setMode(prev => prev === 'asset' ? 'shot' : 'asset')
    setSel(EMPTY_SEL)
  }, [])

  const handleSelect = useCallback((key: string, value: string) => {
    setSel(prev => {
      const next = { ...prev, [key]: value }
      if (key === 'category') next.name = ''   // asset names depend on the category
      if (key === 'seq')      next.shot = ''
      return next
    })
  }, [])

  // ── Filename assembly ───────────────────────────────────────────────────────
  // Asset: CLASS_TASK_NAME_INSTANCE[_VARIANTE] · Shot: NAME_SEQ_SHOT_VARIANTE

  const buildFilename = useCallback((): string => {
    if (mode === 'asset') {
      const cls  = CATEGORY_TO_CLASS[sel.category] ?? formatToken(sel.category)
      const inst = formatToken(sel.instance) || 'null'
      const varr = formatToken(sel.variante)
      let base = `${cls}_${sel.task}_${formatToken(sel.name)}_${inst}`
      if (varr) base += `_${varr}`
      return base
    }
    const varr = formatToken(sel.variante) || 'null'
    return `${formatToken(sel.name)}_${formatSeqLabel(sel.seq)}_${formatShotLabel(sel.shot)}_${varr}`
  }, [mode, sel])

  // ── Token / folder pre-creation before publish ─────────────────────────────

  const createNewTokens = useCallback(async () => {
    if (mode === 'shot') {
      const seqLabel = formatSeqLabel(sel.seq)
      const seqNum   = parseInt(seqLabel.replace(/[^0-9]/g, ''), 10)
      if (!isNaN(seqNum) && !seqs.includes(seqLabel)) {
        try { await api.createSequence(project, seqNum); const d = await api.getSequences(project); setSeqs(d.sequences) } catch { /* may exist */ }
      }
      const shotLabel = formatShotLabel(sel.shot)
      const shotNum   = parseInt(shotLabel.replace(/[^0-9]/g, ''), 10)
      if (!isNaN(seqNum) && !isNaN(shotNum) && !shots.includes(shotLabel)) {
        try { await api.createShot(project, seqNum, shotNum); const d = await api.getShots(project, seqLabel); setShots(d.shots.map(s => s.split('/')[1] ?? s)) } catch { /* may exist */ }
      }
      return
    }
    // asset mode — create the asset folder if the name is new for this category
    const cls  = CATEGORY_TO_CLASS[sel.category] ?? ''
    const name = formatToken(sel.name)
    if (name && cls) {
      try { await api.createAsset(project, cls, name) } catch { /* may already exist */ }
    }
  }, [mode, project, sel, seqs, shots])

  // ── Publish ─────────────────────────────────────────────────────────────────

  const handleCancelZBrush = useCallback(() => {
    setZbrushConnected(false)
    setZbrushVersion(null)
    api.cancelZBrush().catch(() => {}) // fire-and-forget — ZBrush may not be in freeze
  }, [])

  const reset = useCallback(() => {
    setSel(EMPTY_SEL)
    setSourcePath('')
    setDescription('')
  }, [])

  const handlePublish = useCallback(async () => {
    if (!project) { toast.error('Sélectionne un projet'); return }

    const filename = buildFilename()
    const parts = filename.split('_').filter(Boolean)
    if (parts.length < 4) {
      toast.error(mode === 'asset' ? 'Complète Catégorie, Name et Task' : 'Complète Sequence, Shot et Name')
      return
    }

    setPublishing(true)

    try {
      await createNewTokens()

      if (dcc === 'Maya') {
        if (!mayaConnected) {
          toast.error('Maya non connecté : ouvre Maya avec le bridge FLUX actif (commandPort 7001)')
          return
        }
        if (lightUsd && mode === 'asset' && ['.usd', '.usda', '.usdc'].includes(exportExt)) {
          const assetName = formatToken(sel.name) || parts[2]
          const res = await api.exportMayaLightUsd({
            project_name: project,
            asset:        assetName,
            filename,
            fmt:          exportExt.replace('.', ''),
            scope:        mayaScope,
            frame_start:  isSequence ? frameStart : undefined,
            frame_end:    isSequence ? frameEnd : undefined,
            include_geo:     lightInclude.geo,
            include_skel:    lightInclude.skel,
            include_anim:    lightInclude.anim,
            include_weights: lightInclude.weights,
            include_uv:      lightInclude.uv,
            port:            readActiveInstancePort('Maya') ?? undefined,
          })
          toast.success(`USD léger ${res.version} → ${res.asset}`)
          return
        }
        const isAnimAbc = isSequence && exportExt === '.abc'
        const res = await api.publishMaya({
          project_name: project,
          filename,
          extension:    exportExt,
          scope:        mayaScope,
          is_sequence:  isAnimAbc,
          frame_range:  isAnimAbc ? [frameStart, frameEnd] : undefined,
          export_options: mayaExportOpts,
          description:  description || undefined,
          user:         settings?.username ?? undefined,
          port:         readActiveInstancePort('Maya') ?? undefined,
        })
        toast.success(`${versionLabel(res.version_str)} → Maya`)
      } else if (dcc === 'Houdini') {
        if (!houdiniConnected) {
          toast.error('Houdini non connecté : lance le serveur FLUX dans Houdini')
          return
        }
        if (lightUsd && mode === 'asset' && ['.usd', '.usda', '.usdc'].includes(exportExt)) {
          const assetName = formatToken(sel.name) || parts[2]
          const res = await api.exportHoudiniLightUsd({
            project_name: project,
            asset:        assetName,
            filename,
            fmt:          exportExt.replace('.', ''),
            frame_start:  isSequence ? frameStart : undefined,
            frame_end:    isSequence ? frameEnd : undefined,
            include_geo:     lightInclude.geo,
            include_skel:    lightInclude.skel,
            include_anim:    lightInclude.anim,
            include_weights: lightInclude.weights,
            include_uv:      lightInclude.uv,
          })
          toast.success(`USD Layers ${res.version} → ${res.asset}`)
          return
        }
        const res = await api.publishHoudiniRop({
          project_name:  project,
          filename,
          extension:     exportExt,
          rop_node_path: ropNodePath || undefined,
          is_sequence:   isSequence,
          frame_range:   isSequence ? [frameStart, frameEnd, frameStep] : undefined,
          export_options: houExportOpts,
          attr_filter:   (houAttrMode !== 'none' && houAttrNames.some(n => n.trim()))
            ? { mode: houAttrMode, names: houAttrNames.map(n => n.trim()).filter(Boolean) }
            : undefined,
          description:   description || undefined,
          user:          settings?.username ?? undefined,
        })
        toast.success(`${versionLabel(res.version_str)} → ${res.rop_node}`)
      } else if (dcc === 'ZBrush') {
        if (!zbrushConnected) {
          toast.error('ZBrush non connecté : active le bridge FLUX dans ZBrush')
          return
        }
        const res = await api.publishZBrush({
          project_name:   project,
          filename,
          extension:      exportExt,
          export_options: zbrushExportOpts,
          description:    description || undefined,
          user:           settings?.username ?? undefined,
        })
        toast.success(`${versionLabel(res.version_str)} → ZBrush`)
        setZbrushConnected(false)
        setZbrushVersion(null)
        window.electronAPI?.windowMinimize()
      } else if (dcc === 'Fichier local') {
        const files = localFiles.length ? localFiles : (sourcePath.trim() ? [sourcePath] : [])
        if (!files.length) {
          toast.error('Indique le(s) fichier(s) source')
          return
        }
        const multi = files.length > 1
        const cls   = CATEGORY_TO_CLASS[sel.category] ?? formatToken(sel.category)
        // Each source keeps any name; the destination name is composed from the
        // token composer. For a multi-file set, each file gets a DISTINCT instance
        // so they never collapse onto one version: autogroup → the map token from
        // the filename (Mesh_BCol → BCOL); bypass → the file's own stem.
        const targetFor = (f: string): string => {
          if (!multi) return (nameOverride && nameOverride.trim()) || buildFilename()
          const distinct = (mode === 'asset' && autoGroup) ? parseMapToken(f) : formatToken(fileStem(f))
          if (mode === 'asset') {
            const varr = formatToken(sel.variante)
            return `${cls}_${sel.task}_${formatToken(sel.name)}_${distinct}` + (varr ? `_${varr}` : '')
          }
          return `${formatToken(sel.name)}_${formatSeqLabel(sel.seq)}_${formatShotLabel(sel.shot)}_${distinct}`
        }
        let okCount = 0
        const failed: string[] = []
        for (const f of files) {
          try {
            const res = await api.publish({
              source_path:  f,
              project_name: project,
              description:  description || undefined,
              user:         settings?.username ?? undefined,
              target_name:  targetFor(f),
            })
            if (res.success) okCount++
            else failed.push(fileStem(f))
          } catch {
            failed.push(fileStem(f))
          }
        }
        if (okCount) {
          toast.success(
            multi
              ? `${okCount} fichier${okCount > 1 ? 's' : ''} publié${okCount > 1 ? 's' : ''}${failed.length ? ` · ${failed.length} échec(s)` : ''}`
              : 'Publié',
          )
        }
        if (failed.length && !okCount) toast.error(`Échec : ${failed.join(', ')}`)
      } else {
        toast.error(`Publication depuis ${dcc} non encore disponible`)
        return
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Erreur inconnue')
    } finally {
      setPublishing(false)
    }
  }, [
    project, mode, buildFilename, createNewTokens, dcc,
    exportExt, ropNodePath, isSequence, frameStart, frameEnd, frameStep,
    description, settings?.username, sourcePath, localFiles, autoGroup, nameOverride,
    zbrushConnected, zbrushExportOpts,
    mayaConnected, mayaScope, mayaExportOpts, lightUsd, lightInclude, sel, houdiniConnected, houExportOpts, houAttrMode, houAttrNames,
  ])

  // Ctrl/Cmd+P → publish (also prevents the browser print dialog)
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'p') {
        e.preventDefault()
        if (!publishing) void handlePublish()
      }
    }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [handlePublish, publishing])

  const filename = buildFilename()

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>

      {/* Header */}
      <div style={{ padding: '12px 20px', borderBottom: '1px solid var(--rule)', display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.1em', color: 'var(--ink)' }}>Publish</div>
        <div style={{ flex: 1 }} />
        <Btn kbd sm>Ctrl+P</Btn>
      </div>

      <SoftwareSelector active={dcc} onChange={setDcc} />

      <div ref={splitContainerRef} style={{ flex: 1, display: 'flex', minHeight: 0 }}>

        {/* ── Left: Composer + source + description ── */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, overflow: 'hidden' }}>

          <div style={{ flex: 1, padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 14, overflowY: 'auto', minHeight: 0 }}>

            {/* Project selector */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div className="cap">PROJET</div>
              <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                <span style={{ position: 'absolute', left: 8, pointerEvents: 'none', display: 'flex', zIndex: 1 }}>
                  <FolderIcon color="var(--accent)" />
                </span>
                <Select value={project} onValueChange={setProject}>
                  <SelectTrigger style={{ width: 200, paddingLeft: 26 }} />
                  <SelectContent>
                    {projects.length === 0
                      ? <SelectItem value="__none__">Aucun projet</SelectItem>
                      : projects.map(p => <SelectItem key={p} value={p}>{p}</SelectItem>)
                    }
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Publish Composer */}
            <PublishComposer
              project={project}
              tokens={tokens}
              seqs={seqs}
              shots={shots}
              mode={mode}
              sel={sel}
              onModeSwitch={handleModeSwitch}
              onSelect={handleSelect}
              onArchiveToken={(field, value) => {
                const cls = CATEGORY_TO_CLASS[sel.category] ?? formatToken(sel.category)
                if (field === 'name') {
                  requestTokenArchive('name', { field: 'name', class_token: cls, name: value }, `NAME · ${value}`)
                } else if (field === 'instance') {
                  requestTokenArchive('instance', { field: 'instance', class_token: cls, name: sel.name, task: sel.task, instance: value }, `INSTANCE · ${value}`)
                } else if (field === 'seq') {
                  requestTokenArchive('seq', { field: 'seq', seq: value }, `SEQ · ${value}`)
                } else {
                  requestTokenArchive('shot', { field: 'shot', seq: sel.seq, shot: value }, `SHOT · ${sel.seq}/${value}`)
                }
              }}
            />

            {tokenArchive && (
              <div
                onClick={e => { if (e.target === e.currentTarget && !tokenArchive.busy) setTokenArchive(null) }}
                style={{
                  position: 'fixed', inset: 0, zIndex: 3000, background: 'rgba(0,0,0,0.55)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
                }}
              >
                <div style={{
                  width: 360, maxWidth: '92vw', background: 'var(--paper)',
                  border: '1px solid var(--rule-2)', borderRadius: 12, boxShadow: 'var(--shadow)', padding: '18px 18px 14px',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>
                    <Trash2 size={15} strokeWidth={1.9} color="var(--err)" />
                    Archiver {tokenArchive.label} ?
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--ink-3)', marginBottom: 16, lineHeight: 1.5 }}>
                    {tokenArchive.info === null
                      ? 'Analyse du dossier…'
                      : tokenArchive.info.exists && tokenArchive.info.file_count > 0
                        ? `Ce dossier contient ${tokenArchive.info.file_count} fichier${tokenArchive.info.file_count > 1 ? 's' : ''}. Il sera déplacé vers ARCHIVE/ (récupérable), pas supprimé.`
                        : tokenArchive.info.exists
                          ? 'Le dossier (vide) sera déplacé vers ARCHIVE/.'
                          : "Aucun dossier sur disque : seul le token sera retiré."}
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                    <Btn onClick={() => setTokenArchive(null)} disabled={tokenArchive.busy}>Annuler</Btn>
                    <Btn onClick={confirmTokenArchive} disabled={tokenArchive.busy || tokenArchive.info === null}>
                      {tokenArchive.busy ? 'Archivage…' : 'Archiver'}
                    </Btn>
                  </div>
                </div>
              </div>
            )}

            {/* Source / DCC info */}
            {dcc === 'ZBrush' ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {/* Connection status */}
                <div>
                  <div className="cap" style={{ marginBottom: 6 }}>CONNEXION ZBRUSH</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <div style={{
                      width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
                      background: zbrushConnected ? 'var(--ok)' : 'var(--err)',
                    }} />
                    <div style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--ink-3)' }}>
                      {zbrushConnected
                        ? `Connecté${zbrushVersion ? ` · ${zbrushVersion}` : ''}`
                        : 'Non connecté : installe le plugin via le bouton Plug dans la sidebar'}
                    </div>
                  </div>
                </div>

              </div>
            ) : dcc === 'Maya' ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>

                {/* Maya connection — coherent card, UI sans font (matches Launcher naming) */}
                {mayaConnected ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '9px 12px', borderRadius: 8, background: 'var(--paper-2)', border: '1px solid var(--rule-2)' }}>
                    <div style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--ok)', flexShrink: 0, boxShadow: '0 0 6px var(--ok)' }} />
                    <span style={{ fontFamily: 'var(--sans)', fontSize: 12, fontWeight: 500, color: 'var(--ink)' }}>Maya connecté</span>
                    <span style={{ fontFamily: 'var(--sans)', fontSize: 11, color: 'var(--ink-4)' }}>· commandPort 7001</span>
                  </div>
                ) : mayaAutostartInstalled !== null && (
                  <div style={{ borderRadius: 10, border: '1px solid var(--accent)', background: 'var(--accent-soft)', overflow: 'hidden' }}>
                    {/* Header */}
                    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, padding: '12px 14px', borderBottom: '1px solid var(--rule-2)' }}>
                      <div style={{ width: 9, height: 9, borderRadius: '50%', background: 'var(--err)', flexShrink: 0, marginTop: 4 }} />
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
                        <span style={{ fontFamily: 'var(--sans)', fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>Maya n'est pas connecté</span>
                        <span style={{ fontFamily: 'var(--sans)', fontSize: 11, color: 'var(--ink-3)', lineHeight: 1.45 }}>
                          Le pont FLUX (commandPort 7001) est injoignable. Suis les étapes pour l'activer.
                        </span>
                      </div>
                    </div>
                    {/* Steps */}
                    <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 12, background: 'var(--paper)' }}>
                      <MayaStep
                        n={1}
                        done={!!mayaAutostartInstalled}
                        title={mayaAutostartInstalled ? 'Autostart installé' : "Installer l'autostart Maya"}
                        desc={mayaAutostartInstalled ? (mayaStartupFile ?? 'userSetup.py mis à jour') : 'Sidebar → bouton ⬡ à côté de Maya'}
                      />
                      {mayaAutostartInstalled && (
                        <MayaStep n={2} done={false} title="Redémarre Maya" desc="Le commandPort s'ouvre automatiquement au lancement." />
                      )}
                      {mayaConnectCmd && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                          <span style={{ fontFamily: 'var(--sans)', fontSize: 11, color: 'var(--ink-3)' }}>
                            Ou ouvre le port immédiatement — colle ceci dans le Script Editor (Python) de Maya :
                          </span>
                          <CopyBlock text={mayaConnectCmd} />
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            ) : dcc === 'Houdini' ? (
              <div>
                <div className="cap" style={{ marginBottom: 6 }}>NODE ROP</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 7 }}>
                  <div style={{
                    width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
                    background: houdiniConnected ? 'var(--ok)' : 'var(--err)',
                  }} />
                  <div style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--ink-3)' }}>
                    {houdiniConnected
                      ? `Connecté${houdiniVersion ? ` · Houdini ${houdiniVersion}` : ''}`
                      : 'Houdini non connecté : lance le serveur FLUX dans Houdini'}
                  </div>
                </div>
                <input
                  value={ropNodePath}
                  onChange={e => setRopNodePath(e.target.value)}
                  placeholder="/out/rop_alembic1  (auto-rempli depuis la sélection)"
                  style={{
                    width: '100%', height: 28,
                    background: 'var(--bg-deep)', border: '1px solid var(--rule-2)',
                    borderRadius: 5, padding: '0 8px',
                    fontFamily: 'var(--sans)', fontSize: 10, color: 'var(--ink-2)',
                    boxShadow: 'var(--shadow-inset)', outline: 'none',
                  }}
                />
                {detectedNodeType && (
                  <div style={{ marginTop: 4, fontSize: 9, fontFamily: 'var(--mono)', color: resolveNodeExt(detectedNodeType) ? 'var(--ok)' : 'var(--ink-4)' }}>
                    {resolveNodeExt(detectedNodeType)
                      ? `→ ${resolveNodeExt(detectedNodeType)} (${detectedNodeType})`
                      : `type non reconnu : ${detectedNodeType}`}
                  </div>
                )}
              </div>
            ) : dcc === 'Fichier local' ? (
              <div>
                <div className="cap" style={{ marginBottom: 6 }}>FICHIER SOURCE</div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <input
                    value={sourcePath}
                    onChange={e => setSourcePath(e.target.value)}
                    placeholder="Chemin absolu vers le fichier à publier…  (tout type)"
                    style={{
                      flex: 1, minWidth: 0, height: 28,
                      background: 'var(--bg-deep)', border: '1px solid var(--rule-2)',
                      borderRadius: 5, padding: '0 8px',
                      fontFamily: 'var(--sans)', fontSize: 10, color: 'var(--ink-2)',
                      boxShadow: 'var(--shadow-inset)', outline: 'none',
                    }}
                  />
                  <div
                    onClick={async () => {
                      // Native Windows multi-picker — any file type. Selecting several
                      // files (a texture set, a folder's worth of maps) publishes them
                      // in one go; each gets its own destination via autogroup.
                      const picked = await window.electronAPI?.openFiles?.([
                        { name: 'Tous les fichiers', extensions: ['*'] },
                      ])
                      if (picked && picked.length) {
                        setLocalFiles(picked)
                        setSourcePath(picked[0])
                      }
                    }}
                    className="scale-hover"
                    title="Parcourir… (sélection multiple possible)"
                    style={{
                      display: 'flex', alignItems: 'center', gap: 5, flexShrink: 0,
                      height: 28, padding: '0 10px', borderRadius: 5,
                      border: '1px solid var(--rule-2)', background: 'var(--paper-2)',
                      color: 'var(--ink-3)', cursor: 'pointer', fontSize: 10,
                      boxShadow: 'var(--shadow-xs)',
                    }}
                  >
                    <FolderOpen size={12} strokeWidth={1.75} />
                    Parcourir
                  </div>
                  <div
                    onClick={async () => {
                      // Import a whole texture folder (recursive), filtered to image
                      // types so junk (thumbs, logs…) is skipped.
                      const picked = await window.electronAPI?.openFolderFiles?.(TEXTURE_EXTS)
                      if (picked && picked.length) {
                        setLocalFiles(picked)
                        setSourcePath(picked[0])
                      } else if (picked) {
                        toast.error('Aucune image trouvée dans ce dossier')
                      }
                    }}
                    className="scale-hover"
                    title="Importer un dossier de textures (récursif)"
                    style={{
                      display: 'flex', alignItems: 'center', gap: 5, flexShrink: 0,
                      height: 28, padding: '0 10px', borderRadius: 5,
                      border: '1px solid var(--rule-2)', background: 'var(--paper-2)',
                      color: 'var(--ink-3)', cursor: 'pointer', fontSize: 10,
                      boxShadow: 'var(--shadow-xs)',
                    }}
                  >
                    <FolderOpen size={12} strokeWidth={1.75} />
                    Dossier
                  </div>
                </div>

                {/* Multi-file set: list + autogroup toggle. Each file publishes into
                    its own map folder (INSTANCE from the filename) unless bypassed. */}
                {localFiles.length > 1 && (
                  <div style={{ marginTop: 8, border: '1px solid var(--rule-2)', borderRadius: 6, background: 'var(--paper-2)', padding: '8px 10px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                      <span className="cap">{localFiles.length} FICHIERS</span>
                      <span style={{ flex: 1 }} />
                      <label style={{ display: 'inline-flex', alignItems: 'center', gap: 5, cursor: 'pointer', fontSize: 10, color: 'var(--ink-2)' }}>
                        <input type="checkbox" checked={autoGroup} onChange={e => setAutoGroup(e.target.checked)} style={{ accentColor: 'var(--accent)' }} />
                        Autogroup par map
                      </label>
                      <span
                        onClick={() => { setLocalFiles([]); setSourcePath('') }}
                        style={{ color: 'var(--accent-hi)', cursor: 'pointer', fontSize: 10 }}
                      >Vider</span>
                    </div>
                    <div style={{ maxHeight: 120, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 2 }}>
                      {localFiles.map(f => {
                        const inst = (mode === 'asset' && autoGroup) ? parseMapToken(f) : formatToken(fileStem(f))
                        return (
                          <div key={f} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 9, fontFamily: 'var(--mono)', color: 'var(--ink-3)' }}>
                            <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{fileStem(f)}</span>
                            <span style={{ color: 'var(--accent-hi)', flexShrink: 0 }}>→ {inst}</span>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}

                {/* Published name — single file only; multi-file names are auto per file.
                    Must stay token-parseable (it drives the destination folder). */}
                {localFiles.length <= 1 && (<>
                <div className="cap" style={{ margin: '10px 0 6px' }}>NOM PUBLIÉ</div>
                <input
                  value={nameOverride ?? filename}
                  onChange={e => setNameOverride(e.target.value)}
                  spellCheck={false}
                  placeholder={filename}
                  style={{
                    width: '100%', height: 28,
                    background: 'var(--bg-deep)', border: '1px solid var(--rule-2)',
                    borderRadius: 5, padding: '0 8px',
                    fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-2)',
                    boxShadow: 'var(--shadow-inset)', outline: 'none',
                  }}
                />
                <div style={{ fontSize: 9, color: 'var(--ink-4)', marginTop: 4, fontFamily: 'var(--mono)' }}>
                  Extension conservée depuis le fichier source. {nameOverride !== null && (
                    <span onClick={() => setNameOverride(null)} style={{ color: 'var(--accent-hi)', cursor: 'pointer' }}>
                      Réinitialiser
                    </span>
                  )}
                </div>
                </>)}
              </div>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', borderRadius: 6, background: 'var(--paper-2)', border: '1px solid var(--rule-2)' }}>
                <div style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--ink-4)', flexShrink: 0 }} />
                <div style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--ink-4)' }}>
                  La publication depuis <span style={{ color: 'var(--ink-2)' }}>{dcc}</span> se déclenche directement depuis le logiciel
                </div>
              </div>
            )}

            {/* Published by */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ fontSize: 9, fontFamily: 'var(--mono)', color: 'var(--ink-4)', letterSpacing: '0.06em' }}>PUBLIÉ PAR</div>
              <div style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--ink-3)' }}>
                {settings?.username ?? '-'}
              </div>
            </div>
          </div>

          {/* Description + result */}
          <div style={{ padding: '0 20px 16px', flexShrink: 0 }}>
            <SecTitle>Description</SecTitle>
            <textarea
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Décris la modification effectuée…"
              style={{
                width: '100%', height: 90, resize: 'none',
                background: 'var(--paper-2)', border: '1px solid var(--rule-2)',
                borderRadius: 6, padding: '10px 12px',
                fontFamily: 'var(--sans)', fontSize: 11, color: 'var(--ink-2)',
                outline: 'none', boxShadow: 'var(--shadow-inset)',
              }}
            />
          </div>
        </div>

        {/* draggable splitter — resizes the right panel */}
        <div
          onMouseDown={startSplitDrag}
          title="Glisser pour redimensionner"
          style={{ width: 6, flexShrink: 0, cursor: 'col-resize', background: 'var(--rule)', transition: 'background 0.12s' }}
          onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'var(--accent)' }}
          onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'var(--rule)' }}
        />

        {/* ── Right: Format + Séquence + Aperçu (shared for all DCCs) ── */}
        <div style={{ width: rightWidth, flexShrink: 0, display: 'flex', flexDirection: 'column', minWidth: 0, overflowY: 'auto', paddingBottom: 24 }}>

          {/* PRESETS — quick USD Layers setups (Maya & Houdini). Set format + layers. */}
          {(dcc === 'Maya' || dcc === 'Houdini') && mode === 'asset' && (
            <div style={{ padding: '16px 20px 0', flexShrink: 0 }}>
              <SecTitle>PRESETS</SecTitle>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {([
                  { label: 'Base light USD', ext: '.usd', layers: { geo: true, skel: true, anim: true, weights: true, uv: true } },
                  { label: 'Géo USD',        ext: '.usd', layers: { geo: true, skel: false, anim: false, weights: false, uv: true } },
                  { label: 'Skin USD',       ext: '.usd', layers: { geo: true, skel: true, anim: false, weights: true, uv: true } },
                ] as const).map(p => (
                  <Pill key={p.label} style={{ cursor: 'pointer' }}>
                    <span onClick={() => { setExportExt(p.ext); setLightUsd(true); setLightInclude({ ...p.layers }) }}>{p.label}</span>
                  </Pill>
                ))}
              </div>
            </div>
          )}

          {/* FORMAT — hidden for a local file: the format is the picked file's own
              extension (backend infers it from source_path), so we never ask. */}
          {dcc !== 'Fichier local' && (
          <div style={{ padding: '16px 20px 12px', flexShrink: 0 }}>
            <SecTitle>FORMAT</SecTitle>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {formatsForDcc(dcc).map(ext => (
                <div key={ext} onClick={() => setExportExt(ext)} className="scale-hover" style={{
                  padding: '5px 10px', borderRadius: 6, cursor: 'pointer', fontSize: 11,
                  fontFamily: 'var(--mono)', fontWeight: exportExt === ext ? 600 : 400,
                  border: exportExt === ext ? '1px solid var(--accent)' : '1px solid var(--rule-2)',
                  background: exportExt === ext ? 'var(--accent-soft)' : 'var(--paper-2)',
                  color: exportExt === ext ? 'var(--accent-hi)' : 'var(--ink-3)',
                  transition: 'all 0.1s',
                }}>{ext}</div>
              ))}
            </div>
          </div>
          )}

          {/* SÉQUENCE ANIMÉE — ZBrush: never; Maya: .abc only; Houdini: always */}
          <div style={{ padding: '0 20px 12px', flexShrink: 0, opacity: (dcc === 'ZBrush' || (dcc === 'Maya' && exportExt !== '.abc')) ? 0.35 : 1, pointerEvents: (dcc === 'ZBrush' || (dcc === 'Maya' && exportExt !== '.abc')) ? 'none' : undefined }}>
            <SecTitle>SÉQUENCE ANIMÉE</SecTitle>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: isSequence ? 10 : 0 }}>
              <div onClick={() => setIsSequence(v => !v)} style={{
                width: 32, height: 18, borderRadius: 9, cursor: 'pointer', flexShrink: 0,
                background: isSequence ? 'var(--accent)' : 'var(--rule-2)',
                position: 'relative', transition: 'background 0.15s',
              }}>
                <div style={{
                  position: 'absolute', top: 2, left: isSequence ? 16 : 2,
                  width: 14, height: 14, borderRadius: '50%', background: 'white',
                  transition: 'left 0.15s', boxShadow: '0 1px 3px rgba(0,0,0,.3)',
                }} />
              </div>
              <div style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--ink-3)' }}>
                {isSequence ? 'Activé · dossier versionné + $F4' : 'Désactivé · fichier unique LAST'}
              </div>
            </div>
            {isSequence && (
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                {([['Start', frameStart, setFrameStart], ['End', frameEnd, setFrameEnd], ['Step', frameStep, setFrameStep]] as const).map(([lbl, val, set]) => (
                  <div key={lbl} style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                    <div style={{ fontSize: 9, color: 'var(--ink-4)', fontFamily: 'var(--mono)', textTransform: 'uppercase' }}>{lbl}</div>
                    <input type="number" value={val} onChange={e => set(Number(e.target.value))} style={{
                      width: 56, height: 26, background: 'var(--bg-deep)', border: '1px solid var(--rule-2)',
                      borderRadius: 5, padding: '0 6px', fontFamily: 'var(--mono)', fontSize: 11,
                      color: 'var(--ink)', boxShadow: 'var(--shadow-inset)', outline: 'none',
                    }} />
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* SCOPE — Maya only */}
          {dcc === 'Maya' && (
            <div style={{ padding: '0 20px 12px', flexShrink: 0 }}>
              <SecTitle>SCOPE</SecTitle>
              <div style={{ display: 'flex', gap: 4 }}>
                {(['scene', 'selection'] as const).map(s => (
                  <div
                    key={s}
                    onClick={() => setMayaScope(s)}
                    style={{
                      padding: '5px 10px', borderRadius: 6, cursor: 'pointer',
                      fontFamily: 'var(--mono)', fontSize: 11, fontWeight: mayaScope === s ? 600 : 400,
                      border: mayaScope === s ? '1px solid var(--accent)' : '1px solid var(--rule-2)',
                      background: mayaScope === s ? 'var(--accent-soft)' : 'var(--paper-2)',
                      color: mayaScope === s ? 'var(--accent-hi)' : 'var(--ink-3)',
                      transition: 'all 0.1s',
                    }}
                  >{s}</div>
                ))}
              </div>
            </div>
          )}

          {/* OPTIONS D'EXPORT — Maya, per-format (coexists with USD Layers). */}
          {dcc === 'Maya' && schemaForExt(exportExt).length > 0 && (
            <div style={{ padding: '0 20px 12px', flexShrink: 0 }}>
              <SecTitle>OPTIONS D'EXPORT <span style={{ fontFamily: 'var(--mono)', textTransform: 'none', color: 'var(--ink-4)' }}>{exportExt}</span></SecTitle>
              <ExportOptions
                schema={schemaForExt(exportExt)}
                values={mayaExportOpts}
                onChange={(k, v) => setMayaExportOpts(prev => ({ ...prev, [k]: v }))}
              />
            </div>
          )}

          {/* OPTIONS D'EXPORT — Houdini, per-format (ROP parameters). */}
          {dcc === 'Houdini' && houdiniSchemaForExt(exportExt).length > 0 && (
            <div style={{ padding: '0 20px 12px', flexShrink: 0 }}>
              <SecTitle>OPTIONS D'EXPORT <span style={{ fontFamily: 'var(--mono)', textTransform: 'none', color: 'var(--ink-4)' }}>{exportExt}</span></SecTitle>
              <ExportOptions
                schema={houdiniSchemaForExt(exportExt)}
                values={houExportOpts}
                onChange={(k, v) => setHouExportOpts(prev => ({ ...prev, [k]: v }))}
              />
            </div>
          )}

          {/* OPTIONS D'EXPORT — ZBrush, per-format (Tool:Export sliders / FBX plugin). */}
          {dcc === 'ZBrush' && zbrushSchemaForExt(exportExt).length > 0 && (
            <div style={{ padding: '0 20px 12px', flexShrink: 0 }}>
              <SecTitle>OPTIONS D'EXPORT <span style={{ fontFamily: 'var(--mono)', textTransform: 'none', color: 'var(--ink-4)' }}>{exportExt}</span></SecTitle>
              <ExportOptions
                schema={zbrushSchemaForExt(exportExt)}
                values={zbrushExportOpts}
                onChange={(k, v) => setZbrushExportOpts(prev => ({ ...prev, [k]: v }))}
              />
            </div>
          )}

          {/* ATTRIBUTS — Houdini, filtre les attributs point à l'export (attribdelete) */}
          {dcc === 'Houdini' && exportExt !== '.fbx' && (
            <div style={{ padding: '0 20px 12px', flexShrink: 0 }}>
              <SecTitle>ATTRIBUTS</SecTitle>
              <div style={{ display: 'flex', gap: 4, marginBottom: houAttrMode === 'none' ? 0 : 10 }}>
                {([['none', 'Tous'], ['keep', 'Garder uniquement'], ['remove', 'Supprimer']] as const).map(([m, label]) => (
                  <div key={m} onClick={() => setHouAttrMode(m)} style={{
                    padding: '5px 10px', borderRadius: 6, cursor: 'pointer', fontSize: 11,
                    fontFamily: 'var(--mono)', fontWeight: houAttrMode === m ? 600 : 400,
                    border: houAttrMode === m ? '1px solid var(--accent)' : '1px solid var(--rule-2)',
                    background: houAttrMode === m ? 'var(--accent-soft)' : 'var(--paper-2)',
                    color: houAttrMode === m ? 'var(--accent-hi)' : 'var(--ink-3)',
                  }}>{label}</div>
                ))}
              </div>
              {houAttrMode !== 'none' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                    <span className="cap">Presets</span>
                    {['boneCapture', 'curveu'].map(p => (
                      <Pill key={p} style={{ cursor: 'pointer' }}>
                        <span onClick={() => setHouAttrNames(prev => prev.includes(p) ? prev : [...prev, p])}>{p}</span>
                      </Pill>
                    ))}
                    <Pill style={{ cursor: 'pointer' }}>
                      <span onClick={() => setHouAttrNames(prev => [...prev, 'mask'])}>+ mask</span>
                    </Pill>
                    <div style={{ flex: 1 }} />
                    <Btn sm onClick={() => setHouAttrNames(prev => [...prev, ''])}>+ attribut</Btn>
                  </div>
                  {houAttrNames.length === 0 && (
                    <div className="lbl" style={{ fontSize: 10, color: 'var(--ink-4)' }}>
                      {houAttrMode === 'keep' ? 'Aucun attribut listé (P toujours conservé)' : 'Aucun attribut à supprimer'}
                    </div>
                  )}
                  {houAttrNames.map((n, i) => (
                    <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      <AttrCombo
                        value={n}
                        onChange={v => setHouAttrNames(prev => prev.map((x, j) => j === i ? v : x))}
                      />
                      <div onClick={() => setHouAttrNames(prev => prev.filter((_, j) => j !== i))}
                        className="scale-hover-lg" style={{ cursor: 'pointer', color: 'var(--ink-4)', display: 'flex' }}>
                        <Trash2 size={13} strokeWidth={1.75} />
                      </div>
                    </div>
                  ))}
                  <div className="lbl" style={{ fontSize: 9, color: 'var(--ink-4)' }}>
                    Attributs point uniquement (curveu, masks, boneCapture…). Renommage : bientôt.
                  </div>
                </div>
              )}
            </div>
          )}

          {/* USD LAYERS — Maya & Houdini, asset + USD formats only (hidden otherwise).
              Layered UsdSkel export; the checkboxes choose which layers to author. */}
          {(dcc === 'Maya' || dcc === 'Houdini') && mode === 'asset' && ['.usd', '.usda', '.usdc'].includes(exportExt) && (() => {
            const usdOk = true
            const on = usdOk && lightUsd
            return (
              <div style={{ padding: '0 20px 12px', flexShrink: 0 }}>
                <SecTitle>USD LAYERS</SecTitle>
                <div
                  onClick={() => { if (usdOk) setLightUsd(v => !v) }}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 8,
                    cursor: usdOk ? 'pointer' : 'default', userSelect: 'none',
                    opacity: usdOk ? 1 : 0.45,
                  }}
                >
                  <div style={{
                    width: 28, height: 16, borderRadius: 8, flexShrink: 0,
                    background: on ? 'var(--accent)' : 'var(--rule-2)',
                    position: 'relative', transition: 'background 0.15s',
                  }}>
                    <div style={{
                      position: 'absolute', top: 2, left: on ? 14 : 2,
                      width: 12, height: 12, borderRadius: '50%', background: 'white',
                      transition: 'left 0.15s',
                    }} />
                  </div>
                  <span style={{ fontSize: 10, fontFamily: 'var(--mono)', color: on ? 'var(--accent-hi)' : 'var(--ink-3)' }}>
                    {usdOk
                      ? 'Export en layers USD (model / skel / anim…) — choisis ci-dessous'
                      : 'Disponible seulement en usd / usda / usdc'}
                  </span>
                </div>
                {on && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 16px', marginTop: 10 }}>
                    {([['geo', 'Geo'], ['skel', 'Squelette'], ['anim', 'Animation'], ['weights', 'Skin weights (boneCapture)'], ['uv', 'UV']] as const).map(([k, label]) => (
                      <div key={k} onClick={() => setLightInclude(p => ({ ...p, [k]: !p[k] }))}
                        style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', userSelect: 'none' }}>
                        <Check on={lightInclude[k]} />
                        <span style={{ fontSize: 11, color: 'var(--ink-2)' }}>{label}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )
          })()}

          {/* APERÇU OUTPUT */}
          <div style={{ padding: '0 20px 16px', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <SecTitle>APERÇU OUTPUT</SecTitle>
            <div className="subcard" style={{ padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 4, minHeight: 90, maxHeight: 200, overflowY: 'auto' }}>
              {isSequence ? (<>
                <div style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--ink-3)' }}>{filename}_v001/</div>
                <div style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--ink)', paddingLeft: 12 }}>
                  {filename}_v001.$F4{exportExt}
                </div>
              </>) : (
                <div style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--ink)' }}>
                  {filename}_LAST{exportExt}
                </div>
              )}
              {dcc === 'Houdini' && ropNodePath && (
                <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--rule)', fontSize: 9, fontFamily: 'var(--mono)', color: 'var(--ink-4)' }}>
                  ROP : {ropNodePath}
                </div>
              )}
              {dcc === 'ZBrush' && (
                <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--rule)', fontSize: 9, fontFamily: 'var(--mono)', color: zbrushConnected ? 'var(--ok)' : 'var(--err)' }}>
                  {zbrushConnected ? `● ZBrush connecté${zbrushVersion ? ` · ${zbrushVersion}` : ''}` : '✕ ZBrush non connecté'}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Bottom bar */}
      <div style={{ borderTop: '1px solid var(--rule)', padding: '9px 20px', display: 'flex', gap: 8, justifyContent: 'flex-end', flexShrink: 0 }}>
        <Btn ghost onClick={reset}>Réinitialiser</Btn>
        {dcc === 'ZBrush' && (
          <Btn ghost onClick={handleCancelZBrush}>Annuler</Btn>
        )}
        <Btn primary onClick={() => void handlePublish()}>
          {publishing ? 'Publication…' : 'Publish →'}
        </Btn>
      </div>
    </div>
  )
}
