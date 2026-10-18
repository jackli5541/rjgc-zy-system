import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'

const flush = () => new Promise(resolve => setImmediate(resolve))
let moduleId = 0
const loadSource = source => import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}#${++moduleId}`)

function mockDocument(t) {
  const previous = { document: globalThis.document, CSS: globalThis.CSS }
  const artifacts = []
  globalThis.CSS = { escape: value => value }
  globalThis.document = {
    getElementById: () => null,
    body: { querySelector: () => null },
    querySelectorAll: () => artifacts,
    createElement: () => ({
      innerHTML: '', children: [], listeners: {},
      setAttribute() {}, append(...nodes) { this.children.push(...nodes) },
      addEventListener(name, callback) { this.listeners[name] = callback },
      querySelector() { return null }
    })
  }
  t.after(() => Object.assign(globalThis, previous))
  return artifacts
}

test('unchanged chart nodes do not redraw on editor transactions; source changes and stale results are handled', async t => {
  mockDocument(t)
  const requests = []
  globalThis.nodeViewRenderTest = source => new Promise(resolve => requests.push({ source, resolve }))
  t.after(() => delete globalThis.nodeViewRenderTest)
  const source = (await readFile(new URL('../src/shared/editor/mermaidNodeView.js', import.meta.url), 'utf8'))
    .replace("import { renderMermaid } from '../../mermaidRenderer'", 'const renderMermaid = globalThis.nodeViewRenderTest')
  const { createMermaidNodeView } = await loadSource(source)
  const node = source => ({ type: { name: 'mermaidBlock' }, attrs: { source }, nodeSize: 1 })
  const view = createMermaidNodeView({ node: node('graph TD; A-->B'), getPos: () => 0, editor: {}, onEdit() {}, onZoom() {} })
  const preview = view.dom.children[0]
  for (let i = 0; i < 100; i += 1) assert.equal(view.update(node('graph TD; A-->B')), true)
  assert.equal(requests.length, 1)
  assert.equal(view.ignoreMutation({ type: 'childList' }), true)
  assert.equal(view.ignoreMutation({ type: 'selection' }), false)
  view.update(node('graph TD; B-->C'))
  requests[1].resolve({ svg: '<svg>new chart</svg>' })
  await flush()
  requests[0].resolve({ svg: '<svg>old chart</svg>' })
  await flush()
  assert.equal(preview.innerHTML, '<svg>new chart</svg>')
  view.update(node('graph TD; B-->C'))
  assert.equal(preview.innerHTML, '<svg>new chart</svg>')
  assert.equal(requests.length, 2)
  view.update(node('graph TD; C-->D'))
  view.destroy()
  const before = preview.innerHTML
  requests[2].resolve({ svg: '<svg>destroyed chart</svg>' })
  await flush()
  assert.equal(preview.innerHTML, before)
})

async function mockRenderer(t) {
  const artifacts = mockDocument(t)
  const requests = []
  globalThis.mermaidRenderTest = { initialize() {}, render: (id, source) => new Promise((resolve, reject) => requests.push({ id, source, resolve, reject })) }
  t.after(() => delete globalThis.mermaidRenderTest)
  const source = (await readFile(new URL('../src/mermaidRenderer.js', import.meta.url), 'utf8'))
    .replace("import mermaid from 'mermaid'", 'const mermaid = globalThis.mermaidRenderTest')
  return { ...await loadSource(source), requests, artifacts }
}

test('duplicate chart renders share one layout and cache results with independent SVG references', async t => {
  const { renderMermaid, cleanupMermaidArtifacts, requests, artifacts } = await mockRenderer(t)
  const first = renderMermaid('graph TD; A-->B', 'first')
  const second = renderMermaid('graph TD; A-->B', 'second')
  assert.equal(requests.length, 1)
  let removed = false
  artifacts.push({ id: `d${requests[0].id}`, remove() { removed = true } })
  cleanupMermaidArtifacts()
  assert.equal(removed, false, 'unmounting another editor must not remove an active render container')
  requests[0].resolve({ svg: `<svg id="${requests[0].id}" aria-labelledby="title"><style>#${requests[0].id} .edge{marker-end:url(#arrow)}</style><title id="title">图表</title><marker id="arrow"/><path marker-end="url(#arrow)"/><use href="#arrow"/></svg>` })
  const [a, b] = await Promise.all([first, second])
  assert.notEqual(a.svg, b.svg)
  for (const { svg } of [a, b]) {
    const arrow = svg.match(/<marker id="([^"]+)"/)[1]
    const title = svg.match(/<title id="([^"]+)"/)[1]
    const root = svg.match(/<svg id="([^"]+)"/)[1]
    assert.ok(svg.includes(`marker-end="url(#${arrow})"`))
    assert.ok(svg.includes(`marker-end:url(#${arrow})`))
    assert.ok(svg.includes(`href="#${arrow}"`))
    assert.ok(svg.includes(`aria-labelledby="${title}"`))
    assert.ok(svg.includes(`#${root} .edge`))
  }
  const cached = await renderMermaid('graph TD; A-->B', 'cached')
  assert.equal(requests.length, 1)
  assert.notEqual(cached.svg, a.svg)
})

test('render failures can retry and cache eviction stays bounded', async t => {
  const { renderMermaid, requests } = await mockRenderer(t)
  const failed = renderMermaid('retry')
  const failure = assert.rejects(failed, /temporary failure/)
  requests[0].reject(new Error('temporary failure'))
  await failure
  const retry = renderMermaid('retry')
  requests[1].resolve({ svg: '<svg id="retry"/>' })
  await retry
  for (let i = 0; i < 33; i += 1) {
    const rendering = renderMermaid(`chart-${i}`)
    requests.at(-1).resolve({ svg: '<svg id="chart"/>' })
    await rendering
  }
  const count = requests.length
  const evicted = renderMermaid('retry')
  assert.equal(requests.length, count + 1)
  requests.at(-1).resolve({ svg: '<svg id="retry"/>' })
  await evicted
})
