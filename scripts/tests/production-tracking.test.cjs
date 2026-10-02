// Run with node --test scripts/tests/production-tracking.test.cjs. No additional test dependency.
const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const ts = require('typescript')
const source = fs.readFileSync(path.join(__dirname, '../../app/src/pages/Production/tracking.ts'), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText
const mod = { exports: {} }
new Function('exports', 'require', 'module', compiled)(mod.exports, require, mod)
const m = mod.exports
const task = (id, name, tokens = [name], subs = []) => ({ id, name, order: 0, type_tokens: tokens, known_subtasks: subs })
const anim = task('seq-anim', 'ANIM', ['ANIM'], ['BLOCK', 'POLISH'])
const fixture = () => ({ version: 1, sequences: [{ id: 'seq', name: 'SEQ0010', order: 0, tasks: [anim], assets: [{ id: 'a', ref: 'HERO', count: 2 }] }], shots: [{ id: 'sh', name: 'SHOT0020', seq_id: 'seq', order: 0, inherit_tasks: true, inherit_assets: true, tasks: [], assets: [{ id: 'b', ref: 'SET' }] }], assets: [{ id: 'a', class: 'CHAR', name: 'HERO', order: 0, group_id: null, tasks: [task('rig', 'RIG')], task_details: { RIG: { completion: 100 } } }, { id: 'b', class: 'ENV', name: 'SET', order: 1, group_id: null, tasks: [] }], asset_groups: [] })
const dep = id => m.DEFAULT_DEPARTMENTS.find(d => d.id === id)

test('empty and legacy projects get department columns without mutating their metadata', () => {
  const s = { version: 1, assets: [], shots: [], sequences: [], asset_groups: [] }
  assert.equal(m.trackingDepartments(s, 'shot').length, 6)
  assert.equal(m.trackingDepartments(s, 'asset').length, 4)
  assert.equal(s.tracking, undefined)
})
test('shot tasks inherit templates but never sequence approval', () => {
  const s = fixture(); s.sequences[0].task_details = { ANIM: { status: 'APPROVED' } }
  assert.equal(m.departmentStatus(s, s.shots[0], dep('anim')), 'TODO')
  assert.equal(m.departmentStatus(s, s.shots[0], dep('layout')), 'N/A')
  assert.equal(s.shots[0].tasks.length, 0)
})
test('materializing an inherited task is idempotent and keeps independent ids and arrays', () => {
  const s = fixture(); const next = m.ensureTrackingTask(s, 'sh', anim)
  assert.notEqual(next.shots[0].tasks[0].id, anim.id)
  assert.notEqual(next.shots[0].tasks[0].known_subtasks, anim.known_subtasks)
  assert.equal(m.ensureTrackingTask(next, 'sh', anim).shots[0].tasks.length, 1)
  assert.equal(s.shots[0].tasks.length, 0)
})
test('N/A departments can materialize tasks for assets and shots', () => {
  const s = fixture()
  assert.equal(m.ensureTrackingTask(s, 'b', task('new', 'GEO')).assets[1].tasks[0].name, 'GEO')
  assert.equal(m.ensureTrackingTask(s, 'sh', task('new', 'LAYOUT')).shots[0].tasks[0].name, 'LAYOUT')
})
test('casting supports several assets, inherited counts and own overrides', () => {
  const s = fixture()
  assert.deepEqual(m.effectiveCasting(s, s.shots[0]).map(l => l.id), ['b', 'a'])
  s.shots[0].assets.push({ id: 'a', ref: 'HERO', count: 3 })
  assert.equal(m.effectiveCasting(s, s.shots[0]).filter(l => l.id === 'a').length, 1)
  assert.equal(m.effectiveCasting(s, s.shots[0])[1].count, 3)
  s.shots[0].inherit_assets = false
  assert.equal(m.effectiveCasting(s, s.shots[0]).length, 2)
})
test('100% completion is WIP and does not satisfy approval dependencies', () => {
  const s = fixture()
  assert.equal(m.detailStatus({ completion: 100 }), 'WIP')
  assert.equal(m.dependencyReady(s, { entity_id: 'a', task: 'RIG' }), false)
})
test('status patches preserve notes/comments and only affect the selected subtask', () => {
  const s = fixture(); s.shots[0].task_details = { 'ANIM|BLOCK': { notes: 'Keep', comments: [{ id: 'c' }] } }
  const next = m.patchTrackingDetail(s, 'sh', anim, 'BLOCK', 'RTK')
  assert.equal(next.shots[0].task_details['ANIM|BLOCK'].status, 'RTK')
  assert.equal(next.shots[0].task_details['ANIM|BLOCK'].notes, 'Keep')
  assert.equal(next.shots[0].task_details['ANIM|BLOCK'].comments[0].id, 'c')
  assert.equal(m.departmentStatus(next, next.shots[0], dep('anim')), 'RTK')
  assert.equal(s.shots[0].task_details['ANIM|BLOCK'].status, undefined)
})
test('all subtasks must be reviewed before department approval', () => {
  let s = fixture(); s = m.patchTrackingDetail(s, 'sh', anim, 'BLOCK', 'APPROVED')
  assert.equal(m.departmentStatus(s, s.shots[0], dep('anim')), 'WIP')
  s = m.patchTrackingDetail(s, 'sh', anim, 'POLISH', 'APPROVED')
  assert.equal(m.departmentStatus(s, s.shots[0], dep('anim')), 'APPROVED')
})
test('multiple tasks aggregate retakes before approval', () => {
  const s = fixture(); s.shots[0].tasks = [task('one', 'ANIM'), task('two', 'CHAR_ANIM', ['ANIM'])]
  s.shots[0].task_details = { ANIM: { status: 'APPROVED' }, CHAR_ANIM: { status: 'RTK' } }
  assert.equal(m.departmentStatus(s, s.shots[0], dep('anim')), 'RTK')
})
test('unknown statuses remain visible and never resolve blockers', () => {
  const s = fixture(); s.assets[0].task_details.RIG.status = 'LEGACY_REVIEW'
  assert.equal(m.departmentStatus(s, s.assets[0], dep('rig')), 'LEGACY_REVIEW')
  assert.equal(m.dependencyReady(s, { entity_id: 'a' }), false)
})
test('subtask review clears an obsolete parent approval and preserves parent notes', () => {
  const s = fixture(); s.shots[0].task_details = { ANIM: { status: 'APPROVED', notes: 'Keep' } }
  const next = m.patchTrackingDetail(s, 'sh', anim, 'POLISH', 'RTK')
  assert.equal(m.departmentStatus(next, next.shots[0], dep('anim')), 'RTK')
  assert.equal(next.shots[0].task_details.ANIM.notes, 'Keep')
  assert.equal(next.shots[0].task_details.ANIM.status, undefined)
})
test('unknown subtask statuses stay visible', () => {
  const s = fixture(); s.shots[0].task_details = { 'ANIM|BLOCK': { status: 'LEGACY_REVIEW' } }
  assert.equal(m.departmentStatus(s, s.shots[0], dep('anim')), 'LEGACY_REVIEW')
})
test('sequence locks protect shots while assets remain editable', () => {
  const s = fixture(); s.sequences[0].locked = { by: 'QA', at: '2026-10-02' }
  assert.equal(m.trackingLocked(s, s.shots[0]), true)
  assert.equal(m.trackingLocked(s, s.assets[0]), false)
})
test('dependencies on assets, shots and departments expose missing and unapproved targets', () => {
  const s = fixture(); s.shots[0].dependencies = [{ entity_id: 'a', task: 'RIG' }, { entity_id: 'gone' }]
  const d = { ...dep('anim'), depends_on: ['layout'] }
  assert.deepEqual(m.blockers(s, s.shots[0], d), ['HERO · RIG', 'Lien manquant (gone)', 'Layout'])
  s.assets[0].task_details.RIG.status = 'APPROVED'
  assert.equal(m.blockers(s, s.shots[0], d).length, 2)
  assert.equal(m.dependencyReady(s, { entity_id: 'b' }), false)
})
test('configured columns retain fixed flags, active states, tokens and custom legacy tasks', () => {
  const s = fixture(); s.tracking = { departments: [{ ...dep('anim'), active: false, statuses: ['WIP', 'APPROVED'] }] }
  s.shots[0].tasks.push(task('custom', 'MATCHMOVE'))
  const columns = m.trackingDepartments(s, 'shot')
  assert.equal(columns.find(d => d.id === 'anim').active, false)
  assert.equal(columns.find(d => d.id === 'anim').fixed, true)
  assert.ok(columns.some(d => d.name === 'MATCHMOVE'))
  assert.equal(s.tracking.departments.length, 1)
})
