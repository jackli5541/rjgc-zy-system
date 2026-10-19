import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { applyFeedbackSuggestion, hasFeedbackContent } from '../src/modules/ai_grading/feedbackSuggestion.js'

async function setup(t) {
  const requests = []
  globalThis.singleAiTestApi = (path, options) => new Promise((resolve, reject) => requests.push({ path, options, resolve, reject }))
  const source = (await readFile(new URL('../src/modules/ai_grading/composables/useSingleAiGrading.js', import.meta.url), 'utf8'))
    .replace("import { api } from '../../../api'", 'const api = (...args) => globalThis.singleAiTestApi(...args)')
    .replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
  const { useSingleAiGrading } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
  let target = { assignmentId: 'assignment', versionId: 'first' }
  const state = useSingleAiGrading(() => target)
  t.mock.timers.enable({ apis: ['setTimeout'] })
  t.after(() => { state.reset(); delete globalThis.singleAiTestApi })
  return { state, requests, setTarget: value => { target = value; state.reset() } }
}

const flush = () => new Promise(resolve => setImmediate(resolve))

test('first status refresh occurs within 750ms rather than adding a long fixed wait', async t => {
  const { state, requests } = await setup(t)
  const started = state.start()
  requests[0].resolve({ status: 'PROCESSING', phase: 'QUEUED' })
  await started
  t.mock.timers.tick(749)
  assert.equal(requests.length, 1)
  t.mock.timers.tick(1)
  assert.equal(requests.length, 2)
  requests[1].resolve({ draft: { status: 'PROCESSING', phase: 'GENERATING' } })
  await flush()
  assert.equal(state.phase.value, 'GENERATING')
})

test('adopting changes only editable grade and comment, escapes HTML, and preserves annotations and draft status', () => {
  const annotations = [{ id: 'annotation', comment: '保留批注' }]
  const feedback = { status: 'DRAFT', revision: 3, grade: 'C', comment: '<p>手工评语</p>', annotations }
  assert.equal(hasFeedbackContent(feedback), true)
  applyFeedbackSuggestion(feedback, { suggested_grade: 'A', suggested_comment: '<script>alert(1)</script> &\n第二行' })
  assert.equal(feedback.grade, 'A')
  assert.equal(feedback.comment, '&lt;script&gt;alert(1)&lt;/script&gt; &amp;<br>第二行')
  assert.equal(feedback.annotations, annotations)
  assert.equal(feedback.status, 'DRAFT')
  assert.equal(feedback.revision, 3)
  assert.equal(hasFeedbackContent({ comment: '<p><br>&nbsp;</p>' }), false)
  assert.equal(hasFeedbackContent({ grade: 'B', comment: '' }), true)
  assert.equal(hasFeedbackContent({ comment: '<p>保留</p>' }), true)
})

test('only an explicit click creates one task; polling stops when ready and never publishes', async t => {
  const { state, requests } = await setup(t)
  assert.equal(requests.length, 0)
  const started = state.start()
  await state.start()
  assert.equal(requests.length, 1)
  assert.equal(requests[0].path, '/assignments/assignment/submissions/first/ai-grading-draft/retry')
  assert.equal(requests[0].options.method, 'POST')
  requests[0].resolve({ status: 'PROCESSING' })
  await started
  t.mock.timers.tick(1500)
  assert.equal(requests[1].options, undefined)
  requests[1].resolve({ draft: { status: 'READY', suggested_grade: 'A', suggested_comment: '完成良好' } })
  await flush()
  assert.equal(state.loading.value, false)
  assert.equal(state.animate.value, true)
  assert.equal(state.draft.value.suggested_grade, 'A')
  t.mock.timers.tick(15000)
  assert.equal(requests.length, 2)
})

test('switching students ignores old responses and does not generate for the next student', async t => {
  const { state, requests, setTarget } = await setup(t)
  const first = state.start()
  setTarget({ assignmentId: 'assignment', versionId: 'second' })
  requests[0].resolve({ status: 'PROCESSING' })
  await first
  t.mock.timers.tick(5000)
  assert.equal(requests.length, 1)
  assert.equal(state.visible.value, false)
  const second = state.start()
  assert.ok(requests[1].path.includes('/second/'))
  requests[1].resolve({ status: 'READY', suggested_grade: 'B' })
  await second
  assert.equal(state.draft.value.suggested_grade, 'B')
  assert.equal(state.animate.value, false)
})

test('closing cancels scheduled polling and discards an in-flight poll', async t => {
  const { state, requests, setTarget } = await setup(t)
  const started = state.start()
  requests[0].resolve({ status: 'PROCESSING' })
  await started
  t.mock.timers.tick(1500)
  setTarget(null)
  requests[1].resolve({ draft: { status: 'READY', suggested_grade: 'A' } })
  await flush()
  assert.equal(state.draft.value, null)
  assert.equal(state.loading.value, false)
  t.mock.timers.tick(5000)
  assert.equal(requests.length, 2)
  await state.start()
  assert.equal(requests.length, 2)
})

test('failed generation and network errors allow explicit retry', async t => {
  const { state, requests } = await setup(t)
  const first = state.start()
  requests[0].resolve({ status: 'FAILED', error_message: '模型不可用' })
  await first
  assert.equal(state.error.value, '模型不可用')
  assert.equal(state.loading.value, false)
  const second = state.start()
  requests[1].reject(new Error('网络中断'))
  await second
  assert.equal(state.error.value, '网络中断')
  const third = state.start()
  requests[2].resolve({ status: 'READY', suggested_grade: 'C' })
  await third
  assert.equal(state.error.value, '')
  assert.equal(state.draft.value.suggested_grade, 'C')
})

test('reset clears a pending timer before it can poll', async t => {
  const { state, requests } = await setup(t)
  const started = state.start()
  requests[0].resolve({ status: 'PROCESSING' })
  await started
  state.reset()
  t.mock.timers.tick(5000)
  assert.equal(requests.length, 1)
})

test('a stalled request times out at 180 seconds and ignores its late response', async t => {
  const { state, requests } = await setup(t)
  const started = state.start()
  t.mock.timers.tick(180000)
  assert.equal(state.loading.value, false)
  assert.match(state.error.value, /180/)
  requests[0].resolve({ status: 'READY', suggested_grade: 'A' })
  await started
  assert.equal(state.draft.value, null)
  const retried = state.start()
  requests[1].resolve({ status: 'READY', suggested_grade: 'B' })
  await retried
  assert.equal(state.draft.value.suggested_grade, 'B')
})

test('queue and generation phases come from server state, failed jobs stop polling', async t => {
  const { state, requests } = await setup(t)
  const started = state.start()
  requests[0].resolve({ status: 'PROCESSING', phase: 'QUEUED' })
  await started
  assert.equal(state.phase.value, 'QUEUED')
  t.mock.timers.tick(1500)
  requests[1].resolve({ draft: { status: 'PROCESSING', phase: 'GENERATING' } })
  await flush()
  assert.equal(state.phase.value, 'GENERATING')
  t.mock.timers.tick(1500)
  requests[2].resolve({ draft: { status: 'FAILED', error_message: '后台批改任务失败，请重试' } })
  await flush()
  assert.equal(state.loading.value, false)
  assert.match(state.error.value, /后台/)
  t.mock.timers.tick(180000)
  assert.equal(requests.length, 3)
  assert.match(state.error.value, /后台/)
})
