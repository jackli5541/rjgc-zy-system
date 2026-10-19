import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { compileScript, parse } from '@vue/compiler-sfc'
import { reactive, ref, watch } from 'vue'
import { selectionActionPosition } from '../src/shared/aiSelectionPosition.js'

const size = { width: 124, height: 38 }
const viewport = { width: 1200, height: 800 }

test('keeps the selection action next to its selection when clear of chat', () => {
  assert.deepEqual(selectionActionPosition({ left: 600, top: 200 }, size, viewport, { left: 8, top: 8, right: 440, bottom: 600 }), { left: 600, top: 200, behindChat: false })
})

test('avoids chat on each viewport edge when initially positioned', () => {
  for (const chat of [
    { left: 8, top: 8, right: 540, bottom: 680 },
    { left: 660, top: 8, right: 1192, bottom: 680 },
    { left: 8, top: 8, right: 1192, bottom: 450 },
    { left: 8, top: 350, right: 1192, bottom: 792 },
    { left: 300, top: 150, right: 900, bottom: 700 }
  ]) {
    const result = selectionActionPosition({ left: chat.left + 40, top: chat.top + 100 }, size, viewport, chat)
    assert.equal(result.behindChat, false)
    assert.ok(result.left >= 8 && result.top >= 8)
    assert.ok(result.left + size.width <= viewport.width - 8)
    assert.ok(result.top + size.height <= viewport.height - 8)
    assert.ok(result.left >= chat.right + 8 || result.left + size.width <= chat.left - 8 || result.top >= chat.bottom + 8 || result.top + size.height <= chat.top - 8)
  }
})

test('keeps chat unobstructed when it fills a narrow viewport', () => {
  const result = selectionActionPosition({ left: 20, top: 150 }, size, { width: 360, height: 640 }, { left: 12, top: 12, right: 348, bottom: 628 })
  assert.equal(result.behindChat, true)
})

test('keeps the action available without an open chat', () => {
  assert.deepEqual(selectionActionPosition({ left: 1190, top: -20 }, size, viewport), { left: 1068, top: 8, behindChat: false })
})

test('selection action follows its text on scroll, hides offscreen and returns when text becomes visible', () => {
  const source = readFileSync(new URL('../src/shared/components/AiTeacherSelectionAction.vue', import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  const script = compileScript(descriptor, { id: 'selection-action-test' })
  const code = script.scriptSetupAst.filter(node => node.type !== 'ImportDeclaration')
    .map(node => descriptor.scriptSetup.content.slice(node.start, node.end)).join('\n')
  let chat = { left: 8, top: 8, right: 540, bottom: 680 }
  let chatReads = 0
  let mounted
  let unmounted
  let stopWatching
  let header = null
  let toolbar = null
  const listeners = new Map()
  let rangeRect = { left: 100, right: 200, top: 246, bottom: 270, width: 100, height: 24 }
  let extraRects = []
  const range = {
    startContainer: { isConnected: true, parentElement: { closest: () => ({ querySelector: () => toolbar }) } },
    getClientRects: () => [rangeRect, ...extraRects]
  }
  const props = reactive({ selectionId: 'document:1:5', position: { left: 100, top: 200, range } })
  const browser = {
    innerWidth: 1200, innerHeight: 800,
    getComputedStyle: element => ({ position: element.position || 'sticky', display: 'block', visibility: 'visible' }),
    addEventListener: (type, callback) => listeners.set(type, callback),
    removeEventListener: (type, callback) => { if (listeners.get(type) === callback) listeners.delete(type) }
  }
  const context = vm.createContext({
    selectionActionPosition, window: browser,
    document: { querySelector: selector => {
      if (selector === '.app-header') return header
      chatReads += 1
      return { getBoundingClientRect: () => chat }
    } },
    defineProps: () => props, defineEmits: () => () => {},
    ref, watch: (source, callback) => { stopWatching = watch(source, callback, { flush: 'sync' }) },
    onMounted: callback => { mounted = callback }, onBeforeUnmount: callback => { unmounted = callback },
    mockButton: { getBoundingClientRect: () => size },
    requestAnimationFrame: () => { throw new Error('Must not follow chat each frame') }
  })
  vm.runInContext(code, context)
  vm.runInContext('button.value = mockButton', context)
  mounted()
  const position = () => JSON.parse(vm.runInContext('JSON.stringify(style.value)', context))
  const initial = position()
  assert.equal(initial.left, '548px')
  chat = { left: 500, top: 8, right: 1100, bottom: 740 }
  assert.deepEqual(position(), initial)
  // Moving chat does not change the offset from the selected text.
  listeners.get('resize')()
  assert.deepEqual(position(), initial)
  assert.equal(chatReads, 1)
  rangeRect = { ...rangeRect, top: 146, bottom: 170 }
  listeners.get('scroll')()
  assert.equal(position().top, '100px')
  assert.equal(position().left, initial.left)
  assert.equal(chatReads, 1)
  rangeRect = { ...rangeRect, top: -100, bottom: -76 }
  listeners.get('scroll')()
  assert.equal(position().visibility, 'hidden')
  rangeRect = { ...rangeRect, top: 900, bottom: 924 }
  listeners.get('scroll')()
  assert.equal(position().visibility, 'hidden')
  rangeRect = { ...rangeRect, top: 246, bottom: 270 }
  listeners.get('scroll')()
  assert.deepEqual(position(), initial)
  props.position = { left: 600, top: 220, range }
  assert.deepEqual(position(), initial)
  assert.equal(chatReads, 1)
  props.position.top = 300
  assert.deepEqual(position(), initial)
  rangeRect = { ...rangeRect, left: 600, right: 700 }
  props.selectionId = 'document:8:12'
  assert.equal(chatReads, 2)
  header = { getBoundingClientRect: () => ({ top: 0, bottom: 140 }) }
  toolbar = { getBoundingClientRect: () => ({ top: 150, bottom: 210 }) }
  rangeRect = { ...rangeRect, top: 240, bottom: 264 }
  listeners.get('scroll')()
  assert.equal(position().visibility, 'hidden', 'hide when the button enters the toolbar even while the text is visible')
  rangeRect = { ...rangeRect, top: 180, bottom: 204 }
  listeners.get('scroll')()
  assert.equal(position().visibility, 'hidden', 'hide text covered by the toolbar before it reaches browser top')
  rangeRect = { ...rangeRect, top: 300, bottom: 324 }
  listeners.get('scroll')()
  assert.equal(position().visibility, undefined, 'restore when text and button clear the toolbar')
  toolbar = null
  rangeRect = { ...rangeRect, top: 200, bottom: 224 }
  listeners.get('scroll')()
  assert.equal(position().visibility, undefined, 'requirements without an editor toolbar use only the header')
  rangeRect = { ...rangeRect, top: 160, bottom: 184 }
  listeners.get('scroll')()
  assert.equal(position().visibility, 'hidden', 'button must not overlap the fixed header')
  extraRects = [{ ...rangeRect, top: 300, bottom: 324 }]
  listeners.get('scroll')()
  assert.equal(position().visibility, 'hidden', 'do not keep a button above the header for a partly visible line')
  rangeRect = { ...rangeRect, top: 110, bottom: 134 }
  listeners.get('scroll')()
  assert.equal(position().visibility, undefined, 'multiline selections can anchor to a line below the header')
  extraRects = []
  header = null
  assert.notDeepEqual(position(), initial)
  browser.innerWidth = 400
  listeners.get('resize')()
  assert.equal(position().visibility, 'hidden')
  rangeRect = { ...rangeRect, left: 250, right: 350 }
  listeners.get('resize')()
  assert.ok(parseFloat(position().left) + size.width <= 392)
  assert.equal(chatReads, 2)
  props.position.range.startContainer.isConnected = false
  listeners.get('scroll')()
  assert.equal(position().visibility, 'hidden')
  unmounted()
  stopWatching()
  assert.equal(listeners.size, 0)
  const css = descriptor.styles.map(item => item.content).join('\n')
  assert.match(css, /z-index:969/)
})
