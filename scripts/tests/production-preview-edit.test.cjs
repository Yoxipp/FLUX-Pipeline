// Timeline preview + auto edit (app/src/pages/Production/previewEdit.ts).
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
const m = load('previewEdit')
const task = (name) => ({ id: name, name, order: 0, type_tokens: [name], known_subtasks: [] })
const state = () => ({
  version: 1,
  sequences: [{ id: 's2', name: 'SEQ020', order: 1, tasks: [], assets: [] }, { id: 's1', name: 'SEQ010', order: 0, tasks: [task('ANIM')], assets: [] }],
  shots: [
    { id: 'b', seq_id: 's1', name: 'SHOT020', order: 1, inherit_tasks: true, inherit_assets: true, tasks: [], assets: [], frame_start: 1001, frame_end: 1024 },
    { id: 'a', seq_id: 's1', name: 'SHOT010', order: 0, inherit_tasks: true, inherit_assets: true, tasks: [], assets: [] },
    { id: 'c', seq_id: 's2', name: 'SHOT010', order: 0, inherit_tasks: false, inherit_assets: true, tasks: [task('PREVIZ')], assets: [] },
  ],
  assets: [], asset_groups: [],
})
const media = (taskTok) => ({ task: taskTok, rel_path: `x/${taskTok}`, file: 'LAST.mp4', ext: '.mp4', kind: 'video', version: 'v001', version_file: 'v001.mp4', version_count: 1, abs_path: `C:/p/${taskTok}.mp4` })

test('candidates go from storyboard to the last department, custom tasks after', () => {
  const s = state()
  const tokens = m.previewCandidates(s, s.shots[2]).map(c => c.token)
  assert.deepEqual(tokens.slice(0, 3), ['STORYBOARD', 'SB', 'ANIMATIC'])
  assert.ok(tokens.indexOf('LAYOUT') < tokens.indexOf('ANIM'))
  assert.ok(tokens.indexOf('ANIM') < tokens.indexOf('COMP'))
  assert.equal(tokens[tokens.length - 1], 'PREVIZ')
})

test('auto shows the most advanced stage, a department only itself, all shows everything', () => {
  const s = state(), cands = m.previewCandidates(s, s.shots[1])
  const list = [media('ANIM'), media('STORYBOARD'), media('LAYOUT')]
  assert.deepEqual(m.pickMedia(list, cands, 'auto').map(x => x.task), ['ANIM'])
  assert.deepEqual(m.pickMedia(list, cands, 'storyboard').map(x => x.task), ['STORYBOARD'])
  assert.deepEqual(m.pickMedia(list, cands, 'all').map(x => x.task), ['STORYBOARD', 'LAYOUT', 'ANIM'])
  assert.deepEqual(m.pickMedia(list, cands, 'comp'), [])
  assert.deepEqual(m.pickMedia([], cands, 'auto'), [])
})

test('source picker lists each stage once after Auto and Tout', () => {
  const s = state(), opts = m.previewSources(m.previewCandidates(s, s.shots[1]))
  assert.deepEqual(opts.slice(0, 3).map(o => o.id), ['auto', 'all', 'storyboard'])
  assert.equal(new Set(opts.map(o => o.id)).size, opts.length)
})

test('montage follows sequence then shot order, keeps gaps and durations', () => {
  const s = state()
  const frames = sh => (typeof sh.frame_end === 'number' ? sh.frame_end - sh.frame_start + 1 : 50)
  const clips = m.buildMontage(s, { a: [media('ANIM')], c: [media('PREVIZ')] }, 'auto', 24, frames)
  assert.deepEqual(clips.map(c => `${c.seq}/${c.shot}`), ['SEQ010/SHOT010', 'SEQ010/SHOT020', 'SEQ020/SHOT010'])
  assert.equal(clips[1].media, null)
  assert.equal(clips[1].frames, 24)
  assert.equal(clips[1].seconds, 1)
  assert.equal(m.buildMontage(s, {}, 'all', 24, frames, 's2').length, 1)
})
