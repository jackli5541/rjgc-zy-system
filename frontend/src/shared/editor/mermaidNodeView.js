import { renderMermaid } from '../../mermaidRenderer'

export function createMermaidNodeView({ node, getPos, editor, onEdit, onZoom }) {
  const dom = document.createElement('div')
  dom.className = 'mermaid-document-block'
  dom.contentEditable = 'false'
  dom.tabIndex = 0
  dom.title = '点击编辑图表，按 Delete 删除'
  const preview = document.createElement('div')
  preview.className = 'mermaid-document-preview'
  const zoomButton = document.createElement('button')
  zoomButton.type = 'button'
  zoomButton.className = 'mermaid-zoom-button'
  zoomButton.textContent = '放大查看'
  zoomButton.setAttribute('aria-label', '放大查看 Mermaid 图表')
  const deleteButton = document.createElement('button')
  deleteButton.type = 'button'
  deleteButton.className = 'mermaid-delete-button'
  deleteButton.setAttribute('aria-label', '删除 Mermaid 图表')
  deleteButton.title = '删除图表'
  deleteButton.textContent = '删除'
  dom.append(preview, zoomButton, deleteButton)
  let currentNode = node
  let renderVersion = 0

  const draw = async source => {
    const version = ++renderVersion
    preview.innerHTML = '<span class="mermaid-document-loading">正在绘制图表...</span>'
    try {
      const { svg } = await renderMermaid(source, 'editor-block')
      if (version === renderVersion) preview.innerHTML = svg
    } catch (error) {
      if (version === renderVersion) preview.innerHTML = '<span class="mermaid-document-error">图表绘制失败，点击检查或重试</span>'
    }
  }
  const edit = () => onEdit(currentNode.attrs.source, getPos())
  const remove = () => {
    const position = getPos()
    if (typeof position !== 'number') return
    editor.view.dispatch(editor.state.tr.delete(position, position + currentNode.nodeSize))
    editor.commands.focus()
  }
  dom.addEventListener('click', event => { if (!event.target.closest('button')) edit() })
  zoomButton.addEventListener('click', event => {
    event.stopPropagation()
    const svg = preview.querySelector('svg')
    if (svg) onZoom(svg.outerHTML)
  })
  deleteButton.addEventListener('click', event => { event.stopPropagation(); remove() })
  dom.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); edit() }
    if (event.key === 'Delete' || event.key === 'Backspace') { event.preventDefault(); remove() }
  })
  draw(node.attrs.source)
  return {
    dom,
    update(nextNode) {
      if (nextNode.type.name !== 'mermaidBlock') return false
      const changed = nextNode.attrs.source !== currentNode.attrs.source
      currentNode = nextNode
      if (changed) draw(nextNode.attrs.source)
      return true
    },
    // The SVG is display-only DOM, never editable document content.
    ignoreMutation: mutation => mutation.type !== 'selection',
    stopEvent: () => true,
    destroy: () => { renderVersion += 1 }
  }
}
