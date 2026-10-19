import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { hasCompletedTurn } from '../src/modules/assignments/aiTeacherChat.js'

const source = readFileSync(new URL('../src/api.js', import.meta.url), 'utf8').split("let csrfToken = ''")[0].replace('export function', 'function')

test('HTTP fallback generates canonical version 4 UUIDs that match saved answers', () => {
  const context = vm.createContext({ crypto: { getRandomValues: bytes => {
    bytes.fill(255)
    return bytes
  } } })
  vm.runInContext(source, context)
  const id = context.randomUUID()
  assert.equal(id, 'ffffffff-ffff-4fff-bfff-ffffffffffff')
  assert.equal(hasCompletedTurn([{ id, role: 'user' }, { id: 'answer', role: 'assistant' }], id), true)
})

test('secure contexts retain native UUID generation', () => {
  const context = vm.createContext({ crypto: { randomUUID: () => 'native-uuid' } })
  vm.runInContext(source, context)
  assert.equal(context.randomUUID(), 'native-uuid')
})
