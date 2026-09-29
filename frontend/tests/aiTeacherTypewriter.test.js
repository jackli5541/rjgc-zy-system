import assert from 'node:assert/strict'
import test from 'node:test'
import { createTypewriter } from '../src/modules/assignments/aiTeacherTypewriter.js'

function fixture() {
  let callback
  const output = []
  const writer = createTypewriter(text => output.push(text), next => { callback = next; return 1 }, () => { callback = null })
  return { writer, output, step(time) { const next = callback; callback = null; next?.(time) }, pending() { return Boolean(callback) } }
}

test('reveals Unicode text progressively and finishes with the complete answer', () => {
  const f = fixture()
  f.writer.append('你好😀世界')
  f.step(0)
  assert.deepEqual(f.output, [])
  f.step(50)
  assert.equal(f.output.at(-1), '你好😀世界')
  f.writer.append('！')
  f.writer.finish()
  assert.equal(f.output.at(-1), '你好😀世界！')
  assert.equal(f.pending(), false)
})

test('accelerates a large backlog and limits rendering to 50ms intervals', () => {
  const f = fixture()
  f.writer.append('字'.repeat(200))
  f.step(0)
  f.step(50)
  assert.equal(f.output.at(-1).length, 30)
  f.step(66)
  assert.equal(f.output.length, 1)
  f.step(100)
  assert.ok(f.output.at(-1).length > 30)
})

test('cancel clears queued frames and text without replaying it', () => {
  const f = fixture()
  f.writer.append('旧回答')
  f.writer.cancel()
  f.step(100)
  assert.deepEqual(f.output, [])
  f.writer.append('新回答')
  f.writer.finish()
  assert.deepEqual(f.output, ['新回答'])
})
