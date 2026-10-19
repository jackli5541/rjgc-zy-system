import assert from 'node:assert/strict'
import test from 'node:test'

import { findCompletedTurn, hasCompletedTurn, reconcileTurn } from '../src/modules/assignments/aiTeacherChat.js'

test('recognizes an answer committed when the done event was missed', () => {
  const messages = [
    { id: 'question-1', role: 'user' },
    { id: 'answer-1', role: 'assistant' }
  ]
  assert.equal(hasCompletedTurn(messages, 'question-1'), true)
  assert.equal(hasCompletedTurn(messages, 'another-question'), false)
  assert.deepEqual(reconcileTurn(messages, 'question-1', '我的问题', '引用'), {
    completed: true, input: '', quote: ''
  })
})

test('does not treat an unanswered question as a completed turn', () => {
  assert.equal(hasCompletedTurn([{ id: 'question-1', role: 'user' }], 'question-1'), false)
  assert.equal(hasCompletedTurn([
    { id: 'question-1', role: 'user' },
    { id: 'question-2', role: 'user' },
    { id: 'answer-2', role: 'assistant' }
  ], 'question-1'), false)
  assert.deepEqual(reconcileTurn([], 'question-1', '我的问题', '引用'), {
    completed: false, input: '我的问题', quote: '引用'
  })
})

test('matches legacy HTTP UUIDs with canonical IDs returned by the backend', () => {
  const messageId = '00112233445546778899aabbccddeeff'
  const messages = [
    { id: '00112233-4455-4677-8899-aabbccddeeff', role: 'user', content: '问题' },
    { id: 'answer-1', role: 'assistant', content: '回答' }
  ]
  assert.deepEqual(findCompletedTurn(messages, messageId), { user: messages[0], assistant: messages[1] })
  assert.equal(hasCompletedTurn(messages, messageId.toUpperCase()), true)
  assert.equal(reconcileTurn(messages, messageId, '问题', '').completed, true)
  assert.equal(hasCompletedTurn(messages, '00112233445546778899aabbccddee00'), false)
  assert.equal(findCompletedTurn(messages, ''), null)
})
