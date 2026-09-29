import assert from 'node:assert/strict'
import test from 'node:test'

import { hasCompletedTurn, reconcileTurn } from '../src/modules/assignments/aiTeacherChat.js'

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
