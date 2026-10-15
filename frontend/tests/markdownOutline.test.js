import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createRenderer, h, nextTick, reactive } from 'vue'

async function mountReader() {
  const previous = Object.fromEntries(['MutationObserver', 'requestAnimationFrame', 'cancelAnimationFrame', 'window'].map(key => [key, globalThis[key]]))
  const observers = []
  const frames = new Map()
  let frameId = 0
  globalThis.MutationObserver = class {
    constructor(callback) { this.callback = callback; observers.push(this) }
    observe(element, options) { this.element = element; this.options = options }
    disconnect() { this.disconnected = true }
  }
  globalThis.requestAnimationFrame = callback => { frames.set(++frameId, callback); return frameId }
  globalThis.cancelAnimationFrame = id => frames.delete(id)
  globalThis.window = { matchMedia: () => ({ matches: true }) }
  const source = await readFile(new URL('../src/shared/components/MarkdownReader.vue', import.meta.url), 'utf8')
  const script = compileScript(parse(source).descriptor, { id: 'outline-test' }).content
    .replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
    .replace(/^import (\w+) from '[^']+\.vue'/gm, 'const $1 = {}')
  const component = (await import(`data:text/javascript;base64,${Buffer.from(script).toString('base64')}`)).default
  let state
  const props = reactive({ html: '<h1>初始标题</h1>', outlineOpen: false })
  const renderer = createRenderer({
    createComment: () => ({}), createText: () => ({}), createElement: () => ({}),
    insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {}, parentNode() {}, nextSibling() {}
  })
  const reader = { ...component, setup(props, context) { state = component.setup(props, context); return () => null } }
  const app = renderer.createApp({ setup: () => () => h(reader, props) })
  app.mount({})
  let nodes = []
  let scrolledTo
  const viewport = {
    scrollTop: 30,
    querySelectorAll: () => nodes,
    getBoundingClientRect: () => ({ top: 100 }),
    scrollTo: options => { scrolledTo = options }
  }
  state.root.value = viewport
  await nextTick()
  await nextTick()
  const drainFrames = () => {
    while (frames.size) {
      const batch = [...frames.values()]
      frames.clear()
      batch.forEach(callback => callback())
    }
  }
  drainFrames()
  return {
    state, props, observers, viewport,
    get scrolledTo() { return scrolledTo },
    setNodes(value) { nodes = value },
    mutate() { observers[0].callback(); drainFrames() },
    close() { app.unmount(); assert.equal(observers[0].disconnected, true); Object.assign(globalThis, previous) }
  }
}

const heading = (tagName, textContent, top = 200) => ({ tagName, textContent, getBoundingClientRect: () => ({ top }), focus(options) { this.focusOptions = options } })

test('outline discovers a delayed editor mount and follows heading edits, insertion and deletion without HTML prop changes', async () => {
  const reader = await mountReader()
  try {
    assert.equal(reader.state.headings.value.length, 0)
    const title = heading('H1', '作业标题')
    const chapter = heading('H2', '设计章节')
    reader.setNodes([title, chapter])
    reader.mutate()
    assert.deepEqual(reader.state.headings.value.map(item => [item.text, item.depth]), [['作业标题', 0], ['设计章节', 1]])
    reader.state.toggle(0)
    assert.equal(reader.state.visibleHeadings.value.length, 1)
    reader.state.toggle(0)
    chapter.textContent = '修改后的章节'
    reader.setNodes([title, chapter, heading('H3', '新小节')])
    reader.mutate()
    assert.deepEqual(reader.state.headings.value.map(item => item.text), ['作业标题', '修改后的章节', '新小节'])
    reader.setNodes([title])
    reader.mutate()
    assert.equal(reader.state.headings.value.length, 1)
    assert.equal(reader.props.html, '<h1>初始标题</h1>')
  } finally { reader.close() }
})

test('opening the outline rescans headings and navigation scrolls only the document viewport', async () => {
  const reader = await mountReader()
  try {
    const chapter = heading('H2', '切换文档后的章节', 420)
    reader.setNodes([chapter])
    reader.props.outlineOpen = true
    await nextTick()
    await nextTick()
    assert.equal(reader.state.headings.value[0].text, '切换文档后的章节')
    reader.state.locate(0)
    assert.deepEqual(reader.scrolledTo, { top: 330, behavior: 'auto' })
    assert.deepEqual(chapter.focusOptions, { preventScroll: true })
  } finally { reader.close() }
})

test('outline leaves editable heading DOM and editor focus untouched and accounts for the sticky toolbar', async () => {
  const reader = await mountReader()
  try {
    const chapter = heading('H2', '编辑章节', 420)
    chapter.isContentEditable = true
    Object.defineProperty(chapter, 'tabIndex', { set() { assert.fail('outline must not mutate editor-owned heading attributes') } })
    chapter.focus = () => assert.fail('outline must not restore the editor caret')
    reader.viewport.querySelector = () => ({ getBoundingClientRect: () => ({ bottom: 162 }) })
    reader.setNodes([chapter])
    reader.mutate()
    reader.state.locate(0)
    assert.deepEqual(reader.scrolledTo, { top: 276, behavior: 'auto' })
    assert.equal(reader.state.active.value, 0)
  } finally { reader.close() }
})

test('navigation resolves replacement headings even before the scheduled DOM scan', async () => {
  const reader = await mountReader()
  try {
    const stale = heading('H2', '章节', 200)
    reader.setNodes([stale])
    reader.mutate()
    const replacement = heading('H2', '章节', 760)
    reader.setNodes([replacement])
    reader.state.locate(0)
    assert.deepEqual(reader.scrolledTo, { top: 670, behavior: 'auto' })
    assert.equal(stale.focusOptions, undefined)
    assert.deepEqual(replacement.focusOptions, { preventScroll: true })
  } finally { reader.close() }
})
