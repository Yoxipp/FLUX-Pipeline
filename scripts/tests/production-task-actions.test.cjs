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
const m = load('taskActions')
const task = { id: 'task', name: 'Animation', type_tokens: ['ANIM'], known_subtasks: ['BLOCK'], order: 0 }
const fixture = () => ({ version: 1, sequences: [{ id: 'seq', name: 'SEQ0010', order: 0, tasks: [task], assets: [] }], shots: [{ id: 'sh', name: 'SHOT0020', seq_id: 'seq', order: 0, inherit_tasks: true, tasks: [], assets: [], task_details: { 'ANIMATION|BLOCK': { notes: 'Keep', status: 'RTK' } } }], assets: [{ id: 'hero', class: 'CHAR', name: 'HERO', group_id: null, order: 0, tasks: [task] }], asset_groups: [] })

test('assigning inherited task materializes only the shot and preserves review and notes', () => {
  const s = fixture(), next = m.patchTaskArtist(s, 'sh', task, 'block', 'ANTOINE')
  assert.deepEqual(next.shots[0].task_details['ANIMATION|BLOCK'], { notes: 'Keep', status: 'RTK', assignee: 'ANTOINE' })
  assert.notEqual(next.shots[0].tasks[0].id, task.id)
  assert.equal(next.sequences[0].task_details, undefined)
  assert.equal(s.shots[0].tasks.length, 0)
})
test('sequence review and subtask assignment preserve other details', () => {
  let s = fixture(); s.sequences[0].task_details = { ANIMATION: { notes: 'Sequence notes', status: 'APPROVED' } }
  s = m.setTaskStatus(s, s.sequences[0], task, 'BLOCK', 'RTK')
  assert.deepEqual(s.sequences[0].task_details.ANIMATION, { notes: 'Sequence notes' })
  s = m.patchTaskArtist(s, 'seq', task, 'BLOCK', 'TOM')
  assert.deepEqual(s.sequences[0].task_details['ANIMATION|BLOCK'], { status: 'RTK', assignee: 'TOM' })
})
test('publisher prefill keeps Instance empty for assets and shots', () => {
  const s = fixture()
  assert.deepEqual(m.taskPublisherPrefill('QA', s, s.assets[0], task), { project: 'QA', mode: 'asset', sel: { category: 'CHAR', name: 'HERO', task: 'ANIM', instance: '', variante: '' } })
  assert.deepEqual(m.taskPublisherPrefill('QA', s, s.shots[0], task), { project: 'QA', mode: 'shot', sel: { seq: 'SEQ0010', shot: 'SHOT0020', name: 'ANIM', variante: '' } })
})
test('batch shots use selected sequence, default next ten, and independent metadata', () => {
  const s = fixture(); let i = 0
  const next = m.createShotBatch(s, 'seq', 3, '', '', 'Opening', () => `new${++i}`)
  assert.deepEqual(next.shots.map(s => s.name), ['SHOT0020', 'SHOT0030', 'SHOT0040', 'SHOT0050'])
  assert.equal(next.shots[1].label, 'Opening')
  assert.notEqual(next.shots[1].tasks, next.shots[2].tasks)
  assert.equal(s.shots.length, 1)
})
test('batch numbering preserves secondary digit and inserts in numerical order', () => {
  const next = m.createShotBatch(fixture(), 'seq', 2, '1', '5', '', () => 'new')
  assert.deepEqual(next.shots.map(s => [s.name, s.order]), [['SHOT0015', 0], ['SHOT0020', 1], ['SHOT0025', 2]])
})
test('batch creation preserves the relative timeline order of existing shots', () => {
  const s = fixture()
  s.shots.push({ ...s.shots[0], id: 'first', name: 'SHOT0040', order: -1 })
  const next = m.createShotBatch(s, 'seq', 2, '5', '', '', () => 'new')
  assert.deepEqual(next.shots.map(s => s.name), ['SHOT0040', 'SHOT0020', 'SHOT0050', 'SHOT0060'])
})
test('batch creation rejects duplicates, invalid count, range, missing and locked sequences atomically', () => {
  const s = fixture()
  assert.throws(() => m.createShotBatch(s, 'seq', 3, '1', '', '', () => 'new'), /existe/)
  for (const count of [0, 1001, 1.5, NaN]) assert.throws(() => m.createShotBatch(s, 'seq', count, '', '', '', () => 'new'))
  assert.throws(() => m.createShotBatch(s, 'seq', 3, '999', '9', '', () => 'new'))
  assert.throws(() => m.createShotBatch(s, 'missing', 1, '', '', '', () => 'new'))
  s.sequences[0].locked = { by: 'TOM', at: '2026-10-02' }
  assert.throws(() => m.createShotBatch(s, 'seq', 1, '', '', '', () => 'new'), /verrouillée/)
  assert.equal(s.shots.length, 1)
})
