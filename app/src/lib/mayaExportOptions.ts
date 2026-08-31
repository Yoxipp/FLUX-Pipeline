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

export type ExportOptionType = 'bool' | 'enum' | 'int' | 'float'

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
  { key: 'skins',            label: 'Skins',                  type: 'bool', default: true,  tier: 'common' },
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
  { key: 'data_format', label: 'Data format', type: 'enum', default: 'ogawa', tier: 'advanced',
    choices: [{ value: 'ogawa', label: 'Ogawa' }, { value: 'hdf5', label: 'HDF5' }] },
]

// ── USD (.usd / .usda / .usdc) — mayaUSDExport kwargs ─────────────────────────
const USD: ExportOption[] = [
  { key: 'export_uvs',        label: 'Export UVs',       type: 'bool', default: true,  tier: 'common' },
  { key: 'export_materials',  label: 'Materials',        type: 'bool', default: true,  tier: 'common' },
  { key: 'export_blend_shapes', label: 'Blend shapes',   type: 'bool', default: false, tier: 'common' },
  { key: 'export_skels', label: 'Skeletons', type: 'enum', default: 'none', tier: 'common',
    choices: [{ value: 'none', label: 'None' }, { value: 'auto', label: 'Auto' }, { value: 'explicit', label: 'Explicit' }] },
  { key: 'export_skin', label: 'Skin clusters', type: 'enum', default: 'none', tier: 'advanced',
    choices: [{ value: 'none', label: 'None' }, { value: 'auto', label: 'Auto' }, { value: 'explicit', label: 'Explicit' }] },
  { key: 'mesh_scheme', label: 'Mesh scheme', type: 'enum', default: 'none', tier: 'advanced',
    choices: [{ value: 'none', label: 'None (polys)' }, { value: 'catmullClark', label: 'Catmull-Clark' }] },
  { key: 'export_color_sets',   label: 'Color sets',        type: 'bool', default: false, tier: 'advanced' },
  { key: 'export_display_color', label: 'Display color',    type: 'bool', default: false, tier: 'advanced' },
  { key: 'merge_xform_shape',   label: 'Merge transform & shape', type: 'bool', default: true, tier: 'advanced' },
  { key: 'strip_namespaces',    label: 'Strip namespaces',  type: 'bool', default: false, tier: 'advanced' },
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
