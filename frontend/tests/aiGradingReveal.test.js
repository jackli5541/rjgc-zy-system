import assert from 'node:assert/strict'
import test from 'node:test'
import vm from 'node:vm'
import { readFileSync } from 'node:fs'
import { parse as parseSfc, compileScript } from '@vue/compiler-sfc'
import { parse } from '@vue/compiler-dom'
import { createGradingReveal } from '../src/modules/ai_grading/gradingReveal.js'
import { applyFeedbackSuggestion, hasFeedbackContent, feedbackMatchesSuggestion, normalizeFeedbackText } from '../src/modules/ai_grading/feedbackSuggestion.js'

// Compiler DOM decodes entities without requiring a browser in these unit tests.
const textContent = html => {
  const text = node => node.type === 2 ? node.content : (node.children || []).map(text).join('')
  return text(parse(html, { onError() {}, whitespace: 'preserve' }))
}

test('adopted state ignores editor wrappers, entities, line breaks and annotations but notices edits', () => {
  const draft = { suggested_grade: 'A', suggested_comment: '第一行 & <示例>\n第二行 😀' }
  const feedback = { grade: 'A', comment: '<p>第一行 &amp; &lt;示例&gt;</p><p>第二行&nbsp;😀</p>', annotations: [{ id: 'keep' }], status: 'DRAFT' }
  const before = JSON.stringify(feedback)
  assert.equal(feedbackMatchesSuggestion(feedback, draft, textContent), true)
  assert.equal(JSON.stringify(feedback), before)
  feedback.grade = 'B'
  assert.equal(feedbackMatchesSuggestion(feedback, draft, textContent), false)
  feedback.grade = 'A'
  feedback.comment += '<p>教师补充</p>'
  assert.equal(feedbackMatchesSuggestion(feedback, draft, textContent), false)
  assert.equal(normalizeFeedbackText('<p>&#160;<br></p>', textContent), '')
  assert.equal(feedbackMatchesSuggestion({ grade: undefined, comment: '' }, draft, textContent), false)
})

function fixture() {
  let callback
  let output
  const reveal = createGradingReveal(value => { output = value }, next => { callback = next; return 1 }, () => { callback = null })
  return { reveal, get output() { return output }, step(time) { const next = callback; callback = null; next?.(time) }, pending() { return Boolean(callback) } }
}
const draft = { suggested_grade: 'A', analysis: { grade_reason: '理由'.repeat(15), review_points: ['第一条建议', '第二条建议', '第三条建议', '不展示的第四条'] }, suggested_comment: '完整总评😀' }

test('new results reveal reason, points then comment and finish keeps the full source unchanged', () => {
  const f = fixture()
  const original = JSON.stringify(draft)
  f.reveal.show(draft, true)
  assert.equal(f.output.reason, '')
  assert.equal(f.output.typing, true)
  f.step(0)
  f.step(50)
  assert.ok(f.output.reason.length > 0 && f.output.reason.length < draft.analysis.grade_reason.length)
  assert.deepEqual(f.output.points, [])
  assert.equal(f.output.comment, '')
  f.step(250)
  assert.ok(f.output.points.length > 0)
  f.reveal.finish()
  assert.equal(f.output.reason, draft.analysis.grade_reason)
  assert.deepEqual(f.output.points, draft.analysis.review_points.slice(0, 3))
  assert.equal(f.output.comment, draft.suggested_comment)
  assert.equal(f.output.typing, false)
  assert.equal(f.pending(), false)
  assert.equal(JSON.stringify(draft), original)
})

test('history and reduced motion display immediately; switching or canceling discards queued text', () => {
  const f = fixture()
  f.reveal.show(draft, false)
  assert.equal(f.output.comment, draft.suggested_comment)
  assert.equal(f.pending(), false)
  f.reveal.show(draft, true)
  f.step(0)
  f.reveal.cancel()
  const previous = f.output
  f.step(500)
  assert.equal(f.output, previous)
  const next = { analysis: { grade_reason: '新学生' }, suggested_comment: '新总评' }
  f.reveal.show(next, true)
  f.reveal.finish()
  assert.equal(f.output.reason, '新学生')
  assert.equal(f.output.comment, '新总评')
  f.reveal.show(null)
  assert.equal(f.output.reason, '')
  assert.equal(f.output.comment, '')
})

function componentFunctions(relativePath, names) {
  const source = readFileSync(new URL(relativePath, import.meta.url), 'utf8')
  const { descriptor } = parseSfc(source)
  const script = compileScript(descriptor, { id: relativePath })
  return script.scriptSetupAst.filter(node => node.type === 'FunctionDeclaration' && names.includes(node.id.name)).map(node => descriptor.scriptSetup.content.slice(node.start, node.end)).join('\n')
}

test('repeat adoption skips confirmation, edited feedback confirms and stale confirmation cannot affect next student', () => {
  const feedback = { grade: undefined, comment: '', status: 'DRAFT', annotations: [{ id: 'keep' }] }
  const suggestion = { status: 'READY', suggested_grade: 'A', suggested_comment: '完整建议' }
  const confirmations = []
  const state = vm.createContext({
    feedback, aiEnabled: { value: true }, saving: { value: false }, aiDraft: { value: suggestion },
    props: { assignmentId: 'assignment', submissionVersionId: 'student1' }, aiAdoptConfirmation: null,
    feedbackMatchesSuggestion: (current, next) => feedbackMatchesSuggestion(current, next, textContent),
    hasFeedbackContent, applyFeedbackSuggestion, message: { success() {} },
    Modal: { confirm(options) { confirmations.push(options); return { destroy() {} } } }
  })
  vm.runInContext(componentFunctions('../src/modules/assignments/components/FileReviewDrawer.vue', ['adoptAiSuggestion']), state)
  state.adoptAiSuggestion(suggestion)
  assert.equal(feedback.grade, 'A')
  assert.equal(feedback.comment, '完整建议')
  assert.equal(confirmations.length, 0)
  state.adoptAiSuggestion(suggestion)
  assert.equal(confirmations.length, 0)
  feedback.comment = '教师修改'
  state.adoptAiSuggestion(suggestion)
  assert.equal(confirmations.length, 1)
  assert.equal(feedback.comment, '教师修改')
  confirmations[0].onOk()
  assert.equal(feedback.comment, '完整建议')
  feedback.grade = 'B'
  state.adoptAiSuggestion(suggestion)
  state.props.submissionVersionId = 'student2'
  confirmations[1].onOk()
  assert.equal(feedback.grade, 'B')
  assert.equal(feedback.status, 'DRAFT')
  assert.deepEqual(feedback.annotations, [{ id: 'keep' }])
})

test('adoption during playback finishes display before emitting the complete original draft', () => {
  const events = []
  const props = { draft, disabled: false, adopted: false }
  const state = vm.createContext({
    props, displayed: { value: { typing: true } },
    reveal: { finish() { events.push('finish') }, cancel() { events.push('cancel') } },
    emit: (...args) => events.push(args)
  })
  vm.runInContext(componentFunctions('../src/modules/ai_grading/components/SingleAiGradingPanel.vue', ['adopt', 'retry']), state)
  state.adopt()
  assert.equal(events[0], 'finish')
  assert.equal(events[1][0], 'adopt')
  assert.equal(events[1][1], draft)
  props.adopted = true
  state.adopt()
  assert.equal(events.length, 2)
  state.retry()
  assert.equal(events[2], 'cancel')
  assert.deepEqual(events[3], ['retry'])
})

test('panel honors reduced motion changes and unmount removes listeners and animation frames', () => {
  const source = readFileSync(new URL('../src/modules/ai_grading/components/SingleAiGradingPanel.vue', import.meta.url), 'utf8')
  const { descriptor } = parseSfc(source)
  const props = { draft: { ...draft, status: 'READY' }, loading: false, error: '', animate: true }
  const watchers = []
  const cleanup = []
  let frame
  let motionListener
  const motion = {
    matches: false,
    addEventListener(_, callback) { motionListener = callback },
    removeEventListener(_, callback) { assert.equal(callback, motionListener); motionListener = null }
  }
  const state = vm.createContext({
    defineProps: () => props, defineEmits: () => () => {}, ref: value => ({ value }),
    watch(_, callback, options) { watchers.push(callback); if (options?.immediate) callback() },
    onBeforeUnmount: callback => cleanup.push(callback), window: { matchMedia: () => motion },
    createGradingReveal: callback => createGradingReveal(callback, next => { frame = next; return 1 }, () => { frame = null })
  })
  vm.runInContext(descriptor.scriptSetup.content.replace(/^import .+$/gm, '') + '\nglobalThis.getDisplay = () => displayed.value', state)
  assert.equal(state.getDisplay().typing, true)
  motion.matches = true
  motionListener({ matches: true })
  assert.equal(state.getDisplay().comment, draft.suggested_comment)
  assert.equal(frame, null)
  props.loading = true
  watchers.forEach(callback => callback())
  assert.equal(state.getDisplay().reason, '')
  props.loading = false
  watchers.forEach(callback => callback())
  assert.equal(state.getDisplay().comment, draft.suggested_comment)
  assert.equal(frame, null)
  motion.matches = false
  watchers.forEach(callback => callback())
  assert.ok(frame)
  cleanup.forEach(callback => callback())
  assert.equal(frame, null)
  assert.equal(motionListener, null)
})
