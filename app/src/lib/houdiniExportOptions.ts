// houdiniExportOptions.ts — per-format export option schema for Houdini.
//
// Flux exports via export_via_node(), which reuses a selected ROP or auto-creates
// the right one: rop_alembic for .abc, rop_geometry for geo/obj/vdb/usd. The
// options below are therefore ROP *parameters* — each key is the EXACT Houdini
// parm name, so the backend just does rop.parm(key).set(value) defensively (a
// parm absent on the running ROP/version is skipped, never fails the cook).
//
// Defaults match each ROP's own defaults, so an empty options dict cooks exactly
// like before this UI existed.
//
// NOTE: the rich USD LOP dialog (usdexport ROP) does not apply here — SOP-based
// USD export goes through rop_geometry, whose options are the geometry-ROP set
// below. Wiring full USD-LOP options would require exporting USD via a LOP
// usdexport ROP (a separate pipeline change).

import type { ExportOption } from './mayaExportOptions'

// Geometry ROP (rop_geometry / geometry) — used for bgeo/geo/obj/vdb/usd/usda/usdc.
// Real parm names/defaults/menus dumped from Houdini (the geometry ROP is thin; the
// output format is chosen by the file extension).
const GEO: ExportOption[] = [
  { key: 'mkpath',      label: 'Create intermediate dirs', type: 'bool', default: true,  tier: 'common' },
  { key: 'initsim',     label: 'Initialize simulation OPs', type: 'bool', default: false, tier: 'common' },
  { key: 'xformtype', label: 'Transform', type: 'enum', default: 'none', tier: 'advanced',
    choices: [{ value: 'none', label: 'None' }, { value: 'world', label: 'World' }] },
  { key: 'alfprogress', label: 'Alfred style progress',    type: 'bool', default: false, tier: 'advanced' },
  { key: 'savebackground', label: 'Save in background',    type: 'bool', default: true,  tier: 'advanced' },
]

// Alembic ROP (rop_alembic / alembic) — used for .abc. Full real parm set.
const ALEMBIC: ExportOption[] = [
  // common
  { key: 'format', label: 'Format', type: 'enum', default: 'default', tier: 'common',
    choices: [{ value: 'default', label: 'Default' }, { value: 'ogawa', label: 'Ogawa' }, { value: 'hdf5', label: 'HDF5' }] },
  { key: 'save_attributes', label: 'Save attributes',           type: 'bool', default: true,  tier: 'common' },
  { key: 'build_from_path', label: 'Build hierarchy from attribute', type: 'bool', default: false, tier: 'common' },
  { key: 'facesets', label: 'Face sets', type: 'enum', default: 'nonempty', tier: 'common',
    choices: [{ value: 'no', label: 'None' }, { value: 'nonempty', label: 'Non-empty' }, { value: 'all', label: 'All' }] },
  // advanced
  { key: 'use_instancing',     label: 'Use instancing',           type: 'bool', default: true,  tier: 'advanced' },
  { key: 'shape_nodes',        label: 'Create shape nodes',       type: 'bool', default: true,  tier: 'advanced' },
  { key: 'outputindexedarrays', label: 'Output indexed arrays',   type: 'bool', default: true,  tier: 'advanced' },
  { key: 'save_hidden',        label: 'Save hidden objects',      type: 'bool', default: true,  tier: 'advanced' },
  { key: 'full_bounds',        label: 'Full bounding box tree',   type: 'bool', default: false, tier: 'advanced' },
  { key: 'mkpath',             label: 'Create intermediate dirs', type: 'bool', default: true,  tier: 'advanced' },
  { key: 'packed_transform', label: 'Packed transform', type: 'enum', default: 'deform', tier: 'advanced',
    choices: [{ value: 'deform', label: 'Deform' }, { value: 'transform', label: 'Transform' }, { value: 'transformparent', label: 'Transform parent' }] },
  { key: 'collapse', label: 'Collapse objects', type: 'enum', default: 'off', tier: 'advanced',
    choices: [{ value: 'off', label: 'Off' }, { value: 'geo', label: 'Geo' }, { value: 'on', label: 'On' }] },
  { key: 'partition_mode', label: 'Partition mode', type: 'enum', default: 'no', tier: 'advanced',
    choices: [
      { value: 'no', label: 'No' }, { value: 'full', label: 'Full' }, { value: 'shape', label: 'Shape' },
      { value: 'xform', label: 'Xform' }, { value: 'xformshape', label: 'Xform+Shape' },
    ] },
  { key: 'motionBlur', label: 'Motion blur',       type: 'bool', default: false, tier: 'advanced' },
  // attribute patterns (native ABC filtering)
  { key: 'pointAttributes',     label: 'Point attributes',     type: 'string', default: '*', tier: 'advanced' },
  { key: 'vertexAttributes',    label: 'Vertex attributes',    type: 'string', default: '*', tier: 'advanced' },
  { key: 'primitiveAttributes', label: 'Primitive attributes', type: 'string', default: '*', tier: 'advanced' },
  { key: 'detailAttributes',    label: 'Detail attributes',    type: 'string', default: '*', tier: 'advanced' },
]

// Filmbox FBX ROP (filmboxfbx) — used for .fbx. Names/defaults/menu tokens are the
// real ones dumped from Houdini. Set defensively backend-side (skipped if absent),
// and defaults match the ROP's own defaults so nothing changes unless toggled.
const FBX: ExportOption[] = [
  // common
  { key: 'forceskindeform',  label: 'Skin weights / boneCapture (force skin deform)', type: 'bool', default: false, tier: 'common' },
  { key: 'forceblendshape',  label: 'Force blend shape export',   type: 'bool', default: false, tier: 'common' },
  { key: 'computesmoothinggroups', label: 'Compute smoothing groups', type: 'bool', default: false, tier: 'common' },
  { key: 'exportkind',       label: 'Export in ASCII format',     type: 'bool', default: true,  tier: 'common' },
  { key: 'vcformat', label: 'Vertex cache format', type: 'enum', default: 'mayaformat', tier: 'common',
    choices: [{ value: 'mayaformat', label: 'Maya' }, { value: 'maxformat', label: '3ds Max' }] },
  // advanced
  { key: 'convertsurfaces',  label: 'Convert NURBS/Bézier to polygons', type: 'bool', default: false, tier: 'advanced' },
  { key: 'deformsasvcs',     label: 'Export deforms as vertex caches',   type: 'bool', default: false, tier: 'advanced' },
  { key: 'exportclips',      label: 'Export animation clips',     type: 'bool', default: false, tier: 'advanced' },
  { key: 'exportendeffectors', label: 'Export end effectors',     type: 'bool', default: true,  tier: 'advanced' },
  { key: 'detectconstpointobjs', label: 'Detect constant point count', type: 'bool', default: true, tier: 'advanced' },
  { key: 'preserveshapenames', label: 'Preserve shape names',     type: 'bool', default: false, tier: 'advanced' },
  { key: 'createsubnetroot', label: 'Create root for subnet',     type: 'bool', default: true,  tier: 'advanced' },
  { key: 'buildfrompath',    label: 'Build hierarchy from path attribute', type: 'bool', default: false, tier: 'advanced' },
  { key: 'invisobj', label: 'Export invisible objects', type: 'enum', default: 'nullnodes', tier: 'advanced',
    choices: [
      { value: 'nullnodes', label: 'As nulls' }, { value: 'fullnodes', label: 'Full nodes' },
      { value: 'visiblenodes', label: 'Visible only' }, { value: 'nonodes', label: 'None' },
    ] },
  { key: 'convertunits',     label: 'Convert units',              type: 'bool', default: false, tier: 'advanced' },
  { key: 'convertaxis',      label: 'Convert to axis system',     type: 'bool', default: false, tier: 'advanced' },
  { key: 'conservemem',      label: 'Conserve memory',            type: 'bool', default: false, tier: 'advanced' },
  { key: 'embedmedia',       label: 'Embed media',                type: 'bool', default: false, tier: 'advanced' },
  { key: 'polylod',          label: 'Conversion level of detail', type: 'float', default: 1.0,  tier: 'advanced' },
]

export function houdiniSchemaForExt(ext: string): ExportOption[] {
  switch (ext.toLowerCase()) {
    case '.abc': return ALEMBIC
    case '.fbx': return FBX
    case '.bgeo':
    case '.bgeo.sc':
    case '.geo':
    case '.obj':
    case '.vdb':
    case '.usd':
    case '.usda':
    case '.usdc': return GEO
    default: return []   // .fbx / .exr / .hip — no ROP options exposed
  }
}
