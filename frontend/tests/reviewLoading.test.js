import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createRenderer, h, nextTick, reactive, ref } from 'vue'

const flush = async () => { await nextTick(); await new Promise(resolve => setImmediate(resolve)) }
const file = id => ({ id, name: `${id}.md`, previewable: true, render_type: 'RICH_TEXT' })
let mountId = 0

// Run the actual SFC setup and Vue lifecycle without a browser or E2E runner.
async function mountReview(overrides = {}) {
  const requests = []
  const markdownRequests = []
  const errors = []
  const pending = list => (path, options = {}) => new Promise((resolve, reject) => list.push({ path, options, resolve, reject }))
  const previous = { window: globalThis.window, document: globalThis.document }
  globalThis.window = { innerWidth: 1600, innerHeight: 1000, getSelection: () => null, addEventListener() {}, removeEventListener() {} }
  globalThis.document = { documentElement: { classList: { toggle() {}, remove() {} } }, addEventListener() {}, removeEventListener() {} }
  globalThis.reviewTestServices = { api: pending(requests), loadMarkdownPreview: pending(markdownRequests), message: { error: value => errors.push(value) } }
  const source = await readFile(new URL('../src/modules/assignments/components/FileReviewDrawer.vue', import.meta.url), 'utf8')
  const script = compileScript(parse(source).descriptor, { id: 'review-loading-test' }).content
    .replace(/^import (.+) from '([^']+)'/gm, (_, bindings, path) => {
      if (path === 'vue') return `import ${bindings} from '${import.meta.resolve('vue')}'`
      if (path.endsWith('/api')) return 'const { api } = globalThis.reviewTestServices; const exportArchive = api; const randomUUID = () => "test-id"'
      if (path.endsWith('/markdownPreview')) return 'const { loadMarkdownPreview } = globalThis.reviewTestServices'
      if (path === 'ant-design-vue') return 'const { message } = globalThis.reviewTestServices'
      if (path.endsWith('/useHorizontalResize')) return 'const useResizableDrawer = () => ({ width: ref(1200), resizing: ref(false), startResize() {} }); const useResizableRightPane = () => ({ width: ref(400), resizing: ref(false), resizeBy() {}, startResize() {} })'
      return `const ${bindings} = {}`
    })
  const component = (await import(`data:text/javascript;base64,${Buffer.from(script).toString('base64')}#${++mountId}`)).default
  let state
  const review = { ...component, setup(props, context) { state = component.setup(props, context); return () => null } }
  const props = reactive({ open: true, files: [file('first'), file('second')], submissionVersionId: 'version-1', ...overrides })
  const renderer = createRenderer({
    createComment: () => ({}), createText: () => ({}), createElement: () => ({}),
    insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {}, parentNode() {}, nextSibling() {}
  })
  const app = renderer.createApp({ setup: () => () => h(review, props) })
  app.mount({})
  await flush()
  return {
    props, state, requests, markdownRequests, errors,
    close() {
      app.unmount()
      Object.assign(globalThis, previous)
      delete globalThis.reviewTestServices
    }
  }
}

test('first mount while open loads the selected document and feedback once; reopening reloads once', async () => {
  const review = await mountReview({ initialIndex: 1 })
  try {
    const { props, state, requests, markdownRequests } = review
    assert.deepEqual(requests.map(item => item.path), ['/files/second/preview-url', '/submission-versions/version-1/feedback'])
    requests[0].resolve({ url: '/second.md' })
    requests[1].resolve({ grade: 'A', status: 'PUBLISHED', comment: '评语' })
    await flush()
    markdownRequests[0].resolve('<h1>学生作业</h1>')
    await flush()
    assert.equal(state.richHtml.value, '<h1>学生作业</h1>')
    assert.equal(state.feedback.grade, 'A')
    props.files = props.files.map(item => ({ ...item, preview_status: 'READY' }))
    await flush()
    assert.equal(requests.length, 2)
    props.open = false
    await flush()
    assert.equal(state.loading.value, false)
    props.initialIndex = 0
    props.open = true
    await flush()
    assert.deepEqual(requests.slice(2).map(item => item.path), ['/files/first/preview-url', '/submission-versions/version-1/feedback'])
  } finally { review.close() }
})

test('switching students cancels old loads, selects the first file, and ignores late document and feedback results', async () => {
  const review = await mountReview({ initialIndex: 1 })
  try {
    const { props, state, requests, markdownRequests, errors } = review
    requests[0].resolve({ url: '/old.md' })
    await flush()
    props.submissionVersionId = 'version-2'
    props.files = [file('new-first'), file('new-second')]
    await flush()
    assert.equal(requests[0].options.signal.aborted, true)
    assert.equal(markdownRequests[0].options.signal.aborted, true)
    assert.equal(requests[1].options.signal.aborted, true)
    assert.deepEqual(requests.slice(2).map(item => item.path), ['/files/new-first/preview-url', '/submission-versions/version-2/feedback'])
    requests[2].resolve({ url: '/new.md' })
    requests[3].resolve({ status: 'DRAFT', grade: 'B', comment: '新同学评语' })
    await flush()
    markdownRequests[1].resolve('<h1>新同学作业</h1>')
    await flush()
    // Simulate a transport that resolves despite cancellation.
    markdownRequests[0].resolve('<h1>旧同学作业</h1>')
    requests[1].resolve({ status: 'PUBLISHED', grade: 'E', comment: '旧同学评语' })
    await flush()
    assert.equal(state.richHtml.value, '<h1>新同学作业</h1>')
    assert.equal(state.feedback.comment, '新同学评语')
    assert.equal(state.loading.value, false)
    assert.deepEqual(errors, [])
  } finally { review.close() }
})

test('removing files or closing during a request clears loading and prevents obsolete preview fetches', async () => {
  const review = await mountReview()
  try {
    const { props, state, requests, markdownRequests } = review
    assert.equal(state.loading.value, true)
    props.files = []
    await flush()
    assert.equal(state.loading.value, false)
    assert.equal(requests[0].options.signal.aborted, true)
    requests[0].resolve({ url: '/obsolete.md' })
    await flush()
    assert.equal(markdownRequests.length, 0)
    props.open = false
    await flush()
    assert.equal(requests[1].options.signal.aborted, true)
  } finally { review.close() }
})

test('a failed preview clears loading and can be retried without reopening the drawer', async () => {
  const review = await mountReview()
  try {
    const { state, requests, markdownRequests } = review
    requests[0].reject(new Error('文件服务暂时不可用'))
    await flush()
    assert.equal(state.loading.value, false)
    assert.equal(state.error.value, '文件服务暂时不可用')
    const retry = state.loadFile()
    assert.equal(state.error.value, '')
    assert.equal(state.loading.value, true)
    requests[2].resolve({ url: '/retry.md' })
    await flush()
    markdownRequests[0].resolve('<p>重新加载成功</p>')
    await retry
    assert.equal(state.richHtml.value, '<p>重新加载成功</p>')
    assert.equal(state.loading.value, false)
  } finally { review.close() }
})

test('continue grading navigates immediately and fetches the submission board only once in the detail loader', async () => {
  const assignment = { id: 'assignment-1', class_id: 'class-1' }
  const record = { submission_version_id: 'version-1', status: 'SUBMITTED', files: [file('first')] }
  const requests = []
  const navigations = []
  const opened = []
  globalThis.assignmentReviewTestApi = async path => {
    requests.push(path)
    if (path.startsWith('/assignments?')) return { items: [assignment] }
    if (path.endsWith('/submissions')) return { items: [record] }
    return { attachments: [], review_criteria: [], drafts: [] }
  }
  try {
    const source = (await readFile(new URL('../src/modules/assignments/composables/useAssignmentDetail.js', import.meta.url), 'utf8'))
      .replace("import { api } from '../../../api'", 'const api = globalThis.assignmentReviewTestApi')
      .replace("import { Modal, message } from 'ant-design-vue'", 'const Modal = {}; const message = { error() {}, info() {} }')
      .replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
    const { useAssignmentDetail } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
    const ctx = {
      role: ref('TEACHER'), classId: ref('class-1'), detailId: ref('assignment-1'), assignments: ref([]),
      selectedCampaign: ref(null), assignmentAttachments: ref([]), reviewCriteriaFiles: ref([]), draftFiles: ref([]),
      route: { query: { tab: 'submission', grade_submission: 'next' } }, router: { push: async route => navigations.push(route) },
      openAssessmentDrawer: (...args) => opened.push(args)
    }
    const detail = useAssignmentDetail(ctx)
    await detail.continueGrading(assignment)
    assert.equal(requests.length, 0)
    assert.equal(navigations[0].query.grade_submission, 'next')
    await detail.loadAssignmentDetailView(() => true)
    assert.equal(requests.filter(path => path.endsWith('/submissions')).length, 1)
    assert.equal(opened.length, 1)
    assert.equal(opened[0][0].submission_version_id, 'version-1')
    assert.equal(opened[0][1].pendingOnly, true)
  } finally { delete globalThis.assignmentReviewTestApi }
})
