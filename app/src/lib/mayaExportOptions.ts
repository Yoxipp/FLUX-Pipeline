// mayaExportOptions.ts — declarative per-format export option schema for Maya.
//
// The Publisher renders these generically (common toggles visible + an "Avancé"
// expander with the rest), and threads the chosen values to the backend, which
// maps each key onto the real Maya export command (cmds.file flags / FBXExport*
// MEL / OBJ options string / AbcExport -j flags / mayaUSDExport kwargs).
//
// Defaults are chosen to reproduce the pre-options export behaviour exactly, so
// enabling this UI never silently changes an existing publish.
//
// NOTE: only options that map to a real, scriptable Maya command are exposed.
// A few rows from Maya's native dialogs have no reliable MEL/Python equivalent
// (e.g. FBX "Remove single key", "Selection Sets") and are intentionally omitted
// rather than shown as dead controls.

export type ExportOptionType = 'bool' | 'enum' | 'int' | 'float' | 'string'

export interface ExportOption {
  key: string
  label: string
  type: ExportOptionType
  default: boolean | string | number
  tier: 'common' | 'advanced'
  choices?: { value: string; label: string }[]   // enum only
  dependsOn?: string                              // greyed out when this bool key is false
  hint?: string
}

// ── Maya scene (.ma / .mb) — cmds.file flags ──────────────────────────────────
const MAYA_SCENE: ExportOption[] = [
  { key: 'construction_history', label: 'Construction history', type: 'bool', default: true,  tier: 'common' },
  { key: 'preserve_references',  label: 'Preserve references',  type: 'bool', default: false, tier: 'common' },
  { key: 'channels',            label: 'Channels',              type: 'bool', default: true,  tier: 'common' },
  { key: 'shaders',             label: 'Shaders / materials',   type: 'bool', default: true,  tier: 'common' },
  { key: 'expressions',         label: 'Expressions',           type: 'bool', default: true,  tier: 'advanced' },
  { key: 'constraints',         label: 'Constraints',           type: 'bool', default: true,  tier: 'advanced' },
]

// ── FBX — FBXExport* MEL commands ─────────────────────────────────────────────
const FBX: ExportOption[] = [
  // common
  { key: 'smoothing_groups', label: 'Smoothing groups',       type: 'bool', default: true,  tier: 'common' },
  { key: 'smooth_mesh',      label: 'Smooth mesh',            type: 'bool', default: true,  tier: 'common' },
  { key: 'skins',            label: 'Skin weights (boneCapture)', type: 'bool', default: true,  tier: 'common' },
  { key: 'blend_shapes',     label: 'Blend shapes',           type: 'bool', default: true,  tier: 'common' },
  { key: 'bake_animation',   label: 'Bake animation',         type: 'bool', default: false, tier: 'common' },
  { key: 'bake_start',       label: 'Bake start',             type: 'int',  default: 1,     tier: 'common', dependsOn: 'bake_animation' },
  { key: 'bake_end',         label: 'Bake end',               type: 'int',  default: 100,   tier: 'common', dependsOn: 'bake_animation' },
  { key: 'bake_step',        label: 'Bake step',              type: 'int',  default: 1,     tier: 'common', dependsOn: 'bake_animation' },
  // advanced
  { key: 'split_vertex_normals', label: 'Split per-vertex normals', type: 'bool', default: false, tier: 'advanced' },
  { key: 'tangents',          label: 'Tangents & binormals',   type: 'bool', default: false, tier: 'advanced' },
  { key: 'triangulate',       label: 'Triangulate',            type: 'bool', default: false, tier: 'advanced' },
  { key: 'instances',         label: 'Preserve instances',     type: 'bool', default: false, tier: 'advanced' },
  { key: 'referenced_assets', label: 'Referenced assets content', type: 'bool', default: false, tier: 'advanced' },
  { key: 'constraints',       label: 'Constraints',            type: 'bool', default: false, tier: 'advanced' },
  { key: 'skeleton_definitions', label: 'Skeleton definitions', type: 'bool', default: false, tier: 'advanced' },
  { key: 'cameras',           label: 'Cameras',                type: 'bool', default: true,  tier: 'advanced' },
  { key: 'lights',            label: 'Lights',                 type: 'bool', default: true,  tier: 'advanced' },
  { key: 'embed_media',       label: 'Embed media',            type: 'bool', default: false, tier: 'advanced' },
  { key: 'input_connections', label: 'Input connections',      type: 'bool', default: true,  tier: 'advanced' },
  { key: 'include_children',  label: 'Include children',       type: 'bool', default: true,  tier: 'advanced' },
  { key: 'constant_key_reducer', label: 'Constant key reducer', type: 'bool', default: false, tier: 'advanced' },
  { key: 'resample_all',      label: 'Resample all',           type: 'bool', default: false, tier: 'advanced', dependsOn: 'bake_animation' },
  { key: 'use_scene_name',    label: 'Use scene name',         type: 'bool', default: false, tier: 'advanced' },
  { key: 'quaternion', label: 'Quaternion interpolation', type: 'enum', default: 'resample', tier: 'advanced',
    choices: [{ value: 'euler', label: 'Euler' }, { value: 'quaternion', label: 'Quaternion' }, { value: 'resample', label: 'Resample as Euler' }] },
  { key: 'up_axis', label: 'Up axis', type: 'enum', default: 'y', tier: 'advanced',
    choices: [{ value: 'y', label: 'Y' }, { value: 'z', label: 'Z' }] },
  { key: 'animation_only',  label: 'Animation only',      type: 'bool', default: false, tier: 'advanced' },
  { key: 'audio',           label: 'Audio',               type: 'bool', default: false, tier: 'advanced' },
  { key: 'cache_file',      label: 'Geometry cache file', type: 'bool', default: false, tier: 'advanced' },
  { key: 'shape_attributes', label: 'Shape attributes',   type: 'bool', default: false, tier: 'advanced' },
  { key: 'split_takes',     label: 'Split animation into takes', type: 'bool', default: false, tier: 'advanced' },
  { key: 'generate_log',    label: 'Generate log',        type: 'bool', default: false, tier: 'advanced' },
  { key: 'ascii', label: 'ASCII (vs binary)', type: 'bool', default: false, tier: 'advanced' },
  { key: 'file_version', label: 'FBX version', type: 'enum', default: 'FBX202000', tier: 'advanced',
    choices: [
      { value: 'FBX202000', label: '2020' }, { value: 'FBX201900', label: '2019' },
      { value: 'FBX201800', label: '2018' }, { value: 'FBX201600', label: '2016' },
    ] },
]

// ── OBJ — cmds.file options string ────────────────────────────────────────────
const OBJ: ExportOption[] = [
  { key: 'materials', label: 'Materials', type: 'bool', default: true,  tier: 'common' },
  { key: 'normals',   label: 'Normals',   type: 'bool', default: true,  tier: 'common' },
  { key: 'smoothing', label: 'Smoothing', type: 'bool', default: true,  tier: 'common' },
  { key: 'groups',    label: 'Groups',    type: 'bool', default: true,  tier: 'common' },
  { key: 'point_groups', label: 'Point groups', type: 'bool', default: false, tier: 'advanced' },
]

// ── Alembic (.abc) — AbcExport -j flags ───────────────────────────────────────
// Frame range is driven by the existing "Séquence animée" toggle, not here.
const ABC: ExportOption[] = [
  { key: 'uv_write',         label: 'UV write',         type: 'bool', default: true,  tier: 'common' },
  { key: 'write_visibility', label: 'Write visibility', type: 'bool', default: true,  tier: 'common' },
  { key: 'world_space',      label: 'World space',      type: 'bool', default: true,  tier: 'common' },
  { key: 'renderable_only',  label: 'Renderable only',  type: 'bool', default: false, tier: 'advanced' },
  { key: 'strip_namespaces', label: 'Strip namespaces', type: 'bool', default: false, tier: 'advanced' },
  { key: 'write_color_sets', label: 'Write color sets', type: 'bool', default: false, tier: 'advanced' },
  { key: 'write_uv_sets',    label: 'Write UV sets',    type: 'bool', default: false, tier: 'advanced' },
  { key: 'write_face_sets',  label: 'Write face sets',  type: 'bool', default: false, tier: 'advanced' },
  { key: 'euler_filter',     label: 'Euler filter',     type: 'bool', default: false, tier: 'advanced' },
  { key: 'no_normals',       label: 'No normals',       type: 'bool', default: false, tier: 'advanced' },
  { key: 'write_creases',    label: 'Write creases',    type: 'bool', default: false, tier: 'advanced' },
  { key: 'auto_subd',        label: 'Auto subdiv (creases/holes)', type: 'bool', default: false, tier: 'advanced' },
  { key: 'data_format', label: 'Data format', type: 'enum', default: 'ogawa', tier: 'advanced',
    choices: [{ value: 'ogawa', label: 'Ogawa' }, { value: 'hdf5', label: 'HDF5' }] },
]

// ── USD (.usd / .usda / .usdc) — mayaUSDExport flags ──────────────────────────
// Keys are the EXACT mayaUSDExport long flag names (from `cmds.help('mayaUSDExport')`);
// the backend passes them straight through. Defaults keep Flux's current behaviour
// (polys via defaultMeshScheme=none, exportUVs on, no skels/skin).
const USD: ExportOption[] = [
  // common
  { key: 'exportUVs',         label: 'Export UVs',        type: 'bool', default: true,  tier: 'common' },
  { key: 'exportMaterials',   label: 'Materials',         type: 'bool', default: true,  tier: 'common' },
  { key: 'exportBlendShapes', label: 'Blend shapes',      type: 'bool', default: false, tier: 'common' },
  { key: 'exportSkels', label: 'Skeletons', type: 'enum', default: 'none', tier: 'common',
    choices: [{ value: 'none', label: 'None' }, { value: 'auto', label: 'Auto' }, { value: 'explicit', label: 'Explicit' }] },
  { key: 'defaultMeshScheme', label: 'Mesh scheme', type: 'enum', default: 'none', tier: 'common',
    choices: [
      { value: 'none', label: 'None (polys)' }, { value: 'catmullClark', label: 'Catmull-Clark' },
      { value: 'loop', label: 'Loop' }, { value: 'bilinear', label: 'Bilinear' },
    ] },
  // advanced
  { key: 'exportSkin', label: 'Skin clusters', type: 'enum', default: 'none', tier: 'advanced',
    choices: [{ value: 'none', label: 'None' }, { value: 'auto', label: 'Auto' }] },
  { key: 'exportColorSets',     label: 'Color sets',        type: 'bool', default: true,  tier: 'advanced' },
  { key: 'exportDisplayColor',  label: 'Display color',     type: 'bool', default: false, tier: 'advanced' },
  { key: 'exportComponentTags', label: 'Component tags',    type: 'bool', default: true,  tier: 'advanced' },
  { key: 'exportVisibility',    label: 'Visibility',        type: 'bool', default: true,  tier: 'advanced' },
  { key: 'exportInstances',     label: 'Instances',         type: 'bool', default: true,  tier: 'advanced' },
  { key: 'mergeTransformAndShape', label: 'Merge transform & shape', type: 'bool', default: true, tier: 'advanced' },
  { key: 'stripNamespaces',     label: 'Strip namespaces',  type: 'bool', default: false, tier: 'advanced' },
  { key: 'eulerFilter',         label: 'Euler filter',      type: 'bool', default: false, tier: 'advanced' },
  { key: 'staticSingleSample',  label: 'Static single sample', type: 'bool', default: false, tier: 'advanced' },
  { key: 'worldspace',          label: 'World space',       type: 'bool', default: false, tier: 'advanced' },
  { key: 'preserveUVSetNames',  label: 'Preserve UV set names', type: 'bool', default: false, tier: 'advanced' },
  { key: 'normalizeNurbs',      label: 'Normalize NURBS',   type: 'bool', default: false, tier: 'advanced' },
  { key: 'geomSidedness', label: 'Geom sidedness', type: 'enum', default: 'derived', tier: 'advanced',
    choices: [{ value: 'derived', label: 'Derived' }, { value: 'single', label: 'Single' }, { value: 'double', label: 'Double' }] },
  { key: 'upAxis', label: 'Up axis', type: 'enum', default: 'y', tier: 'advanced',
    choices: [{ value: 'y', label: 'Y' }, { value: 'z', label: 'Z' }] },
]

// Map an extension to its schema (usd variants share one schema).
export function schemaForExt(ext: string): ExportOption[] {
  switch (ext.toLowerCase()) {
    case '.ma':
    case '.mb':  return MAYA_SCENE
    case '.fbx': return FBX
    case '.obj': return OBJ
    case '.abc': return ABC
    case '.usd':
    case '.usda':
    case '.usdc': return USD
    default: return []
  }
}

// Build the default value map for a schema.
export function defaultOptions(schema: ExportOption[]): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const o of schema) out[o.key] = o.default
  return out
}
