import mermaid from 'mermaid'

let sequence = 0

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

export async function renderMermaid(source, context = 'diagram') {
  const id = `coursework-mermaid-${context}-${Date.now()}-${sequence++}`
  try {
    return await mermaid.render(id, source)
  } finally {
    cleanupRenderNodes(id)
  }
}

export function cleanupMermaidArtifacts() {
  document.querySelectorAll('[id^="dcoursework-mermaid-"],[id^="icoursework-mermaid-"]').forEach(element => element.remove())
}
