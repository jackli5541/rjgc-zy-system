import mermaid from 'mermaid'

let sequence = 0
const activeRenderIds = new Set()
const pending = new Map()
const cache = new Map()
const MAX_CACHE_ENTRIES = 32
const MAX_CACHE_CHARACTERS = 2 * 1024 * 1024
let cacheCharacters = 0

mermaid.initialize({
  startOnLoad: false,
  securityLevel: 'strict',
  theme: 'neutral',
  suppressErrorRendering: true
})

function cleanupRenderNodes(id) {
  document.getElementById(`d${id}`)?.remove()
  document.getElementById(`i${id}`)?.remove()
  document.body.querySelector(`:scope > #${CSS.escape(id)}`)?.remove()
}

function namespaceSvg(svg, prefix) {
  const ids = new Map([...svg.matchAll(/\sid=(["'])(.*?)\1/g)].map(match => [match[2], `${prefix}-${match[2]}`]))
  const reference = id => ids.get(id) || id
  let result = svg
    .replace(/(\s)id=(["'])(.*?)\2/g, (_, space, quote, id) => `${space}id=${quote}${reference(id)}${quote}`)
    .replace(/url\(\s*(["']?)#([^\s)'";]+)\1\s*\)/g, (_, quote, id) => `url(${quote}#${reference(id)}${quote})`)
    .replace(/(\s(?:href|xlink:href))=(["'])#(.*?)\2/g, (_, attr, quote, id) => `${attr}=${quote}#${reference(id)}${quote}`)
    .replace(/(\saria-(?:labelledby|describedby))=(["'])(.*?)\2/g, (_, attr, quote, value) => `${attr}=${quote}${value.split(/\s+/).map(reference).join(' ')}${quote}`)
  result = result.replace(/<style\b[^>]*>[\s\S]*?<\/style>/g, style => {
    for (const [id, replacement] of ids) {
      const escaped = id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      style = style.replace(new RegExp(`#${escaped}(?![\\w-])`, 'g'), `#${replacement}`)
    }
    return style
  })
  return result
}

function remember(source, svg) {
  const size = source.length + svg.length
  if (size > MAX_CACHE_CHARACTERS) return
  cache.set(source, svg)
  cacheCharacters += size
  while (cache.size > MAX_CACHE_ENTRIES || cacheCharacters > MAX_CACHE_CHARACTERS) {
    const oldest = cache.keys().next().value
    cacheCharacters -= oldest.length + cache.get(oldest).length
    cache.delete(oldest)
  }
}

async function draw(source) {
  const id = `coursework-mermaid-render-${sequence++}`
  activeRenderIds.add(id)
  try {
    const { svg } = await mermaid.render(id, source)
    remember(source, svg)
    return svg
  } finally {
    cleanupRenderNodes(id)
    activeRenderIds.delete(id)
  }
}

export async function renderMermaid(source, context = 'diagram') {
  let svg = cache.get(source)
  if (svg !== undefined) {
    cache.delete(source)
    cache.set(source, svg)
  } else {
    let request = pending.get(source)
    if (!request) {
      request = draw(source)
      pending.set(source, request)
    }
    try { svg = await request }
    finally { if (pending.get(source) === request) pending.delete(source) }
  }
  // Each placement needs its own SVG IDs, including markers, styles and ARIA
  // references, even when its expensive layout was shared with another view.
  return { svg: namespaceSvg(svg, `coursework-mermaid-${context}-${sequence++}`) }
}

export function cleanupMermaidArtifacts() {
  document.querySelectorAll('[id^="dcoursework-mermaid-"],[id^="icoursework-mermaid-"]').forEach(element => {
    if (!activeRenderIds.has(element.id.slice(1))) element.remove()
  })
}
