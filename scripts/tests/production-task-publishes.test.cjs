const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const ts = require('typescript')
const source = fs.readFileSync(path.join(__dirname, '../../app/src/pages/Production/taskPublishes.ts'), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText
const mod = { exports: {} }
new Function('exports', 'require', 'module', compiled)(mod.exports, require, mod)
const m = mod.exports
const pub = (file, date, time) => ({ file, date, time })

test('version is read from the file name, with or without an extension', () => {
  assert.equal(m.publishVersion('HERO_MOD_v012.usd'), 'v012')
  assert.equal(m.publishVersion('HERO_MOD_v1234'), 'v1234')
  assert.equal(m.publishVersion('HERO_MOD_LAST.usd'), '')
  assert.equal(m.publishVersion('HERO_v12.usd'), '')
})
test('publishes sort newest first without touching the input', () => {
  const input = [pub('a', '2026-11-01', '10:00'), pub('b', '2026-11-02', '09:00'), pub('c', '2026-11-01', '11:00')]
  assert.deepEqual(m.sortPublishes(input).map(p => p.file), ['b', 'c', 'a'])
  assert.deepEqual(input.map(p => p.file), ['a', 'b', 'c'])
})
test('a version request finds its publish and ignores case', () => {
  const sorted = [pub('X_v002.usd', '2026-11-02', '09:00'), pub('X_v001.usd', '2026-11-01', '09:00')]
  assert.equal(m.publishOfVersion(sorted, 'V001').file, 'X_v001.usd')
  assert.equal(m.publishOfVersion(sorted, 'v009'), null)
  assert.equal(m.publishOfVersion(sorted, undefined), null)
})
