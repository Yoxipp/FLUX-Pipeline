const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const ts = require('typescript')
const source = fs.readFileSync(path.join(__dirname, '../../app/src/hooks/useNavRail.ts'), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText
const mod = { exports: {} }
new Function('exports', 'require', 'module', compiled)(mod.exports, require, mod)
const { navRailFromStored } = mod.exports

test('a machine that never touched the switch gets the thin bar', () => {
  assert.equal(navRailFromStored(null), true)
})
test('the choice made in the settings is kept', () => {
  assert.equal(navRailFromStored('1'), true)
  assert.equal(navRailFromStored('0'), false)
})
