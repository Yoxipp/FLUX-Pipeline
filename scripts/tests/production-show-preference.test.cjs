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

const prefs = load('showPreference')
const values = new Map()
const storage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) }
test('Show persists All, Mine and sequence selection across independent reads', () => {
  const key = prefs.productionShowKey('SHOW_QA', 'shot')
  for (const filter of [{ kind: 'all' }, { kind: 'mine' }, { kind: 'seq', id: 'sequence-id' }]) {
    prefs.writeProductionShow(key, filter, storage)
    assert.deepEqual(prefs.readProductionShow(key, storage), filter)
  }
})
test('Show preferences are isolated by project, mode and entity view', () => {
  const keys = [prefs.productionShowKey('A', 'shot'), prefs.productionShowKey('B', 'shot'), prefs.productionShowKey('A', 'asset'), prefs.productionShowKey('A', 'shot', 'entity')]
  assert.equal(new Set(keys).size, 4)
  prefs.writeProductionShow(keys[0], { kind: 'mine' }, storage)
  for (const key of keys.slice(1)) assert.deepEqual(prefs.readProductionShow(key, storage), { kind: 'all' })
})
test('missing, corrupt and malformed preferences fall back to All', () => {
  const key = 'invalid-show'
  for (const raw of [null, 'invalid', 'null', 'false', '[]', '{}', '{"kind":"unknown"}', '{"kind":"seq"}', '{"kind":"seq","id":""}', '{"kind":"seq","id":123}']) {
    if (raw === null) values.delete(key); else values.set(key, raw)
    assert.deepEqual(prefs.readProductionShow(key, storage), { kind: 'all' })
  }
})
test('storage failures cannot break the production table', () => {
  const unavailable = { getItem() { throw new Error('blocked') }, setItem() { throw new Error('blocked') } }
  assert.deepEqual(prefs.readProductionShow('show', unavailable), { kind: 'all' })
  assert.doesNotThrow(() => prefs.writeProductionShow('show', { kind: 'mine' }, unavailable))
})
