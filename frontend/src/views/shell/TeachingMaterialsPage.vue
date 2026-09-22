<script setup>
import { computed, h, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { message, Modal, Input } from 'ant-design-vue'
import { ArrowDownOutlined, ArrowUpOutlined, DeleteOutlined, DownloadOutlined, EditOutlined, FileMarkdownOutlined, FolderOpenOutlined, FolderOutlined, MoreOutlined, UploadOutlined, VideoCameraOutlined } from '@ant-design/icons-vue'
import { api } from '../../api'
import { loadMarkdownPreview } from '../../markdownPreview'
import RichTextViewer from '../../components/RichTextViewer.vue'
import { useShellContext } from '../../shellContext'

const { classId, role } = useShellContext()
const loading = ref(false)
const error = ref('')
const folders = ref([])
const files = ref([])
const expanded = ref(new Set())
const selected = ref(null)
const content = ref('')
const htmlDocument = ref('')
const htmlViewport = ref(null)
const htmlScale = ref(1)
const HTML_CANVAS_WIDTH = 1920
const HTML_CANVAS_HEIGHT = 1080
const HTML_PREVIEW_GUTTER = 32
const contentLoading = ref(false)
const context = ref(null)
const uploadInput = ref(null)
const uploadFolderId = ref(null)
const canManage = computed(() => role.value === 'TEACHER')

const folderMap = computed(() => new Map(folders.value.map(item => [item.id, item])))
const fileMap = computed(() => new Map(files.value.map(item => [item.id, item])))
const bySortOrder = (a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name, 'zh-CN')
const childrenFolders = folderId => folders.value.filter(item => item.parent_id === folderId).sort(bySortOrder)
const childrenFiles = folderId => files.value.filter(item => item.folder_id === folderId).sort(bySortOrder)
const visibleNodes = computed(() => {
  const nodes = []
  function append(folderId, depth) {
    childrenFolders(folderId).forEach(folder => {
      nodes.push({ ...folder, nodeType: 'folder', depth })
      if (expanded.value.has(folder.id)) append(folder.id, depth + 1)
    })
    childrenFiles(folderId).forEach(file => nodes.push({ ...file, nodeType: 'file', depth }))
  }
  append(null, 0)
  return nodes
})

function fileIcon(item) {
  if (item.media_type === 'VIDEO') return VideoCameraOutlined
  if (item.media_type === 'MARKDOWN') return FileMarkdownOutlined
  return FileMarkdownOutlined
}

async function loadTree() {
  if (!classId.value) return
  loading.value = true; error.value = ''
  try {
    const data = await api(`/teaching-materials?class_id=${encodeURIComponent(classId.value)}`)
    folders.value = data.folders || []; files.value = data.files || []
  } catch (err) { error.value = err.message || '教学资料加载失败' }
  finally { loading.value = false }
}

function toggleFolder(folder) {
  const next = new Set(expanded.value)
  if (next.has(folder.id)) next.delete(folder.id); else next.add(folder.id)
  expanded.value = next
}

async function selectFile(file) {
  selected.value = file; content.value = ''; htmlDocument.value = ''; contentLoading.value = true
  try {
    if (file.media_type === 'VIDEO') return
    if (file.media_type === 'MARKDOWN') content.value = await loadMarkdownPreview(file.content_url)
    else {
      const response = await fetch(file.content_url, { credentials: 'include' })
      if (!response.ok) throw new Error('文件加载失败')
      // Teacher-uploaded HTML is rendered in an opaque-origin sandbox. Scripts
      // can initialise the document UI, but cannot access the parent app.
      htmlDocument.value = await response.text()
    }
  } catch (err) { message.error(err.message || '文件加载失败') }
  finally { contentLoading.value = false }
}

function clearContext() { context.value = null }
function openContext(event, node = null) {
  if (!canManage.value) return
  event.preventDefault(); event.stopPropagation()
  const width = 196; const height = node?.nodeType === 'file' ? 240 : node ? 288 : 96
  context.value = { node, x: Math.min(event.clientX, window.innerWidth - width - 8), y: Math.min(event.clientY, window.innerHeight - height - 8) }
}

function createFolder(parentId) {
  clearContext()
  let value = ''
  Modal.confirm({
    title: '新建文件夹',
    content: h(Input, { placeholder: '请输入文件夹名称', maxlength: 120, onInput: event => { value = event.target.value } }),
    okText: '创建', cancelText: '取消',
    onOk: async () => {
      const name = value.trim()
      if (!name) { message.warning('请输入文件夹名称'); return Promise.reject() }
      await api('/teaching-materials/folders', { method: 'POST', body: JSON.stringify({ class_id: classId.value, parent_id: parentId, name }) })
      message.success('文件夹已创建'); await loadTree()
    }
  })
}

function renameNode(node) {
  clearContext()
  const isFile = node.nodeType === 'file'
  const suffix = isFile ? node.name.slice(node.name.lastIndexOf('.')) : ''
  let value = isFile ? node.name.slice(0, node.name.length - suffix.length) : node.name
  Modal.confirm({
    title: isFile ? '重命名文件' : '重命名文件夹',
    content: h(Input, { defaultValue: value, placeholder: '请输入名称', maxlength: 120, onInput: event => { value = event.target.value } }),
    okText: '保存', cancelText: '取消',
    onOk: async () => {
      const name = value.trim()
      if (!name) { message.warning('请输入名称'); return Promise.reject() }
      await api(isFile ? `/teaching-materials/files/${node.id}` : `/teaching-materials/folders/${node.id}`, { method: 'PATCH', body: JSON.stringify({ name }) })
      message.success('已重命名'); await loadTree()
    }
  })
}

async function moveNode(node, direction) {
  clearContext()
  const isFile = node.nodeType === 'file'
  try {
    await api(isFile ? `/teaching-materials/files/${node.id}/move` : `/teaching-materials/folders/${node.id}/move`, { method: 'POST', body: JSON.stringify({ direction }) })
    await loadTree()
  } catch (err) { message.error(err.message || '调整顺序失败') }
}

function downloadFile(node) {
  clearContext()
  window.location.assign(`${node.content_url}?download=1`)
}

function triggerUpload(folderId) {
  clearContext(); uploadFolderId.value = folderId; uploadInput.value?.click()
}

async function handleUpload(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  const body = new FormData(); body.append('file', file)
  try {
    const folderQuery = uploadFolderId.value ? `&folder_id=${encodeURIComponent(uploadFolderId.value)}` : ''
    await api(`/teaching-materials/files?class_id=${encodeURIComponent(classId.value)}${folderQuery}`, { method: 'POST', body })
    message.success('文件已上传'); await loadTree()
  } catch (err) { message.error(err.message || '文件上传失败') }
}

function deleteNode(node) {
  clearContext()
  const isFile = node.nodeType === 'file'
  Modal.confirm({
    title: isFile ? `删除文件“${node.name}”？` : `删除文件夹“${node.name}”？`,
    content: isFile ? '删除后学生将无法继续查看该文件。' : '仅允许删除空文件夹。',
    okText: '确认删除', okType: 'danger', cancelText: '取消',
    onOk: async () => {
      await api(isFile ? `/teaching-materials/files/${node.id}` : `/teaching-materials/folders/${node.id}`, { method: 'DELETE' })
      if (selected.value?.id === node.id) { selected.value = null; content.value = ''; htmlDocument.value = '' }
      message.success('已删除'); await loadTree()
    }
  })
}

function typeLabel(type) { return type === 'MARKDOWN' ? 'Markdown' : type === 'HTML' ? 'HTML' : 'MP4 视频' }
let htmlResizeObserver
function resizeHtmlStage() {
  if (!htmlViewport.value) return
  const availableWidth = Math.max(1, htmlViewport.value.clientWidth - HTML_PREVIEW_GUTTER)
  const availableHeight = Math.max(1, htmlViewport.value.clientHeight - HTML_PREVIEW_GUTTER)
  htmlScale.value = Math.min(1, availableWidth / HTML_CANVAS_WIDTH, availableHeight / HTML_CANVAS_HEIGHT)
}
function observeHtmlStage() {
  htmlResizeObserver?.disconnect()
  if (!htmlViewport.value) return
  htmlResizeObserver = new ResizeObserver(resizeHtmlStage)
  htmlResizeObserver.observe(htmlViewport.value)
  resizeHtmlStage()
}
watch([() => selected.value?.media_type, contentLoading], async ([type, loading]) => {
  htmlResizeObserver?.disconnect()
  if (type === 'HTML' && !loading) { await nextTick(); observeHtmlStage() }
})
onMounted(loadTree)
onBeforeUnmount(() => htmlResizeObserver?.disconnect())
</script>

<template>
  <section class="teaching-materials-page" @click="clearContext">
    <input ref="uploadInput" class="teaching-material-upload-input" type="file" accept=".md,.html,.htm,.mp4" @change="handleUpload">
    <header class="page-title teaching-materials-title">
      <div><div class="eyebrow">课程资源</div><h1>教学资料</h1><p>文件目录（右击操作）</p></div>
      <a-tag v-if="canManage" color="blue">教师管理</a-tag><a-tag v-else>只读查看</a-tag>
    </header>
    <a-alert v-if="error" type="error" show-icon :message="error" class="teaching-materials-alert" />
    <div class="teaching-materials-layout">
      <aside class="teaching-materials-tree" @contextmenu="event => openContext(event)">
        <div class="teaching-materials-tree-heading"><span>文件目录</span><small>右击操作</small></div>
        <a-spin v-if="loading" class="teaching-materials-loading" />
        <a-empty v-else-if="!visibleNodes.length" description="暂无教学资料" />
        <div v-else class="teaching-materials-node-list">
          <button v-for="node in visibleNodes" :key="`${node.nodeType}-${node.id}`" type="button" class="teaching-material-node" :class="{selected:selected?.id===node.id,folder:node.nodeType==='folder'}" :style="{paddingLeft:`${14 + node.depth * 20}px`}" @click.stop="node.nodeType==='folder' ? toggleFolder(node) : selectFile(node)" @contextmenu="event => openContext(event,node)">
            <FolderOpenOutlined v-if="node.nodeType==='folder' && expanded.has(node.id)" class="teaching-material-node-icon" />
            <FolderOutlined v-else-if="node.nodeType==='folder'" class="teaching-material-node-icon" />
            <component :is="fileIcon(node)" v-else class="teaching-material-node-icon file" />
            <span class="teaching-material-node-name">{{node.name}}</span><span v-if="node.nodeType==='file'" class="teaching-material-node-type">{{typeLabel(node.media_type)}}</span>
          </button>
        </div>
      </aside>
      <main class="teaching-materials-preview">
        <div v-if="!selected" class="teaching-materials-placeholder"><FolderOpenOutlined/><h2>选择文件查看内容</h2><p>点击左侧文件，内容会显示在这里</p></div>
        <template v-else>
          <div class="teaching-material-preview-heading"><div><div class="eyebrow">{{typeLabel(selected.media_type)}}</div><h2>{{selected.name}}</h2></div><a-tag>{{Math.max(1, Math.ceil(selected.size / 1024))}} KB</a-tag></div>
          <a-spin v-if="contentLoading" class="teaching-material-content-loading" />
          <div v-else-if="selected.media_type==='VIDEO'" class="teaching-material-video"><video :src="selected.content_url" controls preload="metadata" /></div>
          <div v-else-if="selected.media_type==='HTML'" ref="htmlViewport" class="teaching-material-html"><div class="teaching-material-html-stage" :style="{width:`${HTML_CANVAS_WIDTH * htmlScale}px`,height:`${HTML_CANVAS_HEIGHT * htmlScale}px`}"><iframe :srcdoc="htmlDocument" title="HTML 教学资料" sandbox="allow-scripts" allow="fullscreen" allowfullscreen referrerpolicy="no-referrer" :style="{width:`${HTML_CANVAS_WIDTH}px`,height:`${HTML_CANVAS_HEIGHT}px`,transform:`scale(${htmlScale})`}" /></div></div>
          <div v-else class="teaching-material-rich"><RichTextViewer :html="content" /></div>
        </template>
      </main>
    </div>
    <div v-if="context" class="teaching-material-context-menu" :style="{left:`${context.x}px`,top:`${context.y}px`}" @click.stop>
      <template v-if="context.node?.nodeType === 'file'">
        <button type="button" @click="renameNode(context.node)"><EditOutlined/> 重命名</button>
        <button type="button" @click="moveNode(context.node,'up')"><ArrowUpOutlined/> 上移</button>
        <button type="button" @click="moveNode(context.node,'down')"><ArrowDownOutlined/> 下移</button>
        <button type="button" @click="downloadFile(context.node)"><DownloadOutlined/> 下载文件</button>
        <button type="button" class="danger" @click="deleteNode(context.node)"><DeleteOutlined/> 删除文件</button>
      </template>
      <template v-else>
        <button type="button" @click="createFolder(context.node?.id || null)"><FolderOutlined/> 新建文件夹</button>
        <button type="button" @click="triggerUpload(context.node?.id || null)"><UploadOutlined/> 上传文件到此目录</button>
        <template v-if="context.node">
          <button type="button" @click="renameNode(context.node)"><EditOutlined/> 重命名</button>
          <button type="button" @click="moveNode(context.node,'up')"><ArrowUpOutlined/> 上移</button>
          <button type="button" @click="moveNode(context.node,'down')"><ArrowDownOutlined/> 下移</button>
          <button type="button" class="danger" @click="deleteNode(context.node)"><DeleteOutlined/> 删除文件夹</button>
        </template>
      </template>
    </div>
  </section>
</template>
