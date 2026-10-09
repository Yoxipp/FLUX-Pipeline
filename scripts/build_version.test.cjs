// Tests of the version helpers of scripts/build.cjs. Run: node --test scripts/build_version.test.cjs
// (also run by backend/tests/system/test_app_version.py when node is on PATH).
'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const { parse, display, semver, next, compare, nshContent } = require('./build.cjs')

test('parse accepts padded and unpadded builds', () => {
  assert.deepEqual(parse('0.8.000'), { major: 0, minor: 8, build: 0 })
  assert.deepEqual(parse('0.8.001'), { major: 0, minor: 8, build: 1 })
  assert.deepEqual(parse('0.8.1'), { major: 0, minor: 8, build: 1 })
  assert.throws(() => parse('0.8'))
  assert.throws(() => parse('v0.8.001'))
})

test('display is x.x.xxx, semver has no leading zero', () => {
  assert.equal(display(parse('0.8.1')), '0.8.001')
  assert.equal(display(parse('0.8.0')), '0.8.000')
  assert.equal(display(parse('1.2.123')), '1.2.123')
  assert.equal(semver(parse('0.8.001')), '0.8.1')
  assert.equal(semver(parse('0.8.000')), '0.8.0')
})

test('atomic build always wins over the minor release', () => {
  assert.ok(compare(parse('0.8.001'), parse('0.8.000')) > 0)
  assert.ok(compare(parse('0.8.000'), parse('0.8.001')) < 0)
  assert.ok(compare(parse('0.8.010'), parse('0.8.009')) > 0)
  assert.ok(compare(parse('0.9.000'), parse('0.8.999')) > 0)
  assert.equal(compare(parse('0.8.1'), parse('0.8.001')), 0)
})

test('next bumps build, minor or major', () => {
  assert.equal(display(next(parse('0.8.000'), {})), '0.8.001')
  assert.equal(display(next(parse('0.8.009'), {})), '0.8.010')
  assert.equal(display(next(parse('0.8.003'), { minor: true })), '0.9.000')
  assert.equal(display(next(parse('0.8.003'), { minor: true, major: true })), '1.0.000')
})

test('nsh carries both the display and the semver form', () => {
  const nsh = nshContent(parse('0.8.001'))
  assert.match(nsh, /!define FLUX_VERSION "0\.8\.001"/)
  assert.match(nsh, /!define FLUX_SEMVER "0\.8\.1"/)
})
