import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { compileScript, parse } from '@vue/compiler-sfc'
import { findCompletedTurn, reconcileTurn } from '../src/modules/assignments/aiTeacherChat.js'

const { descriptor } = parse(readFileSync(new URL('../src/modules/assignments/components/AiTeacherDrawer.vue', import.meta.url), 'utf8'))
const sendNode = compileScript(descriptor, { id: 'completion' }).scriptSetupAst
  .find(node => node.type === 'FunctionDeclaration' && node.id.name === 'sendQuestion')
const sendSource = descriptor.scriptSetup.content.slice(sendNode.start, sendNode.end)
const localId = '00112233445546778899aabbccddeeff'
const savedUser = { id: '00112233-4455-4677-8899-aabbccddeeff', role: 'user', content: '问题' }
const savedAnswer = { id: 'answer-1', role: 'assistant', content: '完整回答' }

async function sendWithResponse(saved, { missingDone = false, trailingBoundary = true } = {}) {
  const errors = []
  let historyCalls = 0
  const frames = 'event: delta\ndata: {"text":"完整回答"}\n\n'
    + (missingDone ? '' : `event: done\ndata: ${JSON.stringify({ messages: saved })}${trailingBoundary ? '\n\n' : ''}`)
  const encoded = new TextEncoder().encode(frames)
  // Include byte boundaries inside Chinese text as well as event frames.
  const chunks = Array.from(encoded, byte => Uint8Array.of(byte))
  const context = vm.createContext({
    props: { open: true }, input: { value: '问题' }, loading: { value: false },
    sending: { value: false }, verifying: { value: false }, verificationPending: { value: false },
    assignmentId: { value: 'assignment-1' }, conversationId: { value: 'conversation-1' },
    selectedQuotes: { value: [] }, messages: { value: [] }, historyRequestId: 0,
    sendController: null, answerTypewriter: null, AbortController, TextDecoder,
    randomUUID: () => localId, reactive: value => value, emit: () => {},
    scrollToLatest: () => {}, renderAssistantContent: value => value, normalizeMessage: value => value,
    findCompletedTurn, reconcileTurn,
    createTypewriter: onText => {
      let text = ''
      return { append: value => { text += value; onText(text) }, finish: () => onText(text), cancel: () => {} }
    },
    apiStream: async () => ({ read: async () => chunks.length ? { value: chunks.shift(), done: false } : { done: true } }),
    api: async () => { historyCalls += 1; return { messages: saved } },
    message: { error: value => errors.push(value), warning: value => errors.push(value) }
  })
  vm.runInContext(sendSource, context)
  await context.sendQuestion()
  return { context, errors, historyCalls }
}

for (const trailingBoundary of [true, false]) {
  test(`done event accepts legacy UUIDs with trailing boundary=${trailingBoundary}`, async () => {
    const { context, errors, historyCalls } = await sendWithResponse([savedUser, savedAnswer], { trailingBoundary })
    assert.deepEqual(JSON.parse(JSON.stringify(context.messages.value)), [savedUser, savedAnswer])
    assert.equal(context.input.value, '')
    assert.equal(context.sending.value, false)
    assert.equal(historyCalls, 0)
    assert.deepEqual(errors, [])
  })
}

test('missed done event restores saved answers using legacy UUIDs', async () => {
  const { context, errors, historyCalls } = await sendWithResponse([savedUser, savedAnswer], { missingDone: true })
  assert.equal(historyCalls, 1)
  assert.equal(context.messages.value[1], savedAnswer)
  assert.equal(context.input.value, '')
  assert.equal(context.verificationPending.value, false)
  assert.deepEqual(errors, [])
})

test('incomplete answers still restore input and report failure', async () => {
  const { context, errors, historyCalls } = await sendWithResponse([savedUser])
  assert.equal(historyCalls, 1)
  assert.equal(context.messages.value.length, 0)
  assert.equal(context.input.value, '问题')
  assert.deepEqual(errors, ['回答记录不完整，请稍后重试'])
})
