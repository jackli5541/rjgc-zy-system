<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { CheckCircleFilled, CloudSyncOutlined, CodeOutlined, DownloadOutlined, EyeOutlined, FileTextOutlined, MenuFoldOutlined, MenuUnfoldOutlined, SaveOutlined, UndoOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { api } from '../api'
import { loadMarkdownPreview, renderMarkdown } from '../markdownPreview'
import RichTextEditor from './RichTextEditor.vue'
import RichTextViewer from './RichTextViewer.vue'

const props = defineProps({ assignmentId: String, writable: Boolean, canSubmit: Boolean, submitLabel: { type: String, default: '提交当前版本' } })
const emit = defineEmits(['ready', 'preview-criteria', 'submit'])
const loading = ref(false)
const documentLoading = ref(false)
const workspace = ref(null)
const activeId = ref('')
const loadedId = ref('')
const editorHtml = ref('')
const sourceMarkdown = ref('')
const editorMode = ref('visual')
const sidebarCollapsed = ref(false)
const criteriaPreview = ref(null)
const state = ref('idle')
const downloading = ref(false)
let savePromise
let pendingSave
let applying = false
let loadSequence = 0
const documentCache = new Map()
const lastSavedMarkdown = new Map()
const active = computed(() => workspace.value?.documents.find(item => item.id === activeId.value))

function inlineMarkdown(node) {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent.replace(/\\/g, '\\\\')
  if (node.nodeType !== Node.ELEMENT_NODE) return ''
  const content = [...node.childNodes].map(inlineMarkdown).join('')
  const tag = node.tagName.toLowerCase()
  if (tag === 'strong' || tag === 'b') return `**${content}**`
  if (tag === 'em' || tag === 'i') return `*${content}*`
  if (tag === 's') return `~~${content}~~`
  if (tag === 'code' && node.parentElement?.tagName !== 'PRE') return `\`${content}\``
  if (tag === 'a') return `[${content}](${node.getAttribute('href') || ''})`
  if (tag === 'img') {
    const alt = (node.getAttribute('alt') || '').replace(/"/g, '&quot;')
    const src = node.getAttribute('src') || ''
    const width = node.getAttribute('width')
    const height = node.getAttribute('height')
    const size = `${width ? ` width="${width}"` : ''}${height ? ` height="${height}"` : ''}`
    return size ? `<img src="${src}" alt="${alt}"${size}>` : `![${alt.replace(/]/g, '\\]')}](${src})`
  }
  if (tag === 'br') return '\n'
  return content
}

function htmlToMarkdown(value) {
  const root = document.createElement('div')
  root.innerHTML = value
  function tableCell(cell) {
    return [...cell.childNodes]
      .map(inlineMarkdown)
      .join('')
      .replace(/\r?\n+/g, '<br>')
      .replace(/\|/g, '\\|')
      .trim()
  }
  function markdownTable(table) {
    const rows = [...table.rows]
    if (!rows.length) return ''
    const width = Math.max(...rows.map(row => row.cells.length))
    const line = row => {
      const cells = [...row.cells].map(tableCell)
      while (cells.length < width) cells.push('')
      return `| ${cells.join(' | ')} |`
    }
    const separator = `| ${Array.from({ length: width }, () => '---').join(' | ')} |`
    return [line(rows[0]), separator, ...rows.slice(1).map(line)].join('\n')
  }
  function block(node, depth = 0) {
    if (node.nodeType === Node.TEXT_NODE) return node.textContent
    if (node.nodeType !== Node.ELEMENT_NODE) return ''
    const tag = node.tagName.toLowerCase()
    const inner = [...node.childNodes].map(child => block(child, depth)).join('')
    if (/^h[1-6]$/.test(tag)) return `${'#'.repeat(Number(tag[1]))} ${[...node.childNodes].map(inlineMarkdown).join('')}\n\n`
    if (tag === 'p') return `${[...node.childNodes].map(inlineMarkdown).join('')}\n\n`
    if (tag === 'blockquote') return `${inner.trim().split('\n').map(line => `> ${line}`).join('\n')}\n\n`
    if (tag === 'table') return `${markdownTable(node)}\n\n`
    if (tag === 'pre') {
      const language = node.querySelector(':scope > code')?.classList.contains('language-mermaid') ? 'mermaid' : ''
      return `\`\`\`${language}\n${node.textContent.replace(/\n$/, '')}\n\`\`\`\n\n`
    }
    if (tag === 'ul' || tag === 'ol') return `${[...node.children].map((child,index) => `${'  '.repeat(depth)}${tag === 'ol' ? `${index + 1}.` : '-'} ${[...child.childNodes].filter(item => item.nodeName !== 'UL' && item.nodeName !== 'OL').map(inlineMarkdown).join('').trim()}${[...child.children].filter(item => ['UL','OL'].includes(item.tagName)).map(item => `\n${block(item,depth + 1).trimEnd()}`).join('')}`).join('\n')}\n\n`
    if (tag === 'hr') return '---\n\n'
    if (['strong','b','em','i','s','code','a','img','br'].includes(tag)) return inlineMarkdown(node)
    return inner
  }
  return [...root.childNodes].map(node => block(node)).join('').replace(/\n{3,}/g, '\n\n').trimEnd() + '\n'
}

async function load(preferredId) {
  loading.value = true
  try {
    workspace.value = await api(`/assignments/${props.assignmentId}/workspace`, { method: 'POST', body: JSON.stringify({}) })
    criteriaPreview.value = null
    activeId.value = workspace.value.documents.some(item => item.id === preferredId) ? preferredId : workspace.value.documents[0]?.id || ''
    emit('ready', workspace.value)
    if (activeId.value) await loadDocument(activeId.value)
    else clearEditor()
  } catch (error) { message.error(error.message) }
  finally { loading.value = false }
}

function clearEditor() {
  applying = true
  loadedId.value = ''
  editorHtml.value = '<p></p>'
  sourceMarkdown.value = ''
  queueMicrotask(() => { applying = false })
}

function applyMarkdown(id, markdownContent) {
  applying = true
  loadedId.value = id
  const markdown = markdownContent || ''
  editorHtml.value = renderMarkdown(markdown)
  sourceMarkdown.value = markdown
  lastSavedMarkdown.set(id, markdown)
  queueMicrotask(() => { applying = false })
}

function currentMarkdown() {
  return editorMode.value === 'source' ? sourceMarkdown.value : htmlToMarkdown(editorHtml.value)
}

function markdownEqual(left, right) {
  return (left || '').replace(/\r\n/g, '\n').trimEnd() === (right || '').replace(/\r\n/g, '\n').trimEnd()
}

function setEditorMode(nextMode) {
  if (nextMode === editorMode.value || !active.value) return
  applying = true
  if (nextMode === 'source') {
    sourceMarkdown.value = htmlToMarkdown(editorHtml.value)
  } else {
    editorHtml.value = renderMarkdown(sourceMarkdown.value)
  }
  editorMode.value = nextMode
  const saved = lastSavedMarkdown.get(active.value.id) || ''
  state.value = markdownEqual(currentMarkdown(), saved) ? 'saved' : 'dirty'
  queueMicrotask(() => { applying = false })
}

async function loadDocument(id, force = false) {
  const target = workspace.value?.documents.find(item => item.id === id)
  if (!target) return
  const cached = documentCache.get(id)
  if (!force && cached?.revision === target.revision) {
    applyMarkdown(id, cached.markdownContent)
    state.value = 'saved'
    return
  }
  const sequence = ++loadSequence
  documentLoading.value = true
  loadedId.value = ''
  try {
    const document = await api(`/assignments/${props.assignmentId}/workspace/documents/${id}`)
    if (sequence !== loadSequence || activeId.value !== id) return
    Object.assign(target, document)
    documentCache.set(id, { revision: document.revision, markdownContent: document.markdown_content || '' })
    applyMarkdown(id, document.markdown_content || '')
    state.value = 'saved'
  } catch (error) {
    if (sequence === loadSequence) message.error(error.message)
  } finally {
    if (sequence === loadSequence) documentLoading.value = false
  }
}

watch(editorHtml, () => {
  if (applying || loadedId.value !== activeId.value || !props.writable || !active.value) return
  state.value = 'dirty'
})

watch(sourceMarkdown, () => {
  if (applying || editorMode.value !== 'source' || loadedId.value !== activeId.value || !props.writable || !active.value) return
  state.value = markdownEqual(sourceMarkdown.value, lastSavedMarkdown.get(active.value.id) || '') ? 'saved' : 'dirty'
})

async function save(force = false) {
  if (active.value?.locked) return true
  if (!active.value) return true
  if (savePromise) {
    pendingSave = { target: active.value, markdownContent: currentMarkdown() }
    return savePromise
  }
  if (!force && state.value !== 'dirty') return state.value !== 'conflict' && state.value !== 'error'
  pendingSave = { target: active.value, markdownContent: currentMarkdown() }
  savePromise = (async () => {
    try {
      while (pendingSave) {
        const { target, markdownContent } = pendingSave
        pendingSave = undefined
        if (markdownEqual(markdownContent, lastSavedMarkdown.get(target.id))) {
          state.value = 'saved'
          continue
        }
        state.value = 'saving'
        const saved = await api(`/assignments/${props.assignmentId}/workspace/documents/${target.id}`, { method: 'PUT', body: JSON.stringify({ revision: target.revision, markdown_content: markdownContent }) })
        Object.assign(target, saved)
        documentCache.set(target.id, { revision: saved.revision, markdownContent })
        lastSavedMarkdown.set(target.id, markdownContent)
        if (target.id === activeId.value) {
          const latestMarkdown = currentMarkdown()
          if (!markdownEqual(latestMarkdown, markdownContent)) pendingSave = { target, markdownContent: latestMarkdown }
        }
        state.value = pendingSave ? 'dirty' : 'saved'
      }
      return true
    } catch (error) {
      state.value = error.code === 'DOCUMENT_VERSION_CONFLICT' ? 'conflict' : 'error'
      message.error(error.message)
      return false
    } finally {
      savePromise = undefined
    }
  })()
  return savePromise
}

async function selectDocument(id) {
  if (id === activeId.value && !criteriaPreview.value) return
  if (state.value === 'dirty' || state.value === 'saving') return message.warning('请先保存或撤销当前修改')
  criteriaPreview.value = null
  activeId.value = id
  await loadDocument(id)
}

async function selectCriteria(file) {
  if (!await save()) return
  loadSequence += 1
  documentLoading.value = false
  loadedId.value = ''
  activeId.value = ''
  criteriaPreview.value = { file, loading: true, type: '', html: '', src: '' }
  const name = file.name || file.original_name || ''
  try {
    if (/\.md$/i.test(name)) {
      const { url } = await api(`/files/${file.id}/preview-url`)
      const html = await loadMarkdownPreview(url)
      criteriaPreview.value = { file, loading: false, type: 'rich', html, src: '' }
    } else {
      criteriaPreview.value = { file, loading: false, type: 'unsupported', html: '', src: '' }
    }
  } catch (error) {
    criteriaPreview.value = null
    message.error(error.message)
  }
}

async function discardChanges() {
  if (!active.value || state.value === 'saving') return
  if (state.value === 'conflict') {
    await loadDocument(active.value.id, true)
    return
  }
  applyMarkdown(active.value.id, lastSavedMarkdown.get(active.value.id) || '')
  state.value = 'saved'
}

async function downloadCurrent() {
  if (!active.value || downloading.value) return
  const documentId = active.value.id
  if (state.value === 'conflict') return message.warning('请先处理编辑冲突再下载')
  downloading.value = true
  try {
    if (state.value === 'dirty' || state.value === 'error') {
      if (!await save(true)) return
    } else if (state.value === 'saving' && !await savePromise) return
    if (state.value !== 'saved' || activeId.value !== documentId) return message.warning('请先保存当前修改再下载')
    const document = await api(`/assignments/${props.assignmentId}/workspace/documents/${documentId}`)
    const url = URL.createObjectURL(new Blob([document.markdown_content], { type: 'text/markdown;charset=utf-8' }))
    const link = window.document.createElement('a')
    link.href = url
    link.download = document.name
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (error) { message.error(error.message) }
  finally { downloading.value = false }
}
function externalChange(event) {
  if (event.detail?.assignmentId !== props.assignmentId) return
  if (event.detail?.workspaceId && event.detail.workspaceId !== workspace.value?.id) return
  const payload = event.detail?.payload || {}
  const changedId = payload.resource_id
  const target = workspace.value?.documents.find(item => item.id === changedId)
  if (target && payload.revision) target.revision = payload.revision
  if (changedId) documentCache.delete(changedId)
  if (changedId !== activeId.value) return
  if (state.value === 'dirty' || state.value === 'saving') { state.value = 'conflict'; message.warning('同组成员更新了当前文档，请先处理未保存内容') }
  else loadDocument(activeId.value, true)
}
onMounted(() => { load(); window.addEventListener('workspace-changed', externalChange) })
onBeforeUnmount(() => {
  loadSequence += 1
  window.removeEventListener('workspace-changed', externalChange)
})
defineExpose({ save: () => state.value === 'dirty' ? false : save(), reload: () => load(activeId.value) })
</script>

<template>
  <div class="markdown-workspace" :class="{loading,'sidebar-collapsed':sidebarCollapsed}">
    <aside class="document-sidebar">
      <div class="document-sidebar-heading"><div><strong>文档</strong><span>{{workspace?.documents?.length||0}} 份 Markdown</span></div><a-tooltip :title="sidebarCollapsed?'展开文档栏':'折叠文档栏'"><a-button type="text" shape="circle" :aria-label="sidebarCollapsed?'展开文档栏':'折叠文档栏'" @click="sidebarCollapsed=!sidebarCollapsed"><MenuUnfoldOutlined v-if="sidebarCollapsed"/><MenuFoldOutlined v-else/></a-button></a-tooltip></div>
      <nav class="document-list" aria-label="作业文档列表"><a-tooltip v-for="item in workspace?.documents||[]" :key="item.id" :title="sidebarCollapsed?item.name:''" placement="right"><button type="button" class="document-item" :class="{active:item.id===activeId}" @click="selectDocument(item.id)"><span class="document-icon"><FileTextOutlined/></span><span class="document-name">{{item.name}}</span></button></a-tooltip></nav>
    </aside>
    <main class="document-surface">
      <header class="document-status"><div class="document-title"><strong>{{criteriaPreview?.file.name||active?.name}}</strong><span v-if="criteriaPreview">判定标准 · 只读</span><span v-else-if="active?.updated_by">最近由 {{active.updated_by}} 编辑</span></div><div v-if="criteriaPreview" class="readonly-indicator"><EyeOutlined/> 只读查看</div><div v-else-if="active" class="editor-mode-switch" role="tablist" aria-label="编辑模式"><button type="button" :class="{active:editorMode==='visual'}" role="tab" :aria-selected="editorMode==='visual'" @click="setEditorMode('visual')">可视化</button><button type="button" :class="{active:editorMode==='source'}" role="tab" :aria-selected="editorMode==='source'" @click="setEditorMode('source')"><CodeOutlined/> Markdown 源码</button></div></header>
      <div class="writing-stage" :class="{'criteria-stage':criteriaPreview}"><a-skeleton v-if="criteriaPreview?.loading||documentLoading||loading" active/><RichTextViewer v-else-if="criteriaPreview?.type==='rich'" :html="criteriaPreview.html"/><a-empty v-else-if="criteriaPreview" description="判定标准仅支持 Markdown 文档"/><template v-else-if="active&&loadedId===active.id"><RichTextEditor v-if="editorMode==='visual'" v-model="editorHtml" :editable="writable" document placeholder="开始编写作业..."><template #toolbarEnd><a-tooltip title="下载当前原文件"><a-button type="text" shape="circle" aria-label="下载当前原文件" :loading="downloading" @click="downloadCurrent"><DownloadOutlined/></a-button></a-tooltip><div class="save-indicator" :class="state"><CheckCircleFilled v-if="state==='saved'"/><CloudSyncOutlined v-else-if="state==='dirty'||state==='saving'"/><span>{{({dirty:'未保存',saving:'正在保存',saved:'已保存',conflict:'存在编辑冲突',error:'保存失败'})[state]||'已同步'}}</span><a-tooltip v-if="['dirty','conflict','error'].includes(state)" title="撤销"><a-button type="text" shape="circle" aria-label="撤销" @click="discardChanges"><UndoOutlined/></a-button></a-tooltip><a-button v-if="state==='dirty'||state==='error'" type="primary" size="small" :loading="state==='saving'" @click="save"><SaveOutlined/> 保存</a-button><a-button v-if="canSubmit" type="primary" size="small" :disabled="state==='dirty'||state==='saving'||state==='conflict'||state==='error'" @click="emit('submit')">{{submitLabel}}</a-button></div></template></RichTextEditor><section v-else class="source-editor"><div class="source-editor-heading"><div><CodeOutlined/><strong>Markdown 源码</strong></div><div class="source-editor-actions"><a-tooltip title="下载当前原文件"><a-button type="text" shape="circle" aria-label="下载当前原文件" :loading="downloading" @click="downloadCurrent"><DownloadOutlined/></a-button></a-tooltip><div class="save-indicator" :class="state"><CheckCircleFilled v-if="state==='saved'"/><CloudSyncOutlined v-else-if="state==='dirty'||state==='saving'"/><span>{{({dirty:'未保存',saving:'正在保存',saved:'已保存',conflict:'存在编辑冲突',error:'保存失败'})[state]||'已同步'}}</span></div><a-tooltip v-if="['dirty','conflict','error'].includes(state)" title="撤销"><a-button type="text" shape="circle" aria-label="撤销" @click="discardChanges"><UndoOutlined/></a-button></a-tooltip><a-button v-if="state==='dirty'||state==='error'" type="primary" size="small" :loading="state==='saving'" @click="save"><SaveOutlined/> 保存</a-button><a-button v-if="canSubmit" type="primary" size="small" :disabled="state==='dirty'||state==='saving'||state==='conflict'||state==='error'" @click="emit('submit')">{{submitLabel}}</a-button></div></div><textarea v-model="sourceMarkdown" :readonly="!writable" class="source-editor-input" spellcheck="false" aria-label="Markdown 源码"></textarea></section></template><a-empty v-else description="该作业没有可编辑的 Markdown 附件"/></div>
    </main>
  </div>
</template>

<style scoped>
.markdown-workspace{display:grid;grid-template-columns:248px minmax(0,1fr);min-height:680px;overflow:hidden;border:1px solid #dfe6eb;border-radius:6px;background:#f5f7f8}.document-sidebar{border-right:1px solid #dfe6eb;background:#fbfcfc}.document-sidebar-heading,.document-status{display:flex;align-items:center;justify-content:space-between;min-height:62px;border-bottom:1px solid #e4e9ed}.document-sidebar-heading{padding:0 14px 0 18px}.document-sidebar-heading>div,.document-title{display:flex;min-width:0;flex-direction:column}.document-sidebar-heading strong{color:#263943;font-size:14px}.document-sidebar-heading span,.document-title span{margin-top:2px;color:#87949c;font-size:11px}.document-list{padding:10px}.document-item{display:grid;grid-template-columns:30px minmax(0,1fr) 28px;align-items:center;width:100%;min-height:48px;margin-bottom:4px;padding:4px 6px;border:0;border-radius:5px;background:transparent;color:#526672;text-align:left;cursor:pointer}.document-item:hover{background:#f0f4f5}.document-item.active{background:#e5f1ed;color:#176f5b}.document-icon{display:grid;place-items:center;width:26px;height:30px;border:1px solid #dce5e7;border-radius:4px;background:#fff}.document-item.active .document-icon{border-color:#b9d9cf;color:#19816a}.document-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px}.document-surface{min-width:0}.document-status{padding:0 20px;background:#fff}.document-title strong{overflow:hidden;color:#263943;text-overflow:ellipsis;white-space:nowrap;font-size:14px}.document-status>div{display:flex;align-items:center;gap:8px}.save-indicator{display:flex;align-items:center;gap:7px;color:#7d8b93;font-size:12px;white-space:nowrap}.save-indicator.saved{color:#24866e}.save-indicator.conflict,.save-indicator.error{color:#bd4f49}.writing-stage{min-height:618px;padding:28px 34px 42px;background:#f3f5f6}.writing-stage :deep(.feedback-rich-editor){width:min(100%,980px);margin:0 auto;box-shadow:0 2px 10px rgba(31,47,56,.07)}@media(max-width:900px){.markdown-workspace{grid-template-columns:210px minmax(0,1fr)}.writing-stage{padding:20px 18px 32px}}@media(max-width:760px){.markdown-workspace{display:block;min-height:0}.document-sidebar{border-right:0;border-bottom:1px solid #dfe5ea}.document-list{display:flex;overflow-x:auto;padding:8px}.document-item{width:min(220px,70vw);flex:0 0 auto;margin:0 4px 0 0}.document-status{align-items:flex-start;min-height:0;padding:11px 12px;gap:4px;flex-wrap:wrap}.document-status .document-title{width:100%;align-items:flex-start}.document-title strong{max-width:100%}.writing-stage{min-height:500px;padding:12px 8px 20px}}
.markdown-workspace.sidebar-collapsed{grid-template-columns:56px minmax(0,1fr)}.sidebar-collapsed .document-sidebar-heading{justify-content:center;padding:0}.sidebar-collapsed .document-sidebar-heading>div{display:none}.sidebar-collapsed .document-list{padding:10px 7px}.sidebar-collapsed .document-item{display:grid;width:42px;grid-template-columns:1fr;justify-items:center;padding:4px}.sidebar-collapsed .document-name{display:none}@media(max-width:760px){.markdown-workspace.sidebar-collapsed{display:block}.sidebar-collapsed .document-sidebar-heading{justify-content:space-between;padding:0 14px 0 18px}.sidebar-collapsed .document-sidebar-heading>div{display:flex}.sidebar-collapsed .document-sidebar-heading :deep(.ant-btn){display:none}.sidebar-collapsed .document-list{padding:8px}.sidebar-collapsed .document-item{display:grid;width:min(220px,70vw);grid-template-columns:30px minmax(0,1fr) 28px;justify-items:stretch;padding:4px 6px}.sidebar-collapsed .document-name{display:block}}
</style>
<style scoped>
.editor-mode-switch{padding:3px;border:1px solid #dce4e7;border-radius:5px;background:#f7f9fa}.editor-mode-switch button{display:inline-flex;align-items:center;gap:5px;min-height:28px;padding:0 10px;border:0;border-radius:3px;background:transparent;color:#70808a;font-size:12px;cursor:pointer}.editor-mode-switch button:hover{color:#176f5b;background:#edf4f1}.editor-mode-switch button.active{color:#176f5b;background:#e3f1ec;font-weight:600}.source-editor{width:min(100%,980px);min-height:560px;margin:0 auto;border:1px solid #d5dde5;border-radius:6px;background:#fff;box-shadow:0 2px 10px rgba(31,47,56,.07)}.source-editor-heading{display:flex;align-items:center;justify-content:space-between;min-height:52px;padding:0 14px;border-bottom:1px solid #e4e9ed;background:#fafbfb}.source-editor-heading>div:first-child{display:flex;align-items:center;gap:7px;color:#36515b}.source-editor-heading strong{font-size:13px}.source-editor-heading span{color:#85939b;font-size:11px}.source-editor-heading>div:first-child>span{margin-left:4px}.source-editor-actions{display:flex;align-items:center;gap:5px}.source-editor-input{display:block;width:100%;min-height:505px;padding:22px 24px;border:0;outline:0;resize:vertical;color:#263943;background:#fff;font-family:ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",monospace;font-size:13px;line-height:1.7;tab-size:2}.source-editor-input:focus{box-shadow:inset 0 0 0 2px rgba(37,134,111,.14)}
.criteria-list{margin:2px 10px 10px;padding-top:10px;border-top:1px solid #e2e8eb}.criteria-list-heading{display:flex;align-items:center;justify-content:space-between;padding:0 6px 7px;color:#647781;font-size:11px;font-weight:600}.criteria-list-heading small{color:#8b989f;font-weight:400}.criteria-item{display:grid;grid-template-columns:30px minmax(0,1fr);align-items:center;width:100%;min-height:44px;padding:4px 6px;border:0;border-radius:5px;background:#f7f4ea;color:#665b3f;text-align:left;cursor:pointer}.criteria-item:hover{background:#f1ead7;color:#514625}
.criteria-item.active{background:#ece3c9;color:#4f452e}.readonly-indicator{display:flex;align-items:center;gap:6px;color:#776b4d;font-size:12px}.writing-stage.criteria-stage{display:flex;align-items:stretch;justify-content:center}.criteria-stage :deep(.rich-document){width:min(100%,980px)}
.markdown-workspace{overflow:clip}
@media(max-width:760px){.editor-mode-switch{width:100%}.editor-mode-switch button{width:50%;justify-content:center}.source-editor{min-height:480px}.source-editor-heading{align-items:flex-start;gap:8px;padding:10px;flex-direction:column}.source-editor-heading>div:first-child{align-items:flex-start;flex-wrap:wrap}.source-editor-actions{width:100%;justify-content:flex-end}.source-editor-input{min-height:410px;padding:16px}}
</style>
