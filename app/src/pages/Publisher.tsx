import { useState, useEffect, useCallback, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { Trash2, FolderOpen, X, RefreshCw, ChevronRight, ChevronDown } from 'lucide-react'
import { SoftwareSelector } from '../components/shared/SoftwareSelector'
import { Btn, SecTitle, FolderIcon, Pill, Select, SelectTrigger, SelectContent, SelectItem } from '../components/shared/ui'
import { ExportOptions } from '../components/shared/ExportOptions'
import { schemaForExt, defaultOptions } from '../lib/mayaExportOptions'
import { houdiniSchemaForExt } from '../lib/houdiniExportOptions'
import { USD_PRESET_SCHEMAS, defaultPresetOptions, presetForTask, exportedAttrs } from '../lib/usdPresetOptions'
import type { UsdPreset } from '../lib/usdPresetOptions'
import { zbrushSchemaForExt, defaultZbrushOptions } from '../lib/zbrushExportOptions'
import { nukeSchemaForExt, defaultNukeOptions } from '../lib/nukeExportOptions'
import { photoshopSchemaForExt, defaultPhotoshopOptions } from '../lib/photoshopExportOptions'
import { PAINTER_OPTIONS, defaultPainterOptions } from '../lib/painterExportOptions'
import { MARI_OPTIONS, defaultMariOptions } from '../lib/mariExportOptions'
import { DESIGNER_OPTIONS, defaultDesignerOptions } from '../lib/designerExportOptions'
import { MARVELOUS_OPTIONS, defaultMarvelousOptions } from '../lib/marvelousExportOptions'
import { api } from '../api/client'
import type { DesignerPackage, MayaUsdPreview, MayaUsdTreeNode, PainterChannel, PainterPreset, UsdTaskContribution } from '../api/client'
import { useProject } from '../ProjectContext'
import { TextureMapTable, mapParams as buildMapParams } from './publisher/TextureMapTable'
import type { MapOpts } from './publisher/TextureMapTable'
import { useSettings } from '../hooks/useSettings'
import { readActiveInstancePort, writeActiveInstancePort } from '../hooks/useActiveInstances'
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

// Keys must match the SoftwareSelector names exactly (Painter/Mari/Designer), or the
// DCC falls back to DEFAULT_EXPORT_FORMATS.
const EXPORT_FORMATS_BY_DCC: Record<string, string[]> = {
  Maya:      ['.abc', '.fbx', '.obj', '.ma', '.mb', ...USD_FORMATS],
  Houdini:   ['.abc', '.bgeo', '.vdb', '.obj', '.fbx', '.exr', '.hip', ...USD_FORMATS],
  Nuke:      ['.exr', '.dpx', '.tif', '.png', '.mov', '.nk'],
  Painter:   ['.png', '.exr', '.tga', '.tif', '.jpg'],
  Mari:      ['.tif', '.exr', '.png', '.tga', '.jpg'],
  ZBrush:    ['.ztl', '.obj', '.fbx'],
  // Designer: the format of the graph output maps (.sbsar / .sbs are options).
  Designer:  ['.png', '.exr', '.tif', '.tga', '.jpg'],
  Marvelous: ['.abc', '.obj', '.fbx', '.usd', '.glb', '.zprj'],
  Photoshop: ['.psd', '.psb', '.png', '.jpg', '.tif', '.tga'],
}

// Fallback (e.g. "Fichier local"): a broad, DCC-agnostic superset.
const DEFAULT_EXPORT_FORMATS = ['.abc', '.fbx', '.obj', '.exr', '.png', '.tif', ...USD_FORMATS]

function formatsForDcc(dcc: string): string[] {
  return EXPORT_FORMATS_BY_DCC[dcc] ?? DEFAULT_EXPORT_FORMATS
}

// Socket-bridge DCCs (Level 2) whose connection FLUX polls by HTTP ping. The value
// is the backend ping key (/dcc/<key>/ping). Maya/Houdini/ZBrush keep their own
// bespoke polling; these share one generic effect (bridgeStatus below).
const DCC_PING_KEY: Record<string, string> = {
  Nuke:      'nuke',
  Painter:   'substance_painter',
  Mari:      'mari',
  Photoshop: 'photoshop',
  Designer:  'substance_designer',
  Marvelous: 'marvelous',
}

// Designer: one graph = "<package path>::<graph id>", one output = "<graph key>::<output id>".
const graphKey = (pkg: string, graph: string) => `${pkg}::${graph}`
const outputKey = (gk: string, out: string) => `${gk}::${out}`

// ZBrush connection message: distinguish "installed but not answering" (ZBrush
// closed or busy) from "plugin not installed", instead of always blaming install.
function zbrushStatusText(
  connected: boolean, checking: boolean, installed: boolean | null, version: string | null,
): string {
  if (connected) return `Connecté${version ? ` · ${version}` : ''}`
  if (checking) return 'Vérification...'
  if (installed === false) return 'Plugin non installé : bouton Plug dans la sidebar'
  return 'Plugin installé, ZBrush ne répond pas (fermé ou occupé)'
}

// ── Types ─────────────────────────────────────────────────────────────────────

type PublishMode = 'asset' | 'shot'

interface ComposerSel {
  [key: string]: string
  category: string   // asset: CHAR / PROPS / ENV / FX
  name:     string
  task:     string   // asset: GEO / SHADING / GROOM / RIG / CFX (one department each)
  instance: string
  variante: string
  seq:      string   // shot
  shot:     string   // shot
}

const EMPTY_SEL: ComposerSel = { category: '', name: '', task: '', instance: '', variante: '', seq: '', shot: '' }

// Texture-map nomenclature: many real-world aliases -> ONE canonical token. A file
// whose name contains any alias as a segment (e.g. Mesh_basecolor, Mesh_nrm.1001)
// is tagged with the canonical token (BCOL, NORM, ...). Extend freely, and keep the
// backend twin in sync (backend/dcc/texture_publish.py MAP_ALIASES: Painter / Mari).
const MAP_ALIASES: Record<string, string[]> = {
  BCOL:    ['bcol', 'basecolor', 'base_color', 'albedo', 'diffuse', 'diff', 'color', 'col'],
  ROUGH:   ['rough', 'roughness', 'rgh'],
  METAL:   ['metal', 'metallic', 'metalness', 'mtl'],
  SPEC:    ['spec', 'specular'],
  NORM:    ['norm', 'normal', 'nrm', 'nml', 'nor'],
  BUMP:    ['bump'],
  DISP:    ['disp', 'displacement', 'displace', 'height'],
  ZDISP:   ['zdisp'],
  AO:      ['ao', 'occlusion', 'ambientocclusion'],
  OPACITY: ['opacity', 'alpha', 'mask'],
  EMISS:   ['emiss', 'emissive', 'emission', 'emit'],
  SSS:     ['sss', 'subsurface', 'scatter'],
  GLOSS:   ['gloss', 'glossiness'],
  TRANS:   ['trans', 'translucency'],
  CAVITY:  ['cavity'],
  CURV:    ['curv', 'curvature'],
  ISO:     ['iso'],
}

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

// Detect the canonical MAP token for a texture file, or '' when the name carries
// no recognised map nomenclature. Segments are matched exactly (case-insensitive),
// so a number or a random suffix (e.g. "07", "sc060712") is NEVER mistaken for a map.
function detectMapToken(path: string): string {
  const segs = fileStem(path).toLowerCase().split(/[_\-.]/).filter(Boolean)
  const segSet = new Set(segs)
  for (const [canon, aliases] of Object.entries(MAP_ALIASES)) {
    if (aliases.some(a => segSet.has(a))) return canon
  }
  return ''
}

// The suffix that distinguishes each file of a multi-file set, appended AFTER the
// composer INSTANCE (which is always honoured). Prefer the canonical map token;
// when no map is recognised, keep the file stem so files stay distinct instead of
// fabricating a bogus instance from a trailing number.
function mapSuffix(path: string): string {
  return detectMapToken(path) || formatToken(fileStem(path))
}

// Presets row order (2026-09-26): model, rig, look, anim, then custom (drawn after).
const PRESET_ORDER = ['GEO', 'RIG', 'SHADING', 'ANIM']
function presetEntries(table: Record<string, UsdTaskContribution>): [string, UsdTaskContribution][] {
  const rank = (t: string) => (PRESET_ORDER.indexOf(t) + 1 || PRESET_ORDER.length + 1)
  return Object.entries(table).sort(([a], [b]) => rank(a) - rank(b))
}

// Shot tasks the Publisher offers (2026-09-26): anim, camera (LAYOUT carries the
// shot camera, shot_stage), FX and light; COMP only from Nuke. No rig / model in a shot.
function shotTasksFor(dcc: string): string[] {
  const base = ['ANIM', 'LAYOUT', 'FX', 'LIGHT']
  return dcc === 'Nuke' ? [...base, 'COMP'] : base
}

// Publisher category → pipeline CLASS token. "FX" is a display label for FXRIG.
const CATEGORY_TO_CLASS: Record<string, string> = { CHAR: 'CHAR', PROPS: 'PROPS', ENV: 'ENV', FX: 'FXRIG' }
const ASSET_CATEGORIES = ['CHAR', 'PROPS', 'ENV', 'FX'] as const
// Coarse task = TYPE token (fixed order); label shown title-cased, value uppercase.
// One task = one USD department (ADR 0019): MULT is gone, a publish carries one thing.
const ASSET_TASKS: { value: string; label: string }[] = [
  { value: 'GEO', label: 'Geo' }, { value: 'ANIM', label: 'Anim' }, { value: 'SHADING', label: 'Shading' },
  { value: 'GROOM', label: 'Groom' }, { value: 'RIG', label: 'Rig' }, { value: 'CFX', label: 'Cfx' },
  { value: 'REF', label: 'Ref' },
]
// Which task writes which USD department comes from the backend (GET /usd/departments,
// ADR 0019): one table, no copy to drift. This is only the fallback used while the
// request is in flight or when the backend is unreachable.
const USD_DEPARTMENTS_FALLBACK: Record<string, UsdTaskContribution> = {
  GEO:  { department: 'model', label: 'model', what: 'géométrie seule (points, faces, normales, UV)', writer: 'light',
          include: { geo: true,  skel: false, anim: false, weights: false, uv: true } },
  RIG:  { department: 'rig',   label: 'rig', what: 'squelette en rest pose + poids de skin (boneCapture)', writer: 'light',
          include: { geo: true,  skel: true,  anim: false, weights: true,  uv: false } },
  ANIM: { department: 'clip',  label: 'anim', what: 'rotations des joints animés', writer: 'light',
          include: { geo: false, skel: true,  anim: true,  weights: false, uv: false } },
  SHADING: { department: 'look', label: 'look', what: 'matériaux et assignations (sans géométrie)', writer: 'look',
             include: { geo: false, skel: false, anim: false, weights: false, uv: false } },
}
// Shot tasks FLUX writes itself (2026-09-18): SEQ_SHOT_ANIM_<NAME> = the motion of
// one character, the 4th token is the character.
const USD_SHOT_DEPARTMENTS_FALLBACK: Record<string, UsdTaskContribution> = {
  ANIM: { department: 'animation', label: 'anim', what: "mouvement du squelette d'un perso (seulement les joints qui bougent)",
          writer: 'light', include: { geo: false, skel: true, anim: true, weights: false, uv: false } },
}

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
  shotName: { title: 'Task', desc: 'Le département du plan, à la même place que le TYPE dans un asset (ADR 0019). LAYOUT porte la caméra du plan.', expected: 'ANIM, LAYOUT (caméra), FX, LIGHT (COMP depuis Nuke)', example: 'SEQ001_SHOT010_ANIM_DINGO' },
  shotCharacter: { title: 'Perso', desc: "L'anim d'un plan = le mouvement d'un perso (2026-09-18). Un 2e DINGO dans le plan : DINGO_02.", expected: 'NAME d\'un asset', example: 'SEQ001_SHOT010_ANIM_DINGO' },
  shotVariante: { title: 'Variante', desc: 'Remplace Instance en mode Shot. Suggestions basées sur Sequence + Shot + Task.', expected: 'Champ libre', example: 'SEQ001_SHOT010_ANIM_block_LAST' },
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
  dcc:     string
  onModeSwitch: () => void
  onSelect:     (key: string, value: string) => void
  onArchiveToken: (field: 'name' | 'instance' | 'seq' | 'shot', value: string) => void
}

function PublishComposer({ project, tokens, seqs, shots, mode, sel, dcc, onModeSwitch, onSelect, onArchiveToken }: ComposerProps) {
  // Asset names for the selected category (filtered by its CLASS path)
  const cls = CATEGORY_TO_CLASS[sel.category] ?? ''
  const classPath = (tokens.CLASS?.[cls] ?? '').replace(/\\/g, '/')
  const names = classPath
    ? Object.keys(tokens.NAME ?? {}).filter(k => (tokens.NAME?.[k] ?? '').replace(/\\/g, '/').startsWith(classPath + '/'))
    : []

  // Contextual suggestions, scanned from disk (never global)
  const [instanceSug, setInstanceSug] = useState<string[]>([])
  const [varianteSug, setVarianteSug] = useState<string[]>([])

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
          <ModuleBox label="Task" info={TOKEN_INFO.shotName} value={sel.name} fixed options={shotTasksFor(dcc)} placeholder="—" onChange={v => onSelect('name', v)} />
          {formatToken(sel.name) === 'ANIM' ? (
            <ModuleBox label="Perso" info={TOKEN_INFO.shotCharacter} value={sel.variante}
              options={Object.keys(tokens.NAME ?? {}).sort()} placeholder="DINGO"
              onChange={v => onSelect('variante', v)} />
          ) : (
            <ModuleBox label="Variante" info={TOKEN_INFO.shotVariante} value={sel.variante} options={varianteSug} placeholder="null" onChange={v => onSelect('variante', v)} />
          )}
        </>
      )}
    </div>
  )
}

// ── Publisher ─────────────────────────────────────────────────────────────────

// Character NAME of a shot animation token: DINGO_02 -> DINGO (U2).
function characterBase(token: string): string {
  return token.replace(/_\d+$/, '')
}

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
  // ANIMATION = one file with time samples over a frame range (abc / USD).
  // SÉQUENCE = one file per frame ($F4 folder). Frame fields are shared.
  const [animRange, setAnimRange] = useState(false)
  const [frameStart, setFrameStart] = useState(1)
  const [frameEnd, setFrameEnd]     = useState(100)
  const [frameStep, setFrameStep]   = useState(1)
  // Where Start / End came from (U1): the keys of the DCC, its timeline, or typed by hand.
  const [rangeInfo, setRangeInfo]   = useState('')

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
  const [zbrushChecking, setZbrushChecking]   = useState(false)
  const [zbrushPluginInstalled, setZbrushPluginInstalled] = useState<boolean | null>(null)
  // Per-format ZBrush export options, rendered via <ExportOptions> in the right
  // panel like Maya/Houdini. Reset to the format defaults when the format changes.
  const [zbrushExportOpts, setZbrushExportOpts] = useState<Record<string, unknown>>(
    () => defaultZbrushOptions('.obj'),
  )

  // Nuke per-format export options (Write knobs), rendered via <ExportOptions>.
  const [nukeExportOpts, setNukeExportOpts] = useState<Record<string, unknown>>(
    () => defaultNukeOptions('.exr'),
  )

  // Photoshop per-format export options (COM save-option fields).
  const [psExportOpts, setPsExportOpts] = useState<Record<string, unknown>>(
    () => defaultPhotoshopOptions('.psd'),
  )

  // Painter / Mari options (preset / bit depth / conform_tx). These map to typed
  // request fields, not a Write-knob dict; the format comes from the shared picker.
  const [painterOpts, setPainterOpts] = useState<Record<string, unknown>>(() => defaultPainterOptions())
  const [mariOpts, setMariOpts] = useState<Record<string, unknown>>(() => defaultMariOptions())
  // Painter texture sets / Mari channels read from the app: the ticked ones export.
  const [texItems, setTexItems]     = useState<{ name: string; detail: string }[]>([])
  const [texChecked, setTexChecked] = useState<Set<string>>(new Set())
  const [texSource, setTexSource]   = useState('')
  const [texLoading, setTexLoading] = useState(false)
  // Painter: the presets it really has, and the maps of the chosen one (2026-09-25:
  // map by map like Mari, bit depth and size per map, only the ticked maps publish).
  const [painterPresets, setPainterPresets] = useState<PainterPreset[]>([])
  const [mapChecked, setMapChecked] = useState<Set<string>>(new Set())
  const [mapOpts, setMapOpts] = useState<Record<string, MapOpts>>({})
  // Mari: format / bit depth / size per channel (same table as Painter's maps).
  const [chanOpts, setChanOpts] = useState<Record<string, MapOpts>>({})
  // The project's Painter export presets (project.json, picked at creation): only those
  // are offered; none chosen = every preset of Painter (2026-09-26).
  const [projectPresets, setProjectPresets] = useState<string[]>([])
  const [bundledPresets, setBundledPresets] = useState<string[]>([])
  useEffect(() => {
    if (!project) { setProjectPresets([]); return }
    api.getPainterPresets(project)
      .then(r => { setProjectPresets(r.project); setBundledPresets(r.bundled) })
      .catch(() => setProjectPresets([]))
  }, [project])
  const toggleProjectPreset = (name: string) => {
    if (!project) return
    const next = projectPresets.includes(name) ? projectPresets.filter(n => n !== name) : [...projectPresets, name]
    api.putPainterPresets(project, next)
      .then(r => { setProjectPresets(r.project); toast.success(`Presets du projet : ${r.project.join(', ') || 'tous'}`) })
      .catch(e => toast.error(e instanceof Error ? e.message : String(e)))
  }
  const offeredPresets = projectPresets.length
    ? painterPresets.filter(p => projectPresets.includes(p.name))
    : painterPresets
  const missingPresets = projectPresets.filter(n => !painterPresets.some(p => p.name === n))
  const curPreset = offeredPresets.find(p => p.url === painterOpts.preset || p.name === painterOpts.preset)
  // "Canaux du shader": every channel of the stacks (coat, anisotropy, user...), not only
  // the preset's maps. Map id = the fileName the backend gives it ($textureSet_<Label>).
  const [painterChannels, setPainterChannels] = useState<PainterChannel[]>([])
  const channelMapId = (c: PainterChannel) => `$textureSet_${(c.label || c.id).replace(/[^A-Za-z0-9]/g, '') || c.id}`
  // One table: the preset's maps (ticked), then every shader channel that can be added on
  // top of the preset (coat, anisotropy, user...), unticked until wanted.
  const presetRows: { id: string; label: string; detail?: string }[] = curPreset?.maps ?? []
  const channelRows: { id: string; label: string; detail?: string }[] = painterChannels
    .map(c => ({ id: channelMapId(c), label: `+ ${c.label}`, detail: 'canal' }))
    .filter(r => !presetRows.some(m => m.id === r.id))
  const mapRows = [...presetRows, ...channelRows]

  // Designer: the graphs of the open packages (ticked ones export) and their outputs.
  const [designerOpts, setDesignerOpts] = useState<Record<string, unknown>>(() => defaultDesignerOptions())
  const [designerPkgs, setDesignerPkgs] = useState<DesignerPackage[]>([])
  const [graphChecked, setGraphChecked] = useState<Set<string>>(new Set())
  const [outputChecked, setOutputChecked] = useState<Set<string>>(new Set())
  // Marvelous: the open project and the formats this Marvelous can export.
  const [marvelousOpts, setMarvelousOpts] = useState<Record<string, unknown>>(() => defaultMarvelousOptions())
  const [marvelousFormats, setMarvelousFormats] = useState<string[]>([])
  const [marvelousScript, setMarvelousScript] = useState<string | null>(null)
  const designerGraphs = designerPkgs.flatMap(p => p.graphs.map(g => ({ key: graphKey(p.path, g.id), pkg: p, graph: g })))

  // Generic connection status for socket-bridge DCCs (Nuke/Painter/Mari/Photoshop):
  // one polling effect pings the active DCC's key with retry, like Maya/ZBrush, so a
  // single cold ping never shows "non connecté".
  const [bridgeStatus, setBridgeStatus] = useState<{ connected: boolean; checking: boolean; version: string | null }>(
    { connected: false, checking: false, version: null },
  )


  // Houdini-specific
  const [ropNodePath, setRopNodePath]             = useState('')
  const [houdiniConnected, setHoudiniConnected]   = useState(false)
  const [houdiniVersion, setHoudiniVersion]       = useState<string | null>(null)
  const [detectedNodeType, setDetectedNodeType]   = useState<string | null>(null)

  // Maya-specific
  const [mayaConnected, setMayaConnected]           = useState(false)
  const [mayaScope, setMayaScope]                   = useState<'scene' | 'selection'>('scene')
  // Multi-instance shot anim (U2): character instances found in Maya, ticked ones publish.
  const [charInstances, setCharInstances] = useState<{ node: string; label: string; instance: number; meshes: number }[]>([])
  const [charChecked, setCharChecked]     = useState<Set<string>>(new Set())
  const [charLoading, setCharLoading]     = useState(false)
  // Who writes the USD of an asset task: null = the default for this task (FLUX when
  // the task has a department), true/false = the artist's explicit choice.
  const [fluxWriter, setFluxWriter]                 = useState<boolean | null>(null)
  const [usdDepartments, setUsdDepartments] = useState(USD_DEPARTMENTS_FALLBACK)
  const [usdShotDepartments, setUsdShotDepartments] = useState(USD_SHOT_DEPARTMENTS_FALLBACK)
  useEffect(() => {
    api.getUsdDepartments().then(d => {
      setUsdDepartments(d.tasks)
      if (d.shot_tasks) setUsdShotDepartments(d.shot_tasks)
    }).catch(() => {})
  }, [])
  const usdContribution = mode === 'asset'
    ? usdDepartments[sel.task]
    : usdShotDepartments[formatToken(sel.name)]
  // FLUX writes the layered USD by default for a task that has a department.
  const usdLayers = (fluxWriter ?? !!usdContribution) && !!usdContribution
  // The look department is written by its own exporter (materials, no geometry).
  const usdLook = usdLayers && usdContribution?.writer === 'look'
  const usdInclude = usdContribution?.include
    ?? { geo: true, skel: true, anim: true, weights: true, uv: true }
  // USD preset FLUX writes for this task (ADR 0034): its own options, its own listing.
  // null = no FLUX department, or the DCC writes the file ("custom").
  // Only for a USD format: a .ma / .mb / .fbx / .abc of the same task exports the scene
  // (or the selection) as usual, with that format's own options.
  const usdPreset: UsdPreset | null = usdLayers && ['.usd', '.usda', '.usdc'].includes(exportExt)
    ? presetForTask(mode === 'asset' ? sel.task : formatToken(sel.name), mode === 'shot') : null
  const [usdPresetOpts, setUsdPresetOpts] = useState(defaultPresetOptions)
  const [usdPreview, setUsdPreview] = useState<MayaUsdPreview | null>(null)
  const [usdPreviewBusy, setUsdPreviewBusy] = useState(false)
  const [usdPreviewErr, setUsdPreviewErr] = useState('')
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

  // ZBrush plugin install status — drives the "installed vs reachable" message,
  // re-checked whenever the ZBrush panel becomes active (catches Sidebar install).
  useEffect(() => {
    if (dcc !== 'ZBrush') return
    api.getDccAutostart('zbrush')
      .then(r => setZbrushPluginInstalled(r.installed))
      .catch(() => setZbrushPluginInstalled(null))
  }, [dcc])

  // ZBrush connection — poll with retry while the ZBrush panel is active, like Maya.
  // A single failed ping never sticks: the bridge now answers pings even outside a
  // publish, but the socket can still be cold for a moment, so we keep polling
  // instead of concluding "not connected" on the first miss. Navigation-state
  // (Sidebar detected a freeze) still wins instantly with no ping.
  useEffect(() => {
    if (location.state?.zbrushConnected) {
      setDcc('ZBrush')
      setZbrushConnected(true)
      setZbrushChecking(false)
      return
    }
    if (dcc !== 'ZBrush') {
      setZbrushConnected(false); setZbrushVersion(null); setZbrushChecking(false)
      return
    }
    let cancelled = false
    setZbrushChecking(true)
    const poll = async () => {
      try {
        const p = await api.pingDcc('zbrush')
        if (cancelled) return
        setZbrushConnected(p.connected)
        setZbrushVersion(p.version ?? null)
      } catch {
        if (!cancelled) setZbrushConnected(false)
      } finally {
        if (!cancelled) setZbrushChecking(false)
      }
    }
    void poll()
    const id = setInterval(() => void poll(), 3500)
    return () => { cancelled = true; clearInterval(id) }
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
    setNukeExportOpts(defaultNukeOptions(exportExt))
    setPsExportOpts(defaultPhotoshopOptions(exportExt))
  }, [exportExt])

  // Generic bridge-DCC connection polling (Nuke/Painter/Mari/Photoshop). Pings the
  // active DCC's key every 3.5 s with retry; stays in "Vérification..." until the
  // first answer so a cold socket never reads as "non connecté".
  useEffect(() => {
    const key = DCC_PING_KEY[dcc]
    if (!key) { setBridgeStatus({ connected: false, checking: false, version: null }); return }
    let cancelled = false
    setBridgeStatus(s => ({ ...s, checking: true }))
    const poll = async () => {
      try {
        const p = await api.pingDcc(key)
        if (cancelled) return
        setBridgeStatus({ connected: p.connected, checking: false, version: p.version ?? null })
      } catch {
        if (!cancelled) setBridgeStatus({ connected: false, checking: false, version: null })
      }
    }
    void poll()
    const id = setInterval(() => void poll(), 3500)
    return () => { cancelled = true; clearInterval(id) }
  }, [dcc])

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
    // ADR 0019: SEQ_SHOT_TASK[_VARIANTE] — the department sits where an asset has its TYPE.
    return `${formatSeqLabel(sel.seq)}_${formatShotLabel(sel.shot)}_${formatToken(sel.name)}_${varr}`
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

  const handleCancelZBrush = useCallback(async () => {
    try {
      await api.cancelZBrush()          // sends stop; the bridge acks even when idle
      toast.success('ZBrush libéré')
    } catch {
      // ZBrush not reachable (closed / already released): nothing to free.
      toast('ZBrush déjà libre')
    }
    setZbrushConnected(false)
    setZbrushVersion(null)
  }, [])

  const reset = useCallback(() => {
    setSel(EMPTY_SEL)
    setSourcePath('')
    setDescription('')
  }, [])

  const ANIM_EXTS = ['.abc', '.usd', '.usda', '.usdc']
  // model / rig / look presets are a rest state: no frame range (2026-09-26).
  const animCapable = (dcc === 'Maya' || dcc === 'Houdini') && ANIM_EXTS.includes(exportExt)
    && !(usdPreset && usdPreset !== 'anim')
  const seqCapable = (dcc === 'Houdini' && !animCapable && !['.hip', '.hiplc', '.hipnc'].includes(exportExt))
    || (dcc === 'Nuke' && exportExt !== '.nk')

  // Character instances in Maya (U2): listed as soon as a shot animation of a
  // character is being published, every instance ticked by default.
  const shotCharName = mode === 'shot' && formatToken(sel.variante) && formatToken(sel.variante) !== 'null'
    ? characterBase(formatToken(sel.variante)) : ''
  const instancePicker = dcc === 'Maya' && mode === 'shot' && usdLayers
    && ['.usd', '.usda', '.usdc'].includes(exportExt) && !!shotCharName
  const loadInstances = useCallback(async (quiet: boolean) => {
    if (!shotCharName) return
    setCharLoading(true)
    try {
      const r = await api.getMayaCharacterInstances(shotCharName, readActiveInstancePort('Maya') ?? undefined)
      setCharInstances(r.items)
      setCharChecked(new Set(r.items.map(i => i.node)))
      if (!quiet && r.items.length === 0) toast.info(`Aucune instance de ${shotCharName} dans Maya`)
    } catch (e) {
      setCharInstances([])
      if (!quiet) toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setCharLoading(false)
    }
  }, [shotCharName])

  useEffect(() => {
    if (instancePicker && mayaConnected) void loadInstances(true)
    else { setCharInstances([]); setCharChecked(new Set()) }
  }, [instancePicker, mayaConnected, loadInstances])

  // Fill Start / End from the DCC (U1): first / last key of what is exported, else
  // the timeline. Runs when ANIMATION is switched on and when the Maya scope changes.
  const fetchAnimRange = useCallback(async () => {
    if (dcc !== 'Maya' && dcc !== 'Houdini') return
    try {
      const r = await api.getAnimRange(dcc, mayaScope, dcc === 'Maya' ? (readActiveInstancePort('Maya') ?? undefined) : undefined)
      // ANIM preset: Start stays 1001 (or the artist's pre-roll), End = the last key.
      if (usdPreset !== 'anim') setFrameStart(r.start)
      setFrameEnd(r.end)
      setRangeInfo(r.source === 'keys'
        ? `Clés ${r.start}-${r.end} (${r.curves} courbe${r.curves > 1 ? 's' : ''})`
        : `Timeline ${r.start}-${r.end} (aucune clé)`)
    } catch {
      setRangeInfo(`${dcc} ne répond pas : plage à saisir`)
    }
  }, [dcc, mayaScope, usdPreset])

  useEffect(() => {
    if (animCapable && animRange) void fetchAnimRange()
  }, [animCapable, animRange, fetchAnimRange])

  // ANIM preset (2026-09-26): animation on by default, Start 1001 (a pre-roll such
  // as 995 stays editable), End from the last key of the scene (fetch above).
  useEffect(() => {
    if (usdPreset !== 'anim') return
    setAnimRange(true)
    setFrameStart(1001)
  }, [usdPreset])

  // What the preset will export (listing), read from Maya when the preset or the scope changes.
  const fetchUsdPreview = useCallback(async () => {
    if (dcc !== 'Maya' || !usdPreset) { setUsdPreview(null); return }
    setUsdPreviewBusy(true)
    setUsdPreviewErr('')
    try {
      const r = await api.getMayaUsdPreview(usdPreset, mayaScope,
        usdPreset === 'anim' ? frameStart : undefined, usdPreset === 'anim' ? frameEnd : undefined,
        readActiveInstancePort('Maya') ?? undefined)
      setUsdPreview(r)
    } catch (e) {
      setUsdPreview(null)
      setUsdPreviewErr(e instanceof Error ? e.message : String(e))
    } finally {
      setUsdPreviewBusy(false)
    }
  }, [dcc, usdPreset, mayaScope, frameStart, frameEnd])
  const previewRef = useRef(fetchUsdPreview)
  previewRef.current = fetchUsdPreview
  useEffect(() => {
    if (dcc === 'Maya' && usdPreset && mayaConnected) void previewRef.current()
    else setUsdPreview(null)
  }, [dcc, usdPreset, mayaScope, mayaConnected])

  const handlePublish = useCallback(async () => {
    if (!project) { toast.error('Sélectionne un projet'); return }
    const animOn = animCapable && animRange
    const seqOn = seqCapable && isSequence
    // Shot animation (SEQ_SHOT_ANIM_<NAME>): the 4th token is the animated character.
    const shotCharacter = mode === 'shot'
      ? (formatToken(sel.variante) && formatToken(sel.variante) !== 'null' ? formatToken(sel.variante) : '')
      : null

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
        if (usdLook && mode === 'asset' && ['.usd', '.usda', '.usdc'].includes(exportExt)) {
          const res = await api.exportMayaLookUsd({
            project_name: project,
            filename,
            fmt:          exportExt.replace('.', ''),
            scope:        mayaScope,
            user:         settings?.username ?? undefined,
            port:         readActiveInstancePort('Maya') ?? undefined,
          })
          toast.success(`Look ${res.version} → ${res.materials} matériau(x), ${res.bindings} liaison(s)`)
          res.warnings?.forEach(w => toast.warning(w))
          return
        }
        if (usdLayers && ['.usd', '.usda', '.usdc'].includes(exportExt)) {
          const assetName = shotCharacter ?? (formatToken(sel.name) || parts[2])
          if (!assetName) { toast.error('Choisis le perso animé (4e case)'); return }
          // Preset options (ADR 0034): Maya runs the preset sweep (model / rig / anim).
          const presetOptions = usdPreset && usdPreset !== 'look'
            ? { preset: usdPreset, ...usdPresetOpts[usdPreset] } : undefined
          const picked = mode === 'shot' ? charInstances.filter(i => charChecked.has(i.node)) : []
          if (picked.length > 0) {
            // One shot animation per ticked instance, from the meshes under its node.
            const charName = characterBase(assetName)
            for (const it of picked) {
              const token = it.instance === 1 ? charName : `${charName}_${String(it.instance).padStart(2, '0')}`
              const fn = `${formatSeqLabel(sel.seq)}_${formatShotLabel(sel.shot)}_${formatToken(sel.name)}_${token}`
              try {
                const r = await api.exportMayaLightUsd({
                  project_name: project, asset: charName, filename: fn, root: it.node,
                  fmt: exportExt.replace('.', ''), scope: 'selection',
                  frame_start: animOn ? frameStart : undefined, frame_end: animOn ? frameEnd : undefined,
                  include_geo: usdInclude.geo, include_skel: usdInclude.skel, include_anim: usdInclude.anim,
                  include_weights: usdInclude.weights, include_uv: usdInclude.uv,
                  options: presetOptions,
                  port: readActiveInstancePort('Maya') ?? undefined,
                })
                toast.success(`${fn} ${r.version}`)
                r.warnings?.forEach(w => toast.warning(w))
              } catch (e) {
                toast.error(`${fn} : ${e instanceof Error ? e.message : String(e)}`)
              }
            }
            return
          }
          const res = await api.exportMayaLightUsd({
            project_name: project,
            asset:        assetName,
            filename,
            fmt:          exportExt.replace('.', ''),
            scope:        mayaScope,
            frame_start:  animOn ? frameStart : undefined,
            frame_end:    animOn ? frameEnd : undefined,
            include_geo:     usdInclude.geo,
            include_skel:    usdInclude.skel,
            include_anim:    usdInclude.anim,
            include_weights: usdInclude.weights,
            include_uv:      usdInclude.uv,
            options:         presetOptions,
            port:            readActiveInstancePort('Maya') ?? undefined,
          })
          toast.success(`USD ${usdPreset ?? 'léger'} ${res.version} → ${res.asset}`)
          res.warnings?.forEach(w => toast.warning(w))
          return
        }
        const res = await api.publishMaya({
          project_name: project,
          filename,
          extension:    exportExt,
          scope:        mayaScope,
          is_sequence:  false,
          frame_range:  animOn ? [frameStart, frameEnd, frameStep] : undefined,
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
        if (usdLook && mode === 'asset' && ['.usd', '.usda', '.usdc'].includes(exportExt)) {
          const res = await api.exportHoudiniLookUsd({
            project_name: project,
            filename,
            lop_node:     ropNodePath || undefined,
            fmt:          exportExt.replace('.', ''),
            user:         settings?.username ?? undefined,
          })
          toast.success(`Look ${res.version} → ${res.materials} matériau(x), ${res.bindings} liaison(s)`)
          res.warnings?.forEach(w => toast.warning(w))
          return
        }
        if (usdLayers && ['.usd', '.usda', '.usdc'].includes(exportExt)) {
          const assetName = shotCharacter ?? (formatToken(sel.name) || parts[2])
          if (!assetName) { toast.error('Choisis le perso animé (4e case)'); return }
          const res = await api.exportHoudiniLightUsd({
            project_name: project,
            asset:        assetName,
            filename,
            fmt:          exportExt.replace('.', ''),
            frame_start:  animOn ? frameStart : undefined,
            frame_end:    animOn ? frameEnd : undefined,
            include_geo:     usdInclude.geo,
            include_skel:    usdInclude.skel,
            include_anim:    usdInclude.anim,
            include_weights: usdInclude.weights,
            include_uv:      usdInclude.uv,
          })
          toast.success(`USD Layers ${res.version} → ${res.asset}`)
          res.warnings?.forEach(w => toast.warning(w))
          return
        }
        const res = await api.publishHoudiniRop({
          project_name:  project,
          filename,
          extension:     exportExt,
          rop_node_path: ropNodePath || undefined,
          is_sequence:   seqOn,
          frame_range:   (animOn || seqOn) ? [frameStart, frameEnd, frameStep] : undefined,
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
      } else if (dcc === 'Nuke') {
        if (!bridgeStatus.connected) {
          toast.error('Nuke non connecté : lance le serveur FLUX dans Nuke (menu FLUX)')
          return
        }
        // colorspace is a top-level arg of the backend (not a Write knob): pull it
        // out of the options map and send the rest as Write knobs.
        const { colorspace, ...writeKnobs } = nukeExportOpts as { colorspace?: string } & Record<string, unknown>
        const isSeq = seqOn
        const res = await api.publishNuke({
          project_name:   project,
          filename,
          extension:      exportExt,
          export_options: writeKnobs,
          is_sequence:    isSeq,
          frame_range:    isSeq ? [frameStart, frameEnd] : undefined,
          colorspace:     typeof colorspace === 'string' ? colorspace : undefined,
          description:    description || undefined,
          user:           settings?.username ?? undefined,
        })
        toast.success(`${versionLabel(res.version_str)} → Nuke`)
      } else if (dcc === 'Photoshop') {
        if (!bridgeStatus.connected) {
          toast.error('Photoshop non connecté : ouvre Photoshop (photoshop-python-api requis)')
          return
        }
        const res = await api.publishPhotoshop({
          project_name:   project,
          filename,
          extension:      exportExt,
          export_options: psExportOpts,
          description:    description || undefined,
          user:           settings?.username ?? undefined,
        })
        toast.success(`${versionLabel(res.version_str)} → Photoshop`)
      } else if (dcc === 'Painter' || dcc === 'Mari') {
        // The ping can fail while the bridge answers (a busy app): once its texture sets /
        // channels were read, the publish is tried and reports its own error.
        if (!bridgeStatus.connected && texItems.length === 0) {
          toast.error(`${dcc} non connecté : ouvre ${dcc} avec le bridge FLUX actif`)
          return
        }
        if (mode !== 'asset') {
          toast.error('Le texturing se publie en mode Asset (Catégorie / Task / Name)')
          return
        }
        // Tokens from the asset composer (same derivation as buildFilename).
        const tokens = {
          project_name: project,
          class_token:  CATEGORY_TO_CLASS[sel.category] ?? formatToken(sel.category),
          task_token:   sel.task,
          name_token:   formatToken(sel.name),
          instance:     formatToken(sel.instance) || 'null',
          file_format:  exportExt.replace('.', ''),
          description:  description || undefined,
          user:         settings?.username ?? undefined,
        }
        // Only the ticked texture sets / channels (all ticked = let the app export all).
        const picked = texItems.length > 0 && texChecked.size < texItems.length
          ? texItems.map(t => t.name).filter(n => texChecked.has(n)) : undefined
        if (picked && picked.length === 0) { toast.error(dcc === 'Painter' ? 'Coche au moins un texture set' : 'Coche au moins un channel'); return }
        const presetIds = presetRows.map(m => m.id)
        const tickedPreset = presetIds.filter(id => mapChecked.has(id))
        const extraChannels = painterChannels.filter(c => channelRows.some(r => r.id === channelMapId(c)) && mapChecked.has(channelMapId(c)))
        // every preset map = no filter; none = the added channels only
        const pickedMaps = tickedPreset.length === presetIds.length ? undefined : tickedPreset
        if (dcc === 'Painter' && tickedPreset.length === 0 && extraChannels.length === 0) { toast.error('Coche au moins une map'); return }
        const mapParams = buildMapParams(mapRows, mapChecked, mapOpts)
        const chanParams = buildMapParams(texItems.map(t => ({ id: t.name, label: t.name })), texChecked, chanOpts)
        const res = dcc === 'Painter'
          ? await api.publishSubstance({
              ...tokens,
              preset:       String(painterOpts.preset ?? 'PBR Metallic Roughness'),
              bit_depth:    String(painterOpts.bit_depth ?? '8'),
              conform_tx:   !!painterOpts.conform_tx,
              texture_sets: picked,
              size:         painterOpts.size ? Number(painterOpts.size) : undefined,
              padding:      String(painterOpts.padding ?? 'infinite'),
              dilation:     Number(painterOpts.dilation ?? 16),
              maps:         pickedMaps,
              map_params:   Object.keys(mapParams).length ? mapParams : undefined,
              channels:     extraChannels.length ? extraChannels : undefined,
            })
          : await api.publishMari({ ...tokens, conform_tx: !!mariOpts.conform_tx, channels: picked,
                                    channel_params: Object.keys(chanParams).length ? chanParams : undefined })
        const n = res.published?.length ?? 0
        const timings = 'timings' in res && res.timings ? ` (${res.timings})` : ''
        toast.success(`${n} map${n > 1 ? 's' : ''} publiée${n > 1 ? 's' : ''} → ${dcc}${res.tx?.length ? ' · .tx' : ''}${timings}`)
        res.warnings?.forEach(w => toast.warning(w))
      } else if (dcc === 'Designer') {
        // Like Painter: the bridge exports the ticked graphs (their ticked outputs, the
        // .sbsar / .sbs), FLUX publishes each under the asset tokens.
        if (!bridgeStatus.connected && designerGraphs.length === 0) {
          toast.error('Designer non connecté : ouvre Designer avec le bridge FLUX actif')
          return
        }
        if (mode !== 'asset') {
          toast.error('Designer se publie en mode Asset (Catégorie / Task / Name)')
          return
        }
        const picked = designerGraphs.filter(g => graphChecked.has(g.key))
        if (designerGraphs.length > 0 && picked.length === 0) { toast.error('Coche au moins un graph'); return }
        if (!designerOpts.maps && !designerOpts.sbsar && !designerOpts.sbs) {
          toast.error('Coche les maps, le .sbsar ou le .sbs'); return
        }
        const graphs = picked.map(g => {
          const outs = g.graph.outputs.map(o => o.id).filter(id => outputChecked.has(outputKey(g.key, id)))
          return { package: g.pkg.path, graph: g.graph.id,
                   outputs: outs.length < g.graph.outputs.length ? outs : null }
        })
        if (designerOpts.maps && graphs.some(g => g.outputs && g.outputs.length === 0) && !designerOpts.sbsar && !designerOpts.sbs) {
          toast.error('Coche au moins un output par graph'); return
        }
        const res = await api.publishDesignerBridge({
          project_name: project,
          class_token:  CATEGORY_TO_CLASS[sel.category] ?? formatToken(sel.category),
          task_token:   sel.task,
          name_token:   formatToken(sel.name),
          instance:     formatToken(sel.instance) || 'null',
          graphs:       graphs.length ? graphs : undefined,
          file_format:  exportExt.replace('.', ''),
          size:         designerOpts.size ? Number(designerOpts.size) : undefined,
          bit_depth:    designerOpts.bit_depth ? String(designerOpts.bit_depth) : undefined,
          maps:         !!designerOpts.maps,
          sbsar:        !!designerOpts.sbsar,
          sbs:          !!designerOpts.sbs,
          conform_tx:   !!designerOpts.conform_tx,
          description:  description || undefined,
          user:         settings?.username ?? undefined,
        })
        const n = res.published?.length ?? 0
        toast.success(`${n} fichier${n > 1 ? 's' : ''} publié${n > 1 ? 's' : ''} → Designer${res.tx?.length ? ' · .tx' : ''}`)
        res.warnings?.forEach(w => toast.warning(w))
      } else if (dcc === 'Marvelous') {
        // The bridge exports the open project in the picked format (+ .zprj), FLUX
        // publishes it under the composed name (asset or shot).
        if (!bridgeStatus.connected && marvelousFormats.length === 0) {
          toast.error('Marvelous non connecté : lance le script bridge FLUX dans Marvelous')
          return
        }
        const { with_zprj, ...options } = marvelousOpts
        const res = await api.publishMarvelousBridge({
          project_name: project,
          target_name:  (nameOverride && nameOverride.trim()) || buildFilename(),
          file_format:  exportExt.replace('.', ''),
          options,
          with_zprj:    !!with_zprj,
          description:  description || undefined,
          user:         settings?.username ?? undefined,
        })
        const n = res.published?.length ?? 0
        toast.success(`${n} fichier${n > 1 ? 's' : ''} publié${n > 1 ? 's' : ''} → Marvelous`)
        res.warnings?.forEach(w => toast.warning(w))
      } else if (dcc === 'Fichier local') {
        // File ingest (Level 1): local files of any type, under the token-composed name.
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
          // Multi-file set: every file lands under the composer INSTANCE, distinguished
          // by a suffix. Autogroup -> canonical map token (basecolor->BCOL, nrm->NORM...),
          // else the file stem. The instance the artist typed is always honoured.
          const distinct = (mode === 'asset' && autoGroup) ? mapSuffix(f) : formatToken(fileStem(f))
          if (mode === 'asset') {
            const inst = formatToken(sel.instance) || 'null'
            const varr = formatToken(sel.variante)
            return `${cls}_${sel.task}_${formatToken(sel.name)}_${inst}_${distinct}` + (varr ? `_${varr}` : '')
          }
          return `${formatToken(sel.name)}_${formatSeqLabel(sel.seq)}_${formatShotLabel(sel.shot)}_${distinct}`
        }
        // Publish one file; ok + what the publish also wrote (.tx, USD proxy).
        const publishOne = async (f: string, target: string): Promise<{ ok: boolean; tx: number; proxy: boolean }> => {
          const r = await api.publish({ source_path: f, project_name: project,
                   description: description || undefined, user: settings?.username ?? undefined,
                   target_name: target })
          return { ok: r.success, tx: r.tx_paths?.length ?? 0, proxy: !!r.proxy_path }
        }
        let okCount = 0, txCount = 0, proxyCount = 0
        const failed: string[] = []
        for (const f of files) {
          try {
            const r = await publishOne(f, targetFor(f))
            if (r.ok) { okCount++; txCount += r.tx; if (r.proxy) proxyCount++ }
            else failed.push(fileStem(f))
          } catch {
            failed.push(fileStem(f))
          }
        }
        if (okCount) {
          // N4: the .tx / proxy written with the publish are reported, not silent.
          const extras = `${txCount ? ` · ${txCount} .tx` : ''}${proxyCount ? ` · proxy USD` : ''}`
          toast.success(
            multi
              ? `${okCount} fichier${okCount > 1 ? 's' : ''} publié${okCount > 1 ? 's' : ''}${extras}${failed.length ? ` · ${failed.length} échec(s)` : ''}`
              : `Publié → ${dcc}${extras}`,
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
    exportExt, ropNodePath, isSequence, animRange, animCapable, seqCapable, frameStart, frameEnd, frameStep,
    description, settings?.username, sourcePath, localFiles, autoGroup, nameOverride,
    zbrushConnected, zbrushExportOpts,
    bridgeStatus.connected, nukeExportOpts, psExportOpts, painterOpts, mariOpts, texItems, texChecked,
    designerOpts, designerGraphs, graphChecked, outputChecked, marvelousOpts, marvelousFormats,
    mapRows, mapChecked, mapOpts, painterChannels, channelRows,
    mayaConnected, mayaScope, mayaExportOpts, usdLayers, usdInclude, usdPreset, usdPresetOpts, sel, houdiniConnected, houExportOpts, houAttrMode, houAttrNames,
  ])

  // The app a texture list belongs to: a slow answer (Mari busy exporting) that lands
  // after switching to Painter must not fill Painter's list (2026-09-26).
  const texDccRef = useRef(dcc)
  const loadTexItems = useCallback(async () => {
    texDccRef.current = dcc
    if (dcc !== 'Painter' && dcc !== 'Mari') return
    const asked = dcc
    const stale = () => texDccRef.current !== asked
    setTexItems([]); setTexChecked(new Set()); setTexSource('')
    setTexLoading(true)
    try {
      if (dcc === 'Painter') {
        const r = await api.getSubstanceInfo()
        if (stale()) return
        setTexItems(r.texture_sets.map(t => ({
          name: t.name, detail: [t.resolution ? `${t.resolution}px` : '', t.udim ? 'UDIM' : ''].filter(Boolean).join(' · '),
        })))
        setTexSource(r.project || 'Aucun projet ouvert')
        setTexChecked(new Set(r.texture_sets.map(t => t.name)))
        setPainterPresets(r.presets ?? [])
        setPainterChannels(r.channels ?? [])
      } else {
        const r = await api.getMariInfo()
        if (stale()) return
        setTexItems(r.channels.map(c => ({
          name: c.name,
          detail: [c.size ? `${c.size >= 1024 ? `${c.size / 1024}K` : c.size}` : '', c.depth ? `${c.depth}b${c.depth > 8 ? 'f' : ''}` : '',
                 c.layers != null ? `${c.layers} calque${c.layers > 1 ? 's' : ''}` : ''].filter(Boolean).join(' '),
        })))
        setTexSource(r.geo || 'Aucune geo')
        setTexChecked(new Set(r.channels.map(c => c.name)))
      }
    } catch (e) {
      if (stale()) return
      setTexItems([])
      setTexSource(e instanceof Error ? e.message : String(e))
    } finally {
      if (!stale()) setTexLoading(false)
    }
  }, [dcc])
  useEffect(() => { void loadTexItems() }, [loadTexItems])

  // Designer graphs / Marvelous project read from the app (Relire re-reads them).
  const [bridgeInfoSource, setBridgeInfoSource] = useState('')
  const loadBridgeInfo = useCallback(async () => {
    if (dcc !== 'Designer' && dcc !== 'Marvelous') return
    setTexLoading(true)
    try {
      if (dcc === 'Designer') {
        const r = await api.getDesignerInfo()
        setDesignerPkgs(r.packages)
        const all = r.packages.flatMap(p => p.graphs.map(g => ({ key: graphKey(p.path, g.id), g })))
        // The graph open in Designer is ticked; none open -> every graph.
        const current = all.filter(x => x.g.current)
        setGraphChecked(new Set((current.length ? current : all).map(x => x.key)))
        setOutputChecked(new Set(all.flatMap(x => x.g.outputs.map(o => outputKey(x.key, o.id)))))
        setBridgeInfoSource(r.packages.length ? r.packages.map(p => p.name).join(', ') : 'Aucun package ouvert')
      } else {
        const r = await api.getMarvelousInfo()
        setMarvelousFormats(r.formats)
        setBridgeInfoSource([r.project || 'Projet sans nom',
          r.patterns != null ? `${r.patterns} patterns` : '', r.avatars != null ? `${r.avatars} avatar(s)` : '',
        ].filter(Boolean).join(' · '))
      }
    } catch (e) {
      if (dcc === 'Designer') setDesignerPkgs([])
      else setMarvelousFormats([])
      setBridgeInfoSource(e instanceof Error ? e.message : String(e))
    } finally {
      setTexLoading(false)
    }
  }, [dcc])
  useEffect(() => { void loadBridgeInfo() }, [loadBridgeInfo])
  // Marvelous has no startup folder: show where the bridge script is, to run it by hand.
  useEffect(() => {
    if (dcc !== 'Marvelous') return
    api.getDccAutostart('marvelous').then(r => setMarvelousScript(r.installed ? r.startup_file : null)).catch(() => setMarvelousScript(null))
  }, [dcc])

  // Presets read from Painter: keep the chosen one if Painter has it, else PBR Metallic
  // Roughness (or the first). A new preset ticks all of its maps.
  useEffect(() => {
    if (!offeredPresets.length || curPreset) return
    const pick = offeredPresets.find(p => p.name === 'PBR Metallic Roughness') ?? offeredPresets[0]
    setPainterOpts(prev => ({ ...prev, preset: pick.url || pick.name }))
  }, [offeredPresets, curPreset])
  useEffect(() => {
    setMapChecked(new Set(presetRows.map(m => m.id)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [curPreset, painterChannels])

  // Several Maya / Houdini open: ask which one publishes before starting.
  const [instancePick, setInstancePick] = useState<{ dcc: string; items: { port: number; label: string; scene: string | null }[] } | null>(null)
  const requestPublish = useCallback(async () => {
    if (publishing) return
    if (dcc === 'Maya' || dcc === 'Houdini') {
      try {
        const r = await api.getDccInstances(dcc)
        if (r.instances.length > 1) {
          setInstancePick({ dcc, items: r.instances })
          return
        }
      } catch { /* listing failed: publish on the current instance */ }
    }
    void handlePublish()
  }, [dcc, publishing, handlePublish])
  const publishOn = (port: number) => {
    if (!instancePick) return
    writeActiveInstancePort(instancePick.dcc, port)
    setInstancePick(null)
    // Houdini follows the backend choice: let it land before the publish call.
    void api.setActiveInstance(instancePick.dcc, port).catch(() => undefined).then(() => handlePublish())
  }

  // Ctrl/Cmd+P → publish (also prevents the browser print dialog)
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'p') {
        e.preventDefault()
        void requestPublish()
      }
    }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [requestPublish])

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
              dcc={dcc}
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
                      background: zbrushConnected ? 'var(--ok)' : zbrushChecking ? 'var(--ink-4)' : 'var(--err)',
                    }} />
                    <div style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--ink-3)' }}>
                      {zbrushStatusText(zbrushConnected, zbrushChecking, zbrushPluginInstalled, zbrushVersion)}
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
                <div className="cap" style={{ marginBottom: 6 }}>
                  FICHIER SOURCE
                </div>
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

                {/* Multi-file set: list + autogroup toggle. Every file publishes UNDER
                    the composer INSTANCE; autogroup distinguishes them by canonical map
                    token (basecolor->BCOL...), else by the file stem. */}
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
                        const distinct = (mode === 'asset' && autoGroup) ? mapSuffix(f) : formatToken(fileStem(f))
                        const instLabel = mode === 'asset'
                          ? (formatToken(sel.instance) || 'null')
                          : `${formatSeqLabel(sel.seq)}/${formatShotLabel(sel.shot)}`
                        return (
                          <div key={f} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 9, fontFamily: 'var(--mono)', color: 'var(--ink-3)' }}>
                            <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{fileStem(f)}</span>
                            <span style={{ color: 'var(--accent-hi)', flexShrink: 0 }}>→ {instLabel} · {distinct}</span>
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
            ) : DCC_PING_KEY[dcc] ? (
              <div>
                <div className="cap" style={{ marginBottom: 6 }}>CONNEXION {dcc.toUpperCase()}</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <div style={{
                    width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
                    background: bridgeStatus.connected ? 'var(--ok)' : bridgeStatus.checking ? 'var(--ink-4)' : 'var(--err)',
                  }} />
                  <div style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--ink-3)' }}>
                    {bridgeStatus.connected
                      ? `Connecté${bridgeStatus.version ? ` · ${bridgeStatus.version}` : ''}`
                      : bridgeStatus.checking
                        ? 'Vérification...'
                        : dcc === 'Marvelous'
                          ? 'Marvelous ne répond pas : dans Marvelous 2024.1+, Plugins > Plug-in > FLUX Bridge ; en 2024, la ligne ci-dessous (une fois par session)'
                          : `${dcc} ne répond pas : lance le bridge FLUX dans ${dcc} (bouton Plug dans la sidebar pour l'autostart)`}
                  </div>
                </div>
                {dcc === 'Marvelous' && !bridgeStatus.connected && !bridgeStatus.checking && (
                  <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 5 }}>
                    {marvelousScript
                      ? <>
                          <span style={{ fontSize: 10, color: 'var(--ink-3)' }}>
                            Pas de menu Plugins &gt; Plug-in (Marvelous 2024) ou pas de FLUX Bridge dedans : colle cette ligne dans Script &gt; Python (Plugins &gt; Python Editor en 2024.1+) puis Run.
                          </span>
                          {/* No " and no \ : the Marvelous 2024 editor mangles them (SyntaxError). */}
                          <CopyBlock text={`exec(open('${marvelousScript.replace(/\\/g, '/')}').read())`} />
                        </>
                      : <span style={{ fontSize: 10, color: 'var(--ink-4)' }}>Script absent : bouton Plug de Marvelous dans la sidebar pour l'écrire.</span>}
                  </div>
                )}
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

          {/* PRESETS — one click = the USD department to publish (task + format), asset
              and shot alike (2026-09-26: the shot anim uses the same anim preset). */}
          {(dcc === 'Maya' || dcc === 'Houdini') && ['.usd', '.usda', '.usdc'].includes(exportExt) && (
            <div style={{ padding: '16px 20px 0', flexShrink: 0 }}>
              <SecTitle>PRESETS USD</SecTitle>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {presetEntries(mode === 'asset' ? usdDepartments : usdShotDepartments).map(([task, info]) => (
                  <Pill key={task}
                    active={usdLayers && (mode === 'asset' ? sel.task : formatToken(sel.name)) === task
                      && ['.usd', '.usda', '.usdc'].includes(exportExt)}
                    style={{ cursor: 'pointer' }}>
                    <span title={info.what}
                      onClick={() => {
                        handleSelect(mode === 'asset' ? 'task' : 'name', task)
                        setExportExt('.usd'); setFluxWriter(null)
                      }}>
                      {info.label ?? info.department}
                    </span>
                  </Pill>
                ))}
                {/* custom: the DCC writes the file with every one of its USD options. */}
                <Pill active={!usdLayers && ['.usd', '.usda', '.usdc'].includes(exportExt)} style={{ cursor: 'pointer' }}>
                  <span title={`${dcc} écrit le fichier avec toutes ses options d'export USD (animation comprise)`}
                    onClick={() => { setExportExt('.usd'); setFluxWriter(false) }}>
                    custom
                  </span>
                </Pill>
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

          {/* ANIMATION (one animated file: abc / USD) or SÉQUENCE (one file per frame, $F4) */}
          {(animCapable || seqCapable) && (() => {
            const on = animCapable ? animRange : isSequence
            const toggle = () => (animCapable ? setAnimRange(v => !v) : setIsSequence(v => !v))
            const fields: [string, number, (n: number) => void][] = [
              ['Start', frameStart, setFrameStart], ['End', frameEnd, setFrameEnd],
            ]
            // Light USD export samples every frame (no step on that path).
            if (!(animCapable && usdLayers)) fields.push(['Step', frameStep, setFrameStep])
            return (
              <div style={{ padding: '0 20px 12px', flexShrink: 0 }}>
                <SecTitle>{animCapable ? 'ANIMATION' : 'SÉQUENCE'}</SecTitle>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: on ? 10 : 0 }}>
                  <div onClick={toggle} style={{
                    width: 32, height: 18, borderRadius: 9, cursor: 'pointer', flexShrink: 0,
                    background: on ? 'var(--accent)' : 'var(--rule-2)',
                    position: 'relative', transition: 'background 0.15s',
                  }}>
                    <div style={{
                      position: 'absolute', top: 2, left: on ? 16 : 2,
                      width: 14, height: 14, borderRadius: '50%', background: 'white',
                      transition: 'left 0.15s', boxShadow: '0 1px 3px rgba(0,0,0,.3)',
                    }} />
                  </div>
                  <div style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--ink-3)' }}>
                    {animCapable
                      ? (on ? 'Plage animée · un seul fichier' : (usdLayers ? 'Plage de lecture du DCC' : 'Image courante'))
                      : (on ? 'Activé · dossier versionné + $F4' : 'Désactivé · fichier unique LAST')}
                  </div>
                </div>
                {on && (
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    {fields.map(([lbl, val, set]) => (
                      <div key={lbl} style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                        <div style={{ fontSize: 9, color: 'var(--ink-4)', fontFamily: 'var(--mono)', textTransform: 'uppercase' }}>{lbl}</div>
                        <input type="number" value={val} onChange={e => { set(Number(e.target.value)); setRangeInfo('') }} style={{
                          width: 56, height: 26, background: 'var(--bg-deep)', border: '1px solid var(--rule-2)',
                          borderRadius: 5, padding: '0 6px', fontFamily: 'var(--mono)', fontSize: 11,
                          color: 'var(--ink)', boxShadow: 'var(--shadow-inset)', outline: 'none',
                        }} />
                      </div>
                    ))}
                    {animCapable && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 0 }}>
                        <div style={{ fontSize: 9, color: 'var(--ink-4)', fontFamily: 'var(--mono)' }}>&nbsp;</div>
                        <Btn ghost style={{ height: 26, gap: 5 }} onClick={() => { void fetchAnimRange() }}>
                          <RefreshCw size={11} strokeWidth={2} />
                          Clés
                        </Btn>
                      </div>
                    )}
                  </div>
                )}
                {on && animCapable && rangeInfo && (
                  <div style={{ fontSize: 10, color: 'var(--ink-4)', fontFamily: 'var(--mono)', marginTop: 6 }}>{rangeInfo}</div>
                )}
              </div>
            )
          })()}

          {/* INSTANCES — Maya shot animation (U2): tick the character instances to publish */}
          {instancePicker && (() => {
            const charName = shotCharName
            return (
              <div style={{ padding: '0 20px 12px', flexShrink: 0 }}>
                <SecTitle>INSTANCES</SecTitle>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: charInstances.length ? 8 : 0 }}>
                  <Btn ghost disabled={charLoading} style={{ height: 26, gap: 5, flexShrink: 0 }} onClick={() => { void loadInstances(false) }}>
                    <RefreshCw size={11} strokeWidth={2} />
                    {charLoading ? 'Lecture…' : `Relire ${charName}`}
                  </Btn>
                  <div style={{ fontSize: 10, color: 'var(--ink-4)', fontFamily: 'var(--mono)', minWidth: 0 }}>
                    {charInstances.length
                      ? `${charChecked.size} / ${charInstances.length} coché(s) · une anim par instance`
                      : 'Sans liste : une seule anim (scope ci-dessous)'}
                  </div>
                </div>
                {charInstances.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {charInstances.map(it => {
                      const on = charChecked.has(it.node)
                      const tag = `${charName}_${String(it.instance).padStart(2, '0')}`
                      return (
                        <div key={it.node} title={it.node}
                          onClick={() => setCharChecked(prev => {
                            const next = new Set(prev)
                            if (next.has(it.node)) next.delete(it.node); else next.add(it.node)
                            return next
                          })}
                          style={{
                            padding: '5px 10px', borderRadius: 6, cursor: 'pointer', maxWidth: '100%',
                            fontFamily: 'var(--mono)', fontSize: 11, fontWeight: on ? 600 : 400,
                            border: on ? '1px solid var(--accent)' : '1px solid var(--rule-2)',
                            background: on ? 'var(--accent-soft)' : 'var(--paper-2)',
                            color: on ? 'var(--accent-hi)' : 'var(--ink-3)',
                            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                          }}>
                          {tag} · {it.label}
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })()}

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

          {/* OPTIONS du preset USD — Maya, FLUX writes: only what makes sense for it (ADR 0034). */}
          {dcc === 'Maya' && usdPreset && USD_PRESET_SCHEMAS[usdPreset].length > 0 && (
            <div style={{ padding: '0 20px 12px', flexShrink: 0 }}>
              <SecTitle>OPTIONS {usdPreset.toUpperCase()}</SecTitle>
              <ExportOptions
                schema={USD_PRESET_SCHEMAS[usdPreset]}
                values={usdPresetOpts[usdPreset]}
                onChange={(k, v) => setUsdPresetOpts(prev => ({ ...prev, [usdPreset]: { ...prev[usdPreset], [k]: v } }))}
              />
            </div>
          )}

          {/* À EXPORTER + ATTRIBUTS — Maya, FLUX writes: listing and attribute renamer. */}
          {dcc === 'Maya' && usdPreset && (
            <UsdPresetPanel
              preset={usdPreset}
              preview={usdPreview}
              busy={usdPreviewBusy}
              error={usdPreviewErr}
              connected={mayaConnected}
              opts={usdPresetOpts[usdPreset]}
              onRefresh={() => { void fetchUsdPreview() }}
              onRenames={renames => setUsdPresetOpts(prev => ({ ...prev, [usdPreset]: { ...prev[usdPreset], renames } }))}
            />
          )}

          {/* OPTIONS D'EXPORT — Maya, per-format (the DCC writes the file: custom). */}
          {dcc === 'Maya' && !usdPreset && schemaForExt(exportExt).length > 0 && (
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

          {/* OPTIONS D'EXPORT — Nuke, per-format (Write node knobs + colorspace). */}
          {dcc === 'Nuke' && nukeSchemaForExt(exportExt).length > 0 && (
            <div style={{ padding: '0 20px 12px', flexShrink: 0 }}>
              <SecTitle>OPTIONS D'EXPORT <span style={{ fontFamily: 'var(--mono)', textTransform: 'none', color: 'var(--ink-4)' }}>{exportExt}</span></SecTitle>
              <ExportOptions
                schema={nukeSchemaForExt(exportExt)}
                values={nukeExportOpts}
                onChange={(k, v) => setNukeExportOpts(prev => ({ ...prev, [k]: v }))}
              />
            </div>
          )}

          {/* OPTIONS D'EXPORT — Photoshop, per-format (COM save-option fields). */}
          {dcc === 'Photoshop' && photoshopSchemaForExt(exportExt).length > 0 && (
            <div style={{ padding: '0 20px 12px', flexShrink: 0 }}>
              <SecTitle>OPTIONS D'EXPORT <span style={{ fontFamily: 'var(--mono)', textTransform: 'none', color: 'var(--ink-4)' }}>{exportExt}</span></SecTitle>
              <ExportOptions
                schema={photoshopSchemaForExt(exportExt)}
                values={psExportOpts}
                onChange={(k, v) => setPsExportOpts(prev => ({ ...prev, [k]: v }))}
              />
            </div>
          )}

          {/* TEXTURE SETS (Painter) / CHANNELS (Mari): read from the app, ticked ones export. */}
          {(dcc === 'Painter' || dcc === 'Mari') && (
            <div style={{ padding: '0 20px 12px', flexShrink: 0 }}>
              <SecTitle>{dcc === 'Painter' ? 'TEXTURE SETS' : 'CHANNELS'} <span style={{ fontFamily: 'var(--mono)', textTransform: 'none', color: 'var(--ink-4)' }}>{texSource}</span></SecTitle>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: texItems.length ? 8 : 0 }}>
                <Btn ghost disabled={texLoading} style={{ height: 26, gap: 5, flexShrink: 0 }} onClick={() => { void loadTexItems() }}>
                  <RefreshCw size={11} strokeWidth={2} />
                  {texLoading ? 'Lecture…' : 'Relire'}
                </Btn>
                {dcc === 'Painter' && texItems.length > 0 && (
                  <>
                    <Btn ghost style={{ height: 26 }} onClick={() => setTexChecked(new Set(texItems.map(t => t.name)))}>Tout</Btn>
                    <Btn ghost style={{ height: 26 }} onClick={() => setTexChecked(new Set())}>Aucun</Btn>
                    <span style={{ fontSize: 10, color: 'var(--ink-3)', fontFamily: 'var(--mono)' }}>{texChecked.size} / {texItems.length}</span>
                  </>
                )}
              </div>
              {dcc === 'Mari' && texItems.length > 0 && (
                <TextureMapTable
                  rows={texItems.map(t => ({ id: t.name, label: t.name, detail: t.detail }))}
                  checked={texChecked}
                  setChecked={fn => setTexChecked(prev => fn(prev))}
                  opts={chanOpts}
                  setOpts={fn => setChanOpts(prev => fn(prev))}
                  defaultFormat={exportExt.replace('.', '')}
                  sizeDefaultLabel="Taille Mari"
                />
              )}
              {dcc === 'Painter' && texItems.length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {texItems.map(t => {
                    const on = texChecked.has(t.name)
                    return (
                      <div key={t.name} title={t.detail}
                        onClick={() => setTexChecked(prev => { const n = new Set(prev); if (n.has(t.name)) n.delete(t.name); else n.add(t.name); return n })}
                        style={{
                          padding: '5px 10px', borderRadius: 6, cursor: 'pointer', maxWidth: '100%',
                          fontFamily: 'var(--mono)', fontSize: 11, fontWeight: on ? 600 : 400,
                          border: on ? '1px solid var(--accent)' : '1px solid var(--rule-2)',
                          background: on ? 'var(--accent-soft)' : 'var(--paper-2)',
                          color: on ? 'var(--accent-hi)' : 'var(--ink-3)',
                          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                        }}>
                        {t.name}{t.detail ? <span style={{ color: 'var(--ink-4)', fontWeight: 400 }}> · {t.detail}</span> : null}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )}

          {/* OPTIONS D'EXPORT — Painter (preset / bit depth / size / padding / conform .tx). */}
          {dcc === 'Painter' && (
            <div style={{ padding: '0 20px 12px', flexShrink: 0 }}>
              <SecTitle>OPTIONS D'EXPORT <span style={{ fontFamily: 'var(--mono)', textTransform: 'none', color: 'var(--ink-4)' }}>maps {exportExt}</span></SecTitle>
              {bundledPresets.length > 0 && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 11, color: 'var(--ink-3)', marginRight: 4 }} title="Enregistré dans le projet (project.json)">Presets du projet</span>
                  {bundledPresets.map(n => (
                    <Pill key={n} active={projectPresets.includes(n)} onClick={() => toggleProjectPreset(n)} style={{ cursor: 'pointer' }}>{n}</Pill>
                  ))}
                  {projectPresets.length === 0 && <span style={{ fontSize: 10, color: 'var(--ink-4)' }}>aucun : tous les presets de Painter</span>}
                </div>
              )}
              {missingPresets.length > 0 && (
                <div style={{ fontSize: 10, color: 'var(--warn)', marginBottom: 8 }}>
                  Preset du projet absent de Painter : {missingPresets.join(', ')}. Réinstalle le bridge Painter
                  (bouton Plug) puis relance Painter.
                </div>
              )}
              {offeredPresets.length > 0 && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <span style={{ fontSize: 11, color: 'var(--ink-3)', whiteSpace: 'nowrap' }}>Export preset</span>
                  <div style={{ flex: 1, minWidth: 0, display: 'flex', justifyContent: 'flex-end' }}>
                    <Select value={curPreset ? (curPreset.url || curPreset.name) : undefined}
                      onValueChange={v => setPainterOpts(prev => ({ ...prev, preset: v }))}>
                      <SelectTrigger style={{ height: 24, width: '100%', maxWidth: 260, fontSize: 10 }} />
                      <SelectContent>
                        {offeredPresets.map(p => <SelectItem key={p.url || p.name} value={p.url || p.name}>{p.name}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              )}
              <ExportOptions
                schema={offeredPresets.length > 0 ? PAINTER_OPTIONS.filter(o => o.key !== 'preset') : PAINTER_OPTIONS}
                values={painterOpts}
                onChange={(k, v) => setPainterOpts(prev => ({ ...prev, [k]: v }))}
              />
            </div>
          )}

          {/* MAPS (Painter): the preset's maps, then the shader channels that can be added
              on top of it, each with its own format / bit depth / size (same table as Mari). */}
          {dcc === 'Painter' && mapRows.length > 0 && (
            <div style={{ padding: '0 20px 12px', flexShrink: 0 }}>
              <SecTitle>MAPS <span style={{ fontFamily: 'var(--mono)', textTransform: 'none', color: 'var(--ink-4)' }}>{curPreset?.name}{channelRows.length ? ` + ${channelRows.length} canal(aux) ajoutable(s)` : ''}</span></SecTitle>
              <TextureMapTable
                rows={mapRows}
                checked={mapChecked}
                setChecked={fn => setMapChecked(prev => fn(prev))}
                opts={mapOpts}
                setOpts={fn => setMapOpts(prev => fn(prev))}
                defaultFormat={exportExt.replace('.', '')}
                sizeDefaultLabel="Taille du set"
              />
            </div>
          )}

          {/* OPTIONS D'EXPORT — Mari (conform .tx). */}
          {dcc === 'Mari' && (
            <div style={{ padding: '0 20px 12px', flexShrink: 0 }}>
              <SecTitle>OPTIONS D'EXPORT <span style={{ fontFamily: 'var(--mono)', textTransform: 'none', color: 'var(--ink-4)' }}>channels {exportExt}</span></SecTitle>
              <ExportOptions
                schema={MARI_OPTIONS}
                values={mariOpts}
                onChange={(k, v) => setMariOpts(prev => ({ ...prev, [k]: v }))}
              />
            </div>
          )}

          {/* GRAPHS (Designer) / PROJET (Marvelous): read from the app through the bridge. */}
          {(dcc === 'Designer' || dcc === 'Marvelous') && (
            <div style={{ padding: '0 20px 12px', flexShrink: 0 }}>
              <SecTitle>{dcc === 'Designer' ? 'GRAPHS' : 'PROJET'} <span style={{ fontFamily: 'var(--mono)', textTransform: 'none', color: 'var(--ink-4)' }}>{bridgeInfoSource}</span></SecTitle>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
                <Btn ghost disabled={texLoading} style={{ height: 26, gap: 5, flexShrink: 0 }} onClick={() => { void loadBridgeInfo() }}>
                  <RefreshCw size={11} strokeWidth={2} />
                  {texLoading ? 'Lecture…' : 'Relire'}
                </Btn>
                {dcc === 'Designer' && designerGraphs.length > 0 && (
                  <>
                    <Btn ghost style={{ height: 26 }} onClick={() => setGraphChecked(new Set(designerGraphs.map(g => g.key)))}>Tout</Btn>
                    <Btn ghost style={{ height: 26 }} onClick={() => setGraphChecked(new Set())}>Aucun</Btn>
                    <span style={{ fontSize: 10, color: 'var(--ink-3)', fontFamily: 'var(--mono)' }}>{graphChecked.size} / {designerGraphs.length}</span>
                  </>
                )}
                {dcc === 'Marvelous' && marvelousFormats.length > 0 && (
                  <span style={{ fontSize: 10, color: 'var(--ink-3)', fontFamily: 'var(--mono)' }}>
                    exports : {marvelousFormats.map(f => `.${f}`).join(' ')}
                  </span>
                )}
              </div>
              {dcc === 'Marvelous' && marvelousFormats.length > 0 && !marvelousFormats.includes(exportExt.replace('.', '').replace(/^usd[ac]$/, 'usd')) && (
                <div style={{ fontSize: 10, color: 'var(--warn, #e8912a)', fontFamily: 'var(--mono)', marginBottom: 8 }}>
                  {exportExt} absent de ce Marvelous : choisis un autre format
                </div>
              )}
              {dcc === 'Designer' && designerGraphs.length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {designerGraphs.map(g => {
                    const on = graphChecked.has(g.key)
                    return (
                      <div key={g.key} title={g.pkg.path}
                        onClick={() => setGraphChecked(prev => { const n = new Set(prev); if (n.has(g.key)) n.delete(g.key); else n.add(g.key); return n })}
                        style={{
                          padding: '5px 10px', borderRadius: 6, cursor: 'pointer', maxWidth: '100%',
                          fontFamily: 'var(--mono)', fontSize: 11, fontWeight: on ? 600 : 400,
                          border: on ? '1px solid var(--accent)' : '1px solid var(--rule-2)',
                          background: on ? 'var(--accent-soft)' : 'var(--paper-2)',
                          color: on ? 'var(--accent-hi)' : 'var(--ink-3)',
                          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                        }}>
                        {g.graph.id}
                        <span style={{ color: 'var(--ink-4)', fontWeight: 400 }}> · {g.pkg.name} · {g.graph.outputs.length} out{g.graph.current ? ' · ouvert' : ''}</span>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )}

          {/* OUTPUTS (Designer): the output nodes of each ticked graph, the ticked ones export. */}
          {dcc === 'Designer' && !!designerOpts.maps && designerGraphs.some(g => graphChecked.has(g.key) && g.graph.outputs.length > 0) && (
            <div style={{ padding: '0 20px 12px', flexShrink: 0 }}>
              <SecTitle>OUTPUTS</SecTitle>
              {designerGraphs.filter(g => graphChecked.has(g.key)).map(g => {
                const keys = g.graph.outputs.map(o => outputKey(g.key, o.id))
                const nOn = keys.filter(k => outputChecked.has(k)).length
                return (
                  <div key={g.key} style={{ marginBottom: 8 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
                      <span style={{ fontSize: 11, color: 'var(--ink-2)', fontFamily: 'var(--mono)' }}>{g.graph.id}</span>
                      <Btn ghost style={{ height: 22 }} onClick={() => setOutputChecked(prev => new Set([...prev, ...keys]))}>Tout</Btn>
                      <Btn ghost style={{ height: 22 }} onClick={() => setOutputChecked(prev => new Set([...prev].filter(k => !keys.includes(k))))}>Aucun</Btn>
                      <span style={{ fontSize: 10, color: 'var(--ink-3)', fontFamily: 'var(--mono)' }}>{nOn} / {keys.length}</span>
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                      {g.graph.outputs.map(o => {
                        const k = outputKey(g.key, o.id)
                        const on = outputChecked.has(k)
                        return (
                          <div key={k} title={o.id}
                            onClick={() => setOutputChecked(prev => { const n = new Set(prev); if (n.has(k)) n.delete(k); else n.add(k); return n })}
                            style={{
                              padding: '4px 10px', borderRadius: 6, cursor: 'pointer',
                              fontFamily: 'var(--mono)', fontSize: 11, fontWeight: on ? 600 : 400,
                              border: on ? '1px solid var(--accent)' : '1px solid var(--rule-2)',
                              background: on ? 'var(--accent-soft)' : 'var(--paper-2)',
                              color: on ? 'var(--accent-hi)' : 'var(--ink-3)',
                            }}>
                            {o.label}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )
              })}
            </div>
          )}

          {/* OPTIONS D'EXPORT — Designer (maps / .sbsar / .sbs, taille, bit depth, .tx). */}
          {dcc === 'Designer' && (
            <div style={{ padding: '0 20px 12px', flexShrink: 0 }}>
              <SecTitle>OPTIONS D'EXPORT <span style={{ fontFamily: 'var(--mono)', textTransform: 'none', color: 'var(--ink-4)' }}>maps {exportExt}</span></SecTitle>
              <ExportOptions
                schema={DESIGNER_OPTIONS}
                values={designerOpts}
                onChange={(k, v) => setDesignerOpts(prev => ({ ...prev, [k]: v }))}
              />
            </div>
          )}

          {/* OPTIONS D'EXPORT — Marvelous (contenu, epaisseur, UV, echelle, .zprj). */}
          {dcc === 'Marvelous' && (
            <div style={{ padding: '0 20px 12px', flexShrink: 0 }}>
              <SecTitle>OPTIONS D'EXPORT <span style={{ fontFamily: 'var(--mono)', textTransform: 'none', color: 'var(--ink-4)' }}>{exportExt}</span></SecTitle>
              {exportExt === '.zprj'
                ? <div style={{ fontSize: 10, color: 'var(--ink-4)', fontFamily: 'var(--mono)' }}>Le projet Marvelous est publié tel quel (aucune option).</div>
                : <ExportOptions
                    schema={MARVELOUS_OPTIONS}
                    values={marvelousOpts}
                    onChange={(k, v) => setMarvelousOpts(prev => ({ ...prev, [k]: v }))}
                  />}
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

          {/* USD — Maya & Houdini, asset + USD formats only (hidden otherwise). The TASK
              decides what is exported (ADR 0019); the switch only says who writes it. */}
          {(dcc === 'Maya' || dcc === 'Houdini') && ['.usd', '.usda', '.usdc'].includes(exportExt) && (() => {
            const contribution = usdContribution
            const usdOk = !!contribution
            const on = usdLayers
            return (
              <div style={{ padding: '0 20px 12px', flexShrink: 0 }}>
                <SecTitle>USD</SecTitle>
                <div
                  onClick={() => { if (usdOk) setFluxWriter(!on) }}
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
                    {on ? 'Écrit par FLUX (layers USD)' : `Écrit par ${dcc}`}
                  </span>
                </div>
                <div className="lbl" style={{ fontSize: 9.5, color: 'var(--ink-4)', marginTop: 6, lineHeight: 1.5 }}>
                  {usdOk && mode === 'shot' ? (<>
                    TASK {formatToken(sel.name)} du plan : {contribution.what}, avec la plage d'images et les fps.
                    Le 4e token est le perso animé (<span style={{ fontFamily: 'var(--mono)' }}>SEQ_SHOT_ANIM_NAME</span>) ;
                    sélectionne son rig dans {dcc}.
                    {on
                      ? " FLUX écrit /NAME/skel/Anim seul : le squelette et la géo viennent de l'asset."
                      : ` ${dcc} écrit le fichier tel quel (structure non garantie).`}
                  </>) : usdOk ? (<>
                    TASK {sel.task} : département <span style={{ fontFamily: 'var(--mono)' }}>{contribution.department}</span> de
                    l'asset, {contribution.what}. La task décide de ce qui est exporté.
                    {on
                      ? (contribution.writer === 'look'
                        ? ` FLUX lit les matériaux de ${dcc === 'Houdini' ? 'Solaris (LOP affiché ou chemin du node)' : 'la scène'} et écrit /NAME/mtl + les assignations sur /NAME/geo/render (textures .tx si converties).`
                        : usdPreset === 'model'
                          ? ' FLUX écrit la géo seule sous /NAME/geo/render (+ proxy auto) ; skeleton et poids viennent du rig.'
                          : usdPreset === 'rig'
                            ? ' FLUX écrit /NAME/skel/Skeleton en rest pose et pose les poids de skin sur /NAME/geo/render du GEO publié (boneCapture dans Houdini).'
                            : usdPreset === 'anim'
                              ? ' FLUX écrit /NAME/skel/Anim : les rotations des joints qui bougent, sans altérer la courbe.'
                              : " FLUX extrait la scène et écrit /NAME/geo/render, /NAME/skel (structure du pipe).")
                      : ` ${dcc} écrit le fichier tel quel (matériaux, blend shapes… mais structure non garantie).`}
                  </>) : (
                    mode === 'shot'
                      ? `TASK ${formatToken(sel.name) || '—'} : FLUX n'écrit que l'ANIM d'un plan. ${dcc} écrit le fichier.`
                      : `TASK ${sel.task || '—'} : pas de département USD (GEO, SHADING, RIG ou ANIM). ${dcc} écrit le fichier.`
                  )}
                </div>
              </div>
            )
          })()}

          {/* APERÇU OUTPUT */}
          <div style={{ padding: '0 20px 16px', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <SecTitle>APERÇU OUTPUT</SecTitle>
            <div className="subcard" style={{ padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 4, minHeight: 90, maxHeight: 200, overflowY: 'auto' }}>
              {(seqCapable && isSequence) ? (<>
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
                <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--rule)', fontSize: 9, fontFamily: 'var(--mono)', color: zbrushConnected ? 'var(--ok)' : zbrushChecking ? 'var(--ink-4)' : 'var(--err)' }}>
                  {zbrushConnected
                    ? `● ZBrush connecté${zbrushVersion ? ` · ${zbrushVersion}` : ''}`
                    : `${zbrushChecking ? '…' : '✕'} ${zbrushStatusText(zbrushConnected, zbrushChecking, zbrushPluginInstalled, zbrushVersion)}`}
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
        <Btn primary onClick={() => void requestPublish()}>
          {publishing ? 'Publication…' : 'Publish →'}
        </Btn>
      </div>

      {/* Instance picker: several Maya / Houdini are open */}
      {instancePick && (
        <div onClick={() => setInstancePick(null)} style={{
          position: 'fixed', inset: 0, zIndex: 80, background: 'rgba(0,0,0,0.45)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16,
        }}>
          <div className="card" onClick={e => e.stopPropagation()} style={{
            width: 440, maxWidth: '100%', padding: 16, display: 'flex', flexDirection: 'column', gap: 10,
            background: 'var(--paper-2)', boxShadow: 'var(--shadow-md)',
          }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>
              Publier depuis quel {instancePick.dcc} ?
            </div>
            <div style={{ fontSize: 11, color: 'var(--ink-3)' }}>
              {instancePick.items.length} instances ouvertes. Le choix reste actif pour les prochains publishs.
            </div>
            {instancePick.items.map(it => {
              const active = readActiveInstancePort(instancePick.dcc) === it.port
              const scene = it.scene ? it.scene.replace(/\\/g, '/').split('/').pop() : 'Scène sans nom'
              return (
                <div key={it.port} onClick={() => publishOn(it.port)} title={it.scene ?? ''} style={{
                  padding: '9px 12px', borderRadius: 6, cursor: 'pointer', minWidth: 0,
                  border: '1px solid ' + (active ? 'var(--accent)' : 'var(--rule-2)'),
                  background: active ? 'var(--accent-soft)' : 'var(--paper)',
                  display: 'flex', alignItems: 'center', gap: 10,
                }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--ink)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{scene}</div>
                    <div style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--ink-3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      port {it.port}{it.scene ? ` · ${it.scene}` : ''}
                    </div>
                  </div>
                  {active && <span style={{ fontSize: 10, color: 'var(--accent-hi)', flexShrink: 0 }}>actif</span>}
                </div>
              )
            })}
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <Btn ghost onClick={() => setInstancePick(null)}>Annuler</Btn>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── USD preset: what will be exported + attribute renamer (2026-09-26) ────────

function countJoints(node: MayaUsdTreeNode): number {
  return (node.type === 'joint' ? 1 : 0) + node.children.reduce((n, c) => n + countJoints(c), 0)
}

// One row of the rig tree, outliner-like: groups open, joints fold.
function PresetTreeNode({ node, depth }: { node: MayaUsdTreeNode; depth: number }) {
  const [open, setOpen] = useState(node.type === 'group')
  const has = node.children.length > 0
  return (
    <div>
      <div
        title={node.path}
        onClick={() => { if (has) setOpen(o => !o) }}
        style={{
          display: 'flex', alignItems: 'center', gap: 4, paddingLeft: depth * 12, minWidth: 0,
          cursor: has ? 'pointer' : 'default', lineHeight: '18px',
          fontFamily: 'var(--mono)', fontSize: 10,
          color: node.type === 'joint' ? 'var(--ink-2)' : 'var(--ink-3)',
        }}
      >
        {has
          ? (open ? <ChevronDown size={11} strokeWidth={2} /> : <ChevronRight size={11} strokeWidth={2} />)
          : <span style={{ width: 11, flexShrink: 0 }} />}
        <span style={{
          fontSize: 8, padding: '0 4px', borderRadius: 3, flexShrink: 0,
          background: node.type === 'joint' ? 'var(--accent-soft)' : 'var(--paper-2)',
          color: node.type === 'joint' ? 'var(--accent-hi)' : 'var(--ink-4)',
        }}>{node.type === 'joint' ? 'jnt' : 'grp'}</span>
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{node.name}</span>
        {has && !open && <span style={{ color: 'var(--ink-4)', flexShrink: 0 }}>({countJoints(node)})</span>}
      </div>
      {open && node.children.map(c => <PresetTreeNode key={c.path} node={c} depth={depth + 1} />)}
    </div>
  )
}

function UsdPresetPanel({ preset, preview, busy, error, connected, opts, onRefresh, onRenames }: {
  preset: UsdPreset
  preview: MayaUsdPreview | null
  busy: boolean
  error: string
  connected: boolean
  opts: Record<string, unknown>
  onRefresh: () => void
  onRenames: (renames: Record<string, string>) => void
}) {
  const renames = (opts.renames as Record<string, string> | undefined) ?? {}
  const items = preview?.items ?? []
  const colorSets = preset === 'model'
    ? Array.from(new Set(items.flatMap(i => i.color_sets ?? []))) : []
  const attrs = exportedAttrs(preset, opts, colorSets)
  const renamable = attrs.filter(a => a.rename)

  let summary = connected ? '' : 'Maya non connecté'
  if (preview) {
    if (preset === 'model') summary = items.length ? `${items.length} géo(s)` : "aucune géo : l'export échouera"
    else if (preset === 'rig') {
      summary = preview.joints
        ? `${preview.joints} joints · ${preview.roots?.length ?? 0} squelette(s) · ${preview.skinned?.length ?? 0} mesh(es) skinné(s)`
        : "aucun joint : l'export échouera"
    } else if (preset === 'anim') {
      summary = items.length
        ? `${items.length} joint(s) animé(s) sur ${preview.joints ?? 0}`
        : 'aucun joint ne bouge sur la plage'
    } else summary = items.length ? `${items.length} matériau(x)` : 'aucun matériau sur la géo'
  }

  const row: React.CSSProperties = {
    display: 'flex', alignItems: 'center', gap: 8, minWidth: 0, lineHeight: '18px',
    fontFamily: 'var(--mono)', fontSize: 10,
  }
  const dim: React.CSSProperties = { color: 'var(--ink-4)', flexShrink: 0 }
  const name: React.CSSProperties = {
    color: 'var(--ink-2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, minWidth: 0,
  }

  return (<>
    <div style={{ padding: '0 20px 12px', flexShrink: 0 }}>
      <SecTitle>À EXPORTER</SecTitle>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, minWidth: 0 }}>
        <Btn ghost disabled={busy || !connected} style={{ height: 26, gap: 5, flexShrink: 0 }} onClick={onRefresh}>
          <RefreshCw size={11} strokeWidth={2} />
          {busy ? 'Lecture…' : 'Relire la scène'}
        </Btn>
        <div style={{ fontSize: 10, color: 'var(--ink-4)', fontFamily: 'var(--mono)', minWidth: 0,
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{summary}</div>
      </div>
      {error && <div style={{ fontSize: 10, color: 'var(--err)', marginBottom: 6 }}>{error}</div>}
      {preview && (items.length > 0 || (preview.tree?.length ?? 0) > 0) && (
        <div className="subcard" style={{ padding: '6px 10px', maxHeight: 240, overflowY: 'auto' }}>
          {preset === 'model' && items.map(i => (
            <div key={i.path ?? i.name} style={row} title={i.path}>
              <span style={name}>{i.name}</span>
              <span style={dim}>{i.points} pts · {i.faces} f</span>
              <span style={{ ...dim, color: i.uv ? 'var(--ink-4)' : 'var(--warn, var(--err))' }}>{i.uv ? 'UV' : 'sans UV'}</span>
              {i.skinned && <span style={dim} title="Les poids de skin se publient avec le preset rig">skin → rig</span>}
            </div>
          ))}
          {preset === 'anim' && items.map(i => (
            <div key={i.token ?? i.name} style={row} title={i.token}>
              <span style={name}>{i.name}</span>
              <span style={dim}>{(i.channels ?? []).join(' + ')}</span>
            </div>
          ))}
          {preset === 'look' && items.map(i => (
            <div key={i.name} style={row}>
              <span style={name}>{i.name}</span>
              <span style={dim}>{i.type}</span>
              <span style={dim}>{i.meshes} géo(s)</span>
            </div>
          ))}
          {preset === 'rig' && (<>
            {(preview.tree ?? []).map(n => <PresetTreeNode key={n.path} node={n} depth={0} />)}
            {(preview.skinned?.length ?? 0) > 0 && (
              <div style={{ marginTop: 6, paddingTop: 6, borderTop: '1px solid var(--rule)' }}>
                {preview.skinned!.map(m => (
                  <div key={m.name} style={row}>
                    <span style={name}>{m.name}</span>
                    <span style={dim}>skin · {m.joints} influences</span>
                  </div>
                ))}
              </div>
            )}
          </>)}
        </div>
      )}
      {preset === 'anim' && preview && (
        <div className="lbl" style={{ fontSize: 9, color: 'var(--ink-4)', marginTop: 4 }}>
          Aperçu sur {preview.sampled ?? 0} images ; l'export lit chaque image.
        </div>
      )}
    </div>

    <div style={{ padding: '0 20px 12px', flexShrink: 0 }}>
      <SecTitle>ATTRIBUTS EXPORTÉS</SecTitle>
      {renamable.length > 0 && (
        <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
          <Btn ghost sm onClick={() => {
            const next = { ...renames }
            renamable.forEach(a => { if (a.houdiniName) next[a.key ?? a.usd] = a.houdiniName })
            onRenames(next)
          }}>Nomenclature Houdini</Btn>
          <Btn ghost sm onClick={() => onRenames({})}>Noms USD</Btn>
        </div>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.2fr) minmax(0, 1fr) minmax(0, 1fr)', gap: '4px 8px', alignItems: 'center' }}>
        <span className="cap" style={{ fontSize: 9 }}>USD</span>
        <span className="cap" style={{ fontSize: 9 }}>Nom exporté</span>
        <span className="cap" style={{ fontSize: 9 }}>Dans Houdini</span>
        {attrs.map(a => {
          const key = a.key ?? a.usd
          const value = renames[key] ?? ''
          return (
            <div key={a.usd} style={{ display: 'contents' }}>
              <span title={a.what} style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)',
                                            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.usd}</span>
              {a.rename ? (
                <input
                  value={value}
                  placeholder={key}
                  onChange={e => onRenames({ ...renames, [key]: e.target.value.replace(/[^A-Za-z0-9_]/g, '') })}
                  style={{
                    height: 22, minWidth: 0, background: 'var(--bg-deep)', border: '1px solid var(--rule-2)',
                    borderRadius: 5, padding: '0 6px', fontFamily: 'var(--mono)', fontSize: 10,
                    color: 'var(--ink)', boxShadow: 'var(--shadow-inset)', outline: 'none',
                  }}
                />
              ) : (
                <span style={{ fontSize: 9, color: 'var(--ink-4)' }} title={a.what}>fixe</span>
              )}
              <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--accent-hi)',
                             overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {a.rename && value ? value : a.houdini}
              </span>
            </div>
          )
        })}
      </div>
      <div className="lbl" style={{ fontSize: 9, color: 'var(--ink-4)', marginTop: 6, lineHeight: 1.5 }}>
        {preset === 'rig'
          ? "Houdini reconstruit boneCapture à partir de skel:jointIndices / jointWeights et du Skeleton (USD Skin Import, UsdSkel Character Import) : ces noms restent fixes. Les poids se posent sur la géo du GEO publié (et sur son proxy)."
          : preset === 'model'
            ? "UV : st est le nom lu par les matériaux USD (UsdPreviewSurface) ; ne renomme en uv que pour un pipe 100 % Houdini. Un color set renommé Cd devient la couleur de point dans Houdini."
            : 'Attributs du schéma USD : noms fixes.'}
      </div>
    </div>
  </>)
}
