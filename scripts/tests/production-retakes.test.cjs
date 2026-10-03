const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const ts = require('typescript')
const cache = {}
function load(name) {
  if (cache[name]) return cache[name]
  const source = fs.readFileSync(path.join(__dirname, '../../app/src/pages/Production', name + '.ts'), 'utf8')
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText
  const mod = { exports: {} }
  new Function('exports', 'require', 'module', compiled)(mod.exports, n => n.startsWith('./') ? load(n.slice(2)) : require(n), mod)
  return cache[name] = mod.exports
}

const rows = load('tableRows'), tracking = load('tracking'), actions = load('taskActions')
const task = { id: 'light', name: 'LIGHT', order: 0, type_tokens: ['LIGHT'], known_subtasks: ['PASS'] }
const dep = { id: 'lighting', scope: 'shot', name: 'Lighting', active: true, fixed: true, task_tokens: ['LIGHT'], statuses: ['TODO', 'WIP', 'WFA', 'RTK', 'APPROVED'], depends_on: [] }
const fixture = () => ({ version: 1, assets: [], asset_groups: [], sequences: ['a','b'].map((id,order) => ({ id, name: 'SEQ'+id, order, tasks: [task], assets: [] })), shots: [['a','TODO'],['a','RTK'],['b','WIP'],['b','APPROVED']].map(([seq_id,status],order) => ({ id: 'sh'+order, name: 'SHOT'+order, seq_id, order, inherit_tasks: true, tasks: [], assets: [], task_details: { LIGHT: { status, notes: 'Keep', assignee: 'TOM', comments: [{ id: 'c', text: 'Keep' }] } } })) })

test('department sort prioritizes the chosen status, preserving sequence blocks and source order metadata', () => {
  const s = fixture(), original = JSON.stringify(s)
  const groups = rows.productionRowGroups(s, s.shots, 'shot', [dep], { id: dep.id, first: 'APPROVED' })
  assert.deepEqual(groups.map(g => g.id), ['b','a'])
  assert.deepEqual(groups[0].entities.map(e => e.id), ['sh3','sh2'])
  assert.deepEqual(groups[1].entities.map(e => e.id), ['sh0','sh1'])
  assert.equal(JSON.stringify(s), original)
  assert.deepEqual(rows.productionRowGroups(s, s.shots, 'shot', [dep], null).map(g => g.id), ['a','b'])
})
test('virtual fixed TODO, optional empty, custom statuses and multiple tasks sort consistently', () => {
  const s = fixture(), sh = { ...s.shots[0], task_details: {}, inherit_tasks: false }
  assert.equal(rows.departmentRank(s, sh, dep, 'TODO'), 0)
  assert.equal(rows.departmentRank(s, sh, { ...dep, fixed: false }, 'TODO'), dep.statuses.length + 1)
  sh.tasks = [{ ...task, id: 'a', name: 'LIGHT_A' }, { ...task, id: 'b', name: 'LIGHT_B' }]
  sh.task_details = { LIGHT_A: { status: 'CUSTOM' }, LIGHT_B: { status: 'RTK' } }
  assert.equal(rows.departmentRank(s, sh, { ...dep, statuses: [...dep.statuses, 'CUSTOM'] }, 'CUSTOM'), 0)
})
test('empty sequences are retained only when requested; missing sequence rows remain reachable', () => {
  const s = fixture()
  assert.equal(rows.productionRowGroups(s, [], 'shot', [dep], null).length, 0)
  assert.equal(rows.productionRowGroups(s, [], 'shot', [dep], null, s.sequences).length, 2)
  const groups = rows.productionRowGroups(s, [{ ...s.shots[0], seq_id: 'missing' }], 'shot', [dep], null)
  assert.equal(groups[0].sequence, null)
  assert.equal(groups[0].entities.length, 1)
})
test('asset sorting uses the same review rules without sequence blocks', () => {
  const s = fixture(); s.assets = s.shots.map(({ seq_id, ...shot }) => ({ ...shot, class: 'CHAR', group_id: null, tasks: [task] }))
  const groups = rows.productionRowGroups(s, s.assets, 'asset', [dep], { id: dep.id, first: 'RTK' })
  assert.equal(groups.length, 1)
  assert.equal(groups[0].sequence, null)
  assert.equal(groups[0].entities[0].id, 'sh1')
})
test('clearing a fixed badge retains task structure, content and artist, including locked templates', () => {
  const s = fixture(); s.shots[0].locked = true
  const next = actions.clearTaskBadge(s, 'sh0', task)
  assert.deepEqual(next.shots[0].tasks, [])
  assert.deepEqual(next.shots[0].task_details.LIGHT, { ...s.shots[0].task_details.LIGHT, status: '' })
  assert.equal(tracking.trackingTaskStatus(next.shots[0], task, dep), '')
  assert.notEqual(tracking.departmentStatus(next, next.shots[0], dep), 'APPROVED')
  assert.equal(s.shots[0].task_details.LIGHT.status, 'TODO')
  const restored = actions.setTaskStatus(next, next.shots[0], task, '', 'WIP')
  assert.equal(tracking.trackingTaskStatus(restored.shots[0], task, dep), 'WIP')
})
test('subtask badge clearing supersedes parent approval and later review restores aggregation', () => {
  const s = fixture(); s.shots[0].task_details = { LIGHT: { status: 'APPROVED', notes: 'Parent' }, 'LIGHT|PASS': { status: 'APPROVED', assignee: 'TOM', notes: 'Sub' } }
  const next = actions.clearTaskBadge(s, 'sh0', task, 'PASS')
  assert.deepEqual(next.shots[0].task_details.LIGHT, { notes: 'Parent' })
  assert.deepEqual(next.shots[0].task_details['LIGHT|PASS'], { status: '', assignee: 'TOM', notes: 'Sub' })
  assert.notEqual(tracking.taskStatus(next.shots[0], task), 'APPROVED')
  const cleared = actions.clearTaskBadge(s, 'sh0', task)
  const restored = actions.setTaskStatus(cleared, cleared.shots[0], task, 'PASS', 'WIP')
  assert.equal(tracking.taskStatus(restored.shots[0], task), 'WIP')
})
