const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const ts = require('typescript')

// Load a TS module, its relative imports through `deps`.
const load = (file, deps = {}) => {
  const mod = { exports: {} }
  const js = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText
  new Function('exports', 'module', 'require', js)(mod.exports, mod, name => deps[name])
  return mod.exports
}
const tracking = load('app/src/pages/Production/tracking.ts')
const { productionRowGroups, assetDisplayClass } = load('app/src/pages/Production/tableRows.ts', { './tracking': tracking })
const asset = (id, cls, order = 0) => ({ id, class: cls, name: id, order, group_id: null, tasks: [] })
const state = { sequences: [], shots: [], assets: [], asset_groups: [] }
const groups = rows => productionRowGroups(state, rows, 'asset', [], null)

test('groups show in Chara, Enviro, Props order, other classes after', () => {
  const r = groups([asset('P', 'PROPS'), asset('X', 'VEHICLE'), asset('E', 'ENV'), asset('C', 'CHAR')])
  assert.deepEqual(r.map(g => g.assetClass), ['CHAR', 'ENV', 'PROPS', 'VEHICLE'])
})
test('FXRIG assets show under Chara, their token untouched', () => {
  const r = groups([asset('FX', 'FXRIG', 1), asset('HERO', 'CHAR', 0)])
  assert.deepEqual(r.map(g => g.assetClass), ['CHAR'])
  assert.deepEqual(r[0].entities.map(e => e.name), ['HERO', 'FX'])
  assert.equal(r[0].entities[1].class, 'FXRIG')
})
test('display class is case insensitive and leaves other tokens alone', () => {
  assert.equal(assetDisplayClass('fxrig'), 'CHAR')
  assert.equal(assetDisplayClass('env'), 'ENV')
  assert.equal(assetDisplayClass(''), '')
})
