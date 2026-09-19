import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'

const MAX_MARKDOWN_BYTES = 500 * 1024 * 1024
const SAFE_IMAGE_DATA_URL = /^data:image\/(?:png|jpeg|gif|webp);base64,[a-z0-9+/=\s]+$/i
const markdown = new MarkdownIt({ html: true, linkify: true, typographer: false })

function prepareTaskItems(source) {
  return source.replace(/^(\s*[-*]\s+)\[([ xX])\]\s+/gm, (_, prefix, checked) => (
    `${prefix}<input type="checkbox" disabled${checked.toLowerCase() === 'x' ? ' checked' : ''}> `
  ))
}

function secureUrls(container) {
  container.querySelectorAll('a').forEach(link => {
    const href = link.getAttribute('href') || ''
    if (!/^(?:https:\/\/|mailto:)/i.test(href)) link.removeAttribute('href')
    else {
      link.setAttribute('target', '_blank')
      link.setAttribute('rel', 'noopener noreferrer')
    }
  })
  container.querySelectorAll('img').forEach(image => {
    const src = image.getAttribute('src') || ''
    if (!/^(?:http:\/\/|https:\/\/)/i.test(src) && !SAFE_IMAGE_DATA_URL.test(src)) image.removeAttribute('src')
  })
}

export function renderMarkdown(source) {
  const rendered = markdown.render(prepareTaskItems(source))
  const clean = DOMPurify.sanitize(rendered, {
    USE_PROFILES: { html: true },
    ADD_DATA_URI_TAGS: ['img'],
    ADD_ATTR: ['width', 'height'],
    FORBID_TAGS: ['style', 'script', 'iframe', 'object', 'embed', 'form'],
    FORBID_ATTR: ['style'],
    ALLOW_DATA_ATTR: false
  })
  const template = document.createElement('template')
  template.innerHTML = clean
  secureUrls(template.content)
  return template.innerHTML
}

export async function loadMarkdownPreview(url) {
  const response = await fetch(url)
  if (!response.ok) throw new Error('Markdown 文件加载失败')
  const announcedSize = Number(response.headers.get('content-length') || 0)
  if (announcedSize > MAX_MARKDOWN_BYTES) throw new Error('Markdown 文件超过 500 MB，无法在线预览')
  const content = await response.blob()
  if (content.size > MAX_MARKDOWN_BYTES) throw new Error('Markdown 文件超过 500 MB，无法在线预览')
  let source
  try { source = new TextDecoder('utf-8', { fatal: true }).decode(await content.arrayBuffer()) }
  catch (_) { throw new Error('Markdown 文件必须使用 UTF-8 编码') }
  return renderMarkdown(source)
}
