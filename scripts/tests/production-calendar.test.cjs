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
const m = load('shotCalendar'), actions = load('taskActions')
const task = { id: 'light', name: 'LIGHT', order: 0, type_tokens: ['LIGHT'], known_subtasks: [] }
const fixture = () => ({ version: 1, asset_groups: [], assets: [], sequences: [{ id: 'seq', name: 'SEQ0010', order: 0, tasks: [task], assets: [] }], shots: [{ id: 'sh', name: 'SHOT0020', seq_id: 'seq', order: 0, tasks: [], assets: [], inherit_tasks: true }], tracking: { departments: [{ id: 'light', scope: 'shot', name: 'Lighting', order: 0, fixed: true, active: true, task_tokens: ['LIGHT'], statuses: ['TODO', 'APPROVED'], prerequisite_ids: [] }] } })
const item = (end, status = 'accepted', link = 'SEQ0010 SHOT0020 LIGHT') => ({ id: end, start: '2026-10-01', end, status, link })
const now = new Date(2026, 9, 2, 23, 59)
const status = (items, s = fixture()) => m.shotDeadline(s, s.shots[0], items, now)

test('calendar link uses exact sequence and shot tokens, across separators and case', () => {
  for (const link of ['seq0010 shot0020 LIGHT', 'SEQ0010/SHOT0020/LIGHT', 'SEQ0010_SHOT0020_LIGHT']) assert.equal(m.calendarLinksShot(link, 'SEQ0010', 'SHOT0020'), true)
  for (const link of ['SEQ0010 SHOT00201', 'SEQ0020 SHOT0020', 'SHOT0020', 'SEQ00101 SHOT0020']) assert.equal(m.calendarLinksShot(link, 'SEQ0010', 'SHOT0020'), false)
})
test('no linked task or declined-only links are None', () => {
  assert.equal(status([]), 'None')
  assert.equal(status([item('2026-10-02', 'declined')]), 'None')
  assert.equal(status([item('2026-10-02', 'accepted', 'SEQ0020 SHOT0020')]), 'None')
})
test('deadline thresholds use inclusive local calendar days, including the 5-10 day gap', () => {
  for (const [end, expected] of [['2026-10-13', 'In time'], ['2026-10-12', 'In time'], ['2026-10-07', 'In time'], ['2026-10-06', 'Late'], ['2026-10-03', 'Late'], ['2026-10-02', 'Extra-late'], ['2026-10-01', 'Extra-late']]) assert.equal(status([item(end)]), expected)
})
test('earliest outstanding deadline wins; completed and declined dates do not make a shot late', () => {
  assert.equal(status([item('2026-10-13'), item('2026-10-03')]), 'Late')
  assert.equal(status([item('2026-10-01', 'done'), item('2026-10-02', 'declined'), item('2026-10-13')]), 'In time')
  assert.equal(status([item('2026-10-01', 'done')]), 'In time')
})
test('Done requires production approval; optional empty tasks do not count', () => {
  const s = fixture()
  s.tracking.departments.push({ ...s.tracking.departments[0], id: 'render', name: 'Rendering', fixed: false, task_tokens: ['RENDER'] })
  s.shots[0].task_details = { LIGHT: { status: 'APPROVED' } }
  assert.equal(status([item('2026-10-01')], s), 'Done')
  assert.equal(status([], s), 'None')
  s.shots[0].task_details.RENDER = { status: 'WIP' }
  assert.equal(status([item('2026-10-01')], s), 'Extra-late')
  s.tracking.departments = []
  assert.notEqual(status([item('2026-10-01')], s), 'Done')
})
test('bad dates are ignored without throwing', () => {
  assert.equal(status([item('invalid'), item('2026-02-30'), item('2026-10-06')]), 'Late')
})
test('locked shot and locked sequence allow review and assignment without adding structural tasks', () => {
  for (const lockParent of [false, true]) {
    const s = fixture()
    if (lockParent) s.sequences[0].locked = true
    else s.shots[0].locked = true
    let next = actions.setTaskStatus(s, s.shots[0], task, '', 'APPROVED')
    next = actions.patchTaskArtist(next, 'sh', task, '', 'TOM')
    assert.deepEqual(next.shots[0].tasks, [])
    assert.deepEqual(next.shots[0].task_details.LIGHT, { status: 'APPROVED', assignee: 'TOM' })
    assert.equal(next.sequences[0].task_details, undefined)
    assert.equal(s.shots[0].task_details, undefined)
  }
})
