<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import { Node } from '@tiptap/core'
import StarterKit from '@tiptap/starter-kit'
import Image from '@tiptap/extension-image'
import { TableKit } from '@tiptap/extension-table'
import mermaid from 'mermaid'
import { AudioOutlined, BlockOutlined, BoldOutlined, CodeOutlined, DeleteColumnOutlined, DeleteOutlined, DeleteRowOutlined, DeploymentUnitOutlined, InsertRowAboveOutlined, InsertRowBelowOutlined, InsertRowLeftOutlined, InsertRowRightOutlined, ItalicOutlined, LinkOutlined, MinusOutlined, OrderedListOutlined, PictureOutlined, RedoOutlined, StopOutlined, TableOutlined, UndoOutlined, UnorderedListOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'

let activeSpeechStop = null
const MAX_MARKDOWN_BYTES = 500 * 1024 * 1024

const props = defineProps({ modelValue: { type: String, default: '' }, placeholder: { type: String, default: '' }, compact: Boolean, document: Boolean, autofocus: Boolean, speechEnabled: Boolean, editable: { type: Boolean, default: true } })
const emit = defineEmits(['update:modelValue'])
const speechSupported = ref(false)
const listening = ref(false)
const speechState = ref('idle')
const interimText = ref('')
const mermaidOpen = ref(false)
const mermaidSource = ref('flowchart LR\n  A[开始] --> B[处理]\n  B --> C[完成]')
const mermaidSvg = ref('')
const mermaidError = ref('')
const mermaidRendering = ref(false)
const editingMermaidPos = ref(null)
const imageInput = ref(null)
const imageLoading = ref(false)
const lastSpeechRange = ref(null)
const editorVersion = ref(0)
let recognition = null
let speechStopRequested = false
let speechRestartTimer = 0

mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'neutral' })

const MermaidBlock = Node.create({
  name: 'mermaidBlock',
  group: 'block',
  atom: true,
  selectable: true,
  addAttributes() { return { source: { default: '' } } },
  parseHTML() {
    return [{
      tag: 'pre',
      priority: 1000,
      getAttrs: element => {
        const code = element.querySelector(':scope > code.language-mermaid')
        return code ? { source: code.textContent || '' } : false
      }
    }]
  },
  renderHTML({ node }) {
    return ['pre', ['code', { class: 'language-mermaid' }, node.attrs.source]]
  },
  addNodeView() {
    return ({ node, getPos, editor: nodeEditor }) => {
      const dom = document.createElement('div')
      dom.className = 'mermaid-document-block'
      dom.tabIndex = 0
      dom.title = '点击编辑图表，按 Delete 删除'
      const preview = document.createElement('div')
      preview.className = 'mermaid-document-preview'
      const deleteButton = document.createElement('button')
      deleteButton.type = 'button'
      deleteButton.className = 'mermaid-delete-button'
      deleteButton.setAttribute('aria-label', '删除 Mermaid 图表')
      deleteButton.title = '删除图表'
      deleteButton.textContent = '删除'
      dom.append(preview, deleteButton)
      let currentNode = node
      let renderVersion = 0

      const draw = async source => {
        const version = ++renderVersion
        preview.innerHTML = '<span class="mermaid-document-loading">正在绘制图表...</span>'
        try {
          const { svg } = await mermaid.render(`mermaid-block-${Date.now()}-${Math.random().toString(16).slice(2)}`, source)
          if (version === renderVersion) preview.innerHTML = svg
        } catch (error) {
          if (version === renderVersion) preview.innerHTML = '<span class="mermaid-document-error">图表语法有误，点击修改</span>'
        }
      }
      const edit = () => openMermaidEditor(currentNode.attrs.source, getPos())
      const remove = () => {
        const position = getPos()
        nodeEditor.view.dispatch(nodeEditor.state.tr.delete(position, position + currentNode.nodeSize))
        nodeEditor.commands.focus()
      }
      dom.addEventListener('click', edit)
      deleteButton.addEventListener('click', event => { event.stopPropagation(); remove() })
      dom.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); edit() }
        if (event.key === 'Delete' || event.key === 'Backspace') { event.preventDefault(); remove() }
      })
      draw(node.attrs.source)
      return {
        dom,
        update: nextNode => {
          if (nextNode.type.name !== 'mermaidBlock') return false
          currentNode = nextNode
          draw(nextNode.attrs.source)
          return true
        },
        stopEvent: () => true,
        destroy: () => { renderVersion += 1 }
      }
    }
  }
})

const EditableImage = Image.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      width: {
        default: null,
        parseHTML: element => element.getAttribute('width'),
        renderHTML: attributes => attributes.width ? { width: attributes.width } : {}
      },
      height: {
        default: null,
        parseHTML: element => element.getAttribute('height'),
        renderHTML: attributes => attributes.height ? { height: attributes.height } : {}
      }
    }
  },
  addNodeView() {
    return ({ node, getPos, editor: nodeEditor }) => {
      const dom = document.createElement('figure')
      dom.className = 'document-image-block'
      const image = document.createElement('img')
      const resizeFrame = document.createElement('span')
      resizeFrame.className = 'document-image-resize-frame'
      resizeFrame.setAttribute('aria-hidden', 'true')
      const cornerPositions = ['top-left', 'top-right', 'bottom-left', 'bottom-right']
      cornerPositions.forEach(position => {
        const corner = document.createElement('i')
        corner.className = `document-image-corner ${position}`
        resizeFrame.append(corner)
      })
      const deleteButton = document.createElement('button')
      deleteButton.type = 'button'
      deleteButton.className = 'document-image-delete'
      deleteButton.setAttribute('aria-label', '删除图片')
      deleteButton.title = '删除图片'
      deleteButton.textContent = '删除'
      const widthHandle = document.createElement('button')
      widthHandle.type = 'button'
      widthHandle.className = 'document-image-resize resize-width'
      widthHandle.title = '左右拖动调整宽度'
      const heightHandle = document.createElement('button')
      heightHandle.type = 'button'
      heightHandle.className = 'document-image-resize resize-height'
      heightHandle.title = '上下拖动调整高度'
      const cornerHandle = document.createElement('button')
      cornerHandle.type = 'button'
      cornerHandle.className = 'document-image-resize resize-both'
      cornerHandle.title = '自由调整宽度和高度'

      const applyNode = current => {
        image.src = current.attrs.src
        image.alt = current.attrs.alt || ''
        dom.style.width = current.attrs.width || ''
        dom.style.height = current.attrs.height || ''
        if (current.attrs.title) image.title = current.attrs.title
        else image.removeAttribute('title')
      }
      const remove = () => {
        const position = getPos()
        nodeEditor.view.dispatch(nodeEditor.state.tr.delete(position, position + node.nodeSize))
        nodeEditor.commands.focus()
      }
      applyNode(node)
      deleteButton.addEventListener('click', event => { event.stopPropagation(); remove() })
      const bindResize = (handle, axis) => handle.addEventListener('pointerdown', event => {
        event.preventDefault()
        event.stopPropagation()
        dom.classList.add('is-resizing')
        const editorWidth = nodeEditor.view.dom.getBoundingClientRect().width
        const startX = event.clientX
        const startY = event.clientY
        const bounds = dom.getBoundingClientRect()
        let nextWidth = Math.round(bounds.width / editorWidth * 100)
        let nextHeight = Math.round(bounds.height)
        const move = moveEvent => {
          if (axis !== 'height') {
            nextWidth = Math.max(10, Math.min(100, Math.round((bounds.width + moveEvent.clientX - startX) / editorWidth * 100)))
            dom.style.width = `${nextWidth}%`
          }
          if (axis !== 'width') {
            nextHeight = Math.max(60, Math.min(2000, Math.round(bounds.height + moveEvent.clientY - startY)))
            dom.style.height = `${nextHeight}px`
          }
        }
        const finish = () => {
          window.removeEventListener('pointermove', move)
          window.removeEventListener('pointerup', finish)
          window.removeEventListener('pointercancel', finish)
          dom.classList.remove('is-resizing')
          const position = getPos()
          nodeEditor.view.dispatch(nodeEditor.state.tr.setNodeMarkup(position, undefined, {
            ...node.attrs,
            width: axis === 'height' ? node.attrs.width : `${nextWidth}%`,
            height: axis === 'width' ? node.attrs.height : `${nextHeight}px`
          }))
          nodeEditor.commands.focus()
        }
        window.addEventListener('pointermove', move)
        window.addEventListener('pointerup', finish, { once: true })
        window.addEventListener('pointercancel', finish, { once: true })
      })
      bindResize(widthHandle, 'width')
      bindResize(heightHandle, 'height')
      bindResize(cornerHandle, 'both')
      dom.append(image, resizeFrame, deleteButton, widthHandle, heightHandle, cornerHandle)
      return {
        dom,
        update: nextNode => {
          if (nextNode.type.name !== this.name) return false
          node = nextNode
          applyNode(nextNode)
          return true
        },
        stopEvent: event => [deleteButton, widthHandle, heightHandle, cornerHandle].includes(event.target)
      }
    }
  }
})

const editor = useEditor({
  content: props.modelValue,
  extensions: [StarterKit.configure({ link: { openOnClick: false } }), EditableImage.configure({ allowBase64: true }), TableKit, MermaidBlock],
  editable: props.editable,
  editorProps: { attributes: { 'data-placeholder': props.placeholder } },
  onCreate: ({ editor: instance }) => {
    instance.on('transaction', () => { editorVersion.value += 1 })
    instance.on('selectionUpdate', () => { editorVersion.value += 1 })
    if (props.autofocus) instance.commands.focus('end')
  },
  onUpdate: ({ editor: instance }) => emit('update:modelValue', instance.getHTML())
})

watch(() => props.modelValue, value => {
  if (editor.value && editor.value.getHTML() !== value) editor.value.commands.setContent(value || '', { emitUpdate: false })
})

watch(() => props.editable, value => editor.value?.setEditable(value))

function releaseSpeechSession() {
  if (activeSpeechStop === stopRecognition) activeSpeechStop = null
}

function speechErrorText(error) {
  return {
    'not-allowed': '麦克风权限被拒绝，请在浏览器中允许后重试',
    'service-not-allowed': '浏览器不允许使用语音识别服务',
    'audio-capture': '未检测到可用麦克风设备',
    network: '语音识别网络不可用，请检查网络后重试',
    'no-speech': '未检测到语音，请重试'
  }[error] || '语音识别失败，请重试'
}

function stopRecognition() {
  speechStopRequested = true
  if (speechRestartTimer) { window.clearTimeout(speechRestartTimer); speechRestartTimer = 0 }
  if (!recognition) { listening.value = false; speechState.value = 'idle'; releaseSpeechSession(); return }
  listening.value = false
  speechState.value = 'idle'
  interimText.value = ''
  try { recognition.stop() } catch (error) { /* already stopped */ }
}

function startRecognition() {
  if (!speechSupported.value || !editor.value) return
  activeSpeechStop?.()
  speechStopRequested = false
  recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)()
  recognition.lang = 'zh-CN'
  recognition.continuous = true
  recognition.interimResults = true
  const currentRecognition = recognition
  recognition.onresult = event => {
    let finalText = ''
    let pendingText = ''
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      if (event.results[index].isFinal) finalText += event.results[index][0].transcript
      else pendingText += event.results[index][0].transcript
    }
    interimText.value = pendingText
    if (!finalText) return
    const position = editor.value.state.selection.to
    const from = position
    editor.value.chain().focus().setTextSelection(position).insertContent(finalText).run()
    lastSpeechRange.value = { from, to: from + finalText.length }
  }
  recognition.onerror = event => {
    if (event.error === 'not-allowed' || event.error === 'service-not-allowed' || event.error === 'audio-capture') {
      speechStopRequested = true
      listening.value = false
      speechState.value = 'error'
      message.warning(speechErrorText(event.error))
    } else if (event.error !== 'no-speech') {
      speechState.value = 'retrying'
      message.warning(speechErrorText(event.error))
    }
  }
  recognition.onend = () => {
    if (recognition !== currentRecognition) return
    recognition = null
    if (!speechStopRequested && speechSupported.value) {
      speechState.value = 'retrying'
      speechRestartTimer = window.setTimeout(() => {
        speechRestartTimer = 0
        if (!speechStopRequested) startRecognition()
      }, 250)
      return
    }
    listening.value = false
    speechState.value = 'idle'
    releaseSpeechSession()
  }
  activeSpeechStop = stopRecognition
  listening.value = true
  speechState.value = 'listening'
  interimText.value = ''
  try { recognition.start() }
  catch (error) {
    recognition = null
    listening.value = false
    speechState.value = 'error'
    releaseSpeechSession()
    message.warning('无法启动语音识别，请重试')
  }
}

function toggleSpeechRecognition() {
  if (listening.value) stopRecognition()
  else startRecognition()
}

function undoSpeechInput() {
  if (!lastSpeechRange.value || !editor.value) return
  editor.value.chain().focus().deleteRange(lastSpeechRange.value).run()
  lastSpeechRange.value = null
}

const speechLabel = computed(() => ({ listening: '正在听...', retrying: '网络重试中...', error: '识别失败' }[speechState.value] || ''))

onMounted(() => {
  speechSupported.value = Boolean(window.SpeechRecognition || window.webkitSpeechRecognition)
})
onBeforeUnmount(() => {
  stopRecognition()
  editor.value?.destroy()
})

defineExpose({ stopSpeechRecognition: stopRecognition })

function setLink() {
  const previous = editor.value?.getAttributes('link').href || ''
  const href = window.prompt('输入 HTTPS 链接', previous)
  if (href === null) return
  if (!href) editor.value.chain().focus().unsetLink().run()
  else if (/^https:\/\//i.test(href)) editor.value.chain().focus().extendMarkRange('link').setLink({ href }).run()
}

function insertTable() {
  editor.value?.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()
}

function runTableCommand(command) {
  if (!editor.value?.isActive('table')) return
  editor.value.chain().focus()[command]().run()
}

const tableActive = computed(() => {
  editorVersion.value
  return Boolean(editor.value?.isActive('table'))
})

function readDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

async function prepareImage(file) {
  const original = await readDataUrl(file)
  if (file.size <= 600 * 1024 || file.type === 'image/gif') return original
  const image = new window.Image()
  image.src = original
  await image.decode()
  const scale = Math.min(1, 1600 / Math.max(image.naturalWidth, image.naturalHeight))
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(image.naturalWidth * scale))
  canvas.height = Math.max(1, Math.round(image.naturalHeight * scale))
  canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height)
  return canvas.toDataURL('image/webp', 0.84)
}

async function insertImage(event) {
  const input = event.target
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (!['image/png', 'image/jpeg', 'image/gif', 'image/webp'].includes(file.type)) return message.error('仅支持 PNG、JPEG、GIF 或 WebP 图片')
  if (file.size > MAX_MARKDOWN_BYTES) return message.error('图片不能超过 500 MB')
  imageLoading.value = true
  try {
    const src = await prepareImage(file)
    if ((editor.value?.getHTML().length || 0) + src.length > MAX_MARKDOWN_BYTES) {
      return message.error('插入图片后 Markdown 将超过 500 MB，请压缩图片或删除部分内容')
    }
    editor.value?.chain().focus().setImage({ src, alt: file.name.replace(/\.[^.]+$/, '') }).run()
  } catch (error) {
    message.error('图片读取失败，请重新选择')
  } finally {
    imageLoading.value = false
  }
}

function openMermaidEditor(source = '', position = null) {
  editingMermaidPos.value = position
  mermaidSource.value = source || 'flowchart LR\n  A[开始] --> B[处理]\n  B --> C[完成]'
  mermaidOpen.value = true
  renderMermaid()
}

async function renderMermaid() {
  mermaidRendering.value = true
  mermaidError.value = ''
  try {
    const { svg } = await mermaid.render(`mermaid-${Date.now()}`, mermaidSource.value)
    mermaidSvg.value = svg
    return svg
  } catch (error) {
    mermaidSvg.value = ''
    mermaidError.value = '图表语法有误，请检查节点和连线写法'
    return ''
  } finally { mermaidRendering.value = false }
}

async function insertMermaid() {
  const svg = await renderMermaid()
  if (!svg) return
  const position = editingMermaidPos.value
  if (position === null) {
    editor.value?.chain().focus().insertContent({ type: 'mermaidBlock', attrs: { source: mermaidSource.value } }).run()
  } else {
    const node = editor.value?.state.doc.nodeAt(position)
    if (!node || node.type.name !== 'mermaidBlock') return message.error('图表位置已变化，请重新打开')
    editor.value.view.dispatch(editor.value.state.tr.setNodeMarkup(position, undefined, { source: mermaidSource.value }))
  }
  editingMermaidPos.value = null
  mermaidOpen.value = false
}
</script>

<template>
  <div class="feedback-rich-editor" :class="{compact,document}">
    <div v-if="editor" class="feedback-editor-toolbar">
      <div class="editor-toolbar-tools">
      <a-tooltip title="粗体"><a-button size="small" :type="editor.isActive('bold')?'primary':'default'" @click="editor.chain().focus().toggleBold().run()"><BoldOutlined/></a-button></a-tooltip>
      <a-tooltip title="斜体"><a-button size="small" :type="editor.isActive('italic')?'primary':'default'" @click="editor.chain().focus().toggleItalic().run()"><ItalicOutlined/></a-button></a-tooltip>
      <a-tooltip title="一级标题"><a-button size="small" :type="editor.isActive('heading',{level:1})?'primary':'default'" @click="editor.chain().focus().toggleHeading({level:1}).run()">H1</a-button></a-tooltip>
      <a-tooltip title="二级标题"><a-button size="small" :type="editor.isActive('heading',{level:2})?'primary':'default'" @click="editor.chain().focus().toggleHeading({level:2}).run()">H2</a-button></a-tooltip>
      <a-tooltip title="无序列表"><a-button size="small" @click="editor.chain().focus().toggleBulletList().run()"><UnorderedListOutlined/></a-button></a-tooltip>
      <a-tooltip title="有序列表"><a-button size="small" @click="editor.chain().focus().toggleOrderedList().run()"><OrderedListOutlined/></a-button></a-tooltip>
      <a-tooltip title="引用"><a-button size="small" :type="editor.isActive('blockquote')?'primary':'default'" @click="editor.chain().focus().toggleBlockquote().run()"><BlockOutlined/></a-button></a-tooltip>
      <a-tooltip title="行内代码"><a-button size="small" :type="editor.isActive('code')?'primary':'default'" @click="editor.chain().focus().toggleCode().run()"><span class="inline-code-icon">&lt;/&gt;</span></a-button></a-tooltip>
      <a-tooltip title="链接"><a-button size="small" @click="setLink"><LinkOutlined/></a-button></a-tooltip>
      <a-tooltip title="代码块（多行）"><a-button size="small" :type="editor.isActive('codeBlock')?'primary':'default'" @click="editor.chain().focus().toggleCodeBlock().run()"><CodeOutlined/></a-button></a-tooltip>
      <a-tooltip title="分隔线"><a-button size="small" @click="editor.chain().focus().setHorizontalRule().run()"><MinusOutlined/></a-button></a-tooltip>
      <a-tooltip v-if="document" title="插入表格"><a-button size="small" @click="insertTable"><TableOutlined/></a-button></a-tooltip>
      <template v-if="document&&tableActive">
        <span class="toolbar-divider"></span>
        <a-tooltip title="上方插入行"><a-button size="small" @click="runTableCommand('addRowBefore')"><InsertRowAboveOutlined/></a-button></a-tooltip>
        <a-tooltip title="下方插入行"><a-button size="small" @click="runTableCommand('addRowAfter')"><InsertRowBelowOutlined/></a-button></a-tooltip>
        <a-tooltip title="左侧插入列"><a-button size="small" @click="runTableCommand('addColumnBefore')"><InsertRowLeftOutlined/></a-button></a-tooltip>
        <a-tooltip title="右侧插入列"><a-button size="small" @click="runTableCommand('addColumnAfter')"><InsertRowRightOutlined/></a-button></a-tooltip>
        <a-tooltip title="删除当前行"><a-button size="small" @click="runTableCommand('deleteRow')"><DeleteRowOutlined/></a-button></a-tooltip>
        <a-tooltip title="删除当前列"><a-button size="small" @click="runTableCommand('deleteColumn')"><DeleteColumnOutlined/></a-button></a-tooltip>
        <a-tooltip title="切换表头"><a-button size="small" @click="runTableCommand('toggleHeaderRow')">TH</a-button></a-tooltip>
        <a-tooltip title="删除表格"><a-button size="small" danger @click="runTableCommand('deleteTable')"><DeleteOutlined/></a-button></a-tooltip>
      </template>
      <span class="toolbar-divider"></span>
      <a-tooltip title="撤销"><a-button size="small" :disabled="!editor.can().undo()" @click="editor.chain().focus().undo().run()"><UndoOutlined/></a-button></a-tooltip>
      <a-tooltip title="重做"><a-button size="small" :disabled="!editor.can().redo()" @click="editor.chain().focus().redo().run()"><RedoOutlined/></a-button></a-tooltip>
      <a-tooltip v-if="document" title="插入图片"><a-button size="small" :loading="imageLoading" @click="imageInput?.click()"><PictureOutlined/></a-button></a-tooltip>
      <a-tooltip v-if="document" title="插入 Mermaid 图表"><a-button size="small" @click="openMermaidEditor()"><DeploymentUnitOutlined/></a-button></a-tooltip>
      <a-tooltip v-if="speechEnabled&&speechSupported" :title="listening?'停止语音输入':'语音输入'">
        <a-button size="small" :type="listening?'primary':'default'" :aria-pressed="listening" @click="toggleSpeechRecognition"><StopOutlined v-if="listening"/><AudioOutlined v-else/></a-button>
      </a-tooltip>
      <a-tooltip v-if="speechEnabled&&speechSupported&&lastSpeechRange" title="撤销最近一次语音输入"><a-button size="small" aria-label="撤销最近一次语音输入" @click="undoSpeechInput"><UndoOutlined/></a-button></a-tooltip>
      <span v-if="speechEnabled&&speechSupported&&speechLabel" class="speech-status">{{speechLabel}}</span>
      </div>
      <div v-if="$slots.toolbarEnd" class="feedback-editor-toolbar-end"><slot name="toolbarEnd"/></div>
    </div>
    <input v-if="document" ref="imageInput" class="document-image-input" type="file" accept="image/png,image/jpeg,image/gif,image/webp" @change="insertImage">
    <div v-if="speechEnabled&&speechSupported&&listening&&interimText" class="speech-interim">正在识别：{{interimText}}</div>
    <EditorContent :editor="editor"/>
    <a-modal v-model:open="mermaidOpen" :title="editingMermaidPos===null?'插入 Mermaid 图表':'编辑 Mermaid 图表'" width="820px" :confirm-loading="mermaidRendering" :ok-text="editingMermaidPos===null?'插入图表':'保存修改'" cancel-text="取消" @ok="insertMermaid">
      <div class="mermaid-builder"><div><label>图表语法</label><a-textarea v-model:value="mermaidSource" :rows="12" spellcheck="false" @change="renderMermaid"/></div><div><label>预览</label><div class="mermaid-preview"><a-spin v-if="mermaidRendering"/><div v-else-if="mermaidSvg" v-html="mermaidSvg"></div><a-alert v-else type="error" :message="mermaidError||'暂无预览'"/></div></div></div>
    </a-modal>
  </div>
</template>

<style scoped>
.feedback-rich-editor{overflow:hidden;border:1px solid #d5dde5;border-radius:6px;background:#fff}.feedback-editor-toolbar{display:flex;min-width:0;align-items:center;padding:7px 10px;border-bottom:1px solid #e4e9ed;background:#fafbfb}.editor-toolbar-tools{display:flex;min-width:0;align-items:center;gap:3px;flex:1 1 auto;overflow-x:auto;scrollbar-width:thin}.editor-toolbar-tools>*{flex:0 0 auto}.feedback-editor-toolbar :deep(.ant-btn){border-color:transparent;box-shadow:none}.feedback-editor-toolbar :deep(.ant-btn-default:hover){border-color:#d7e0e4;background:#eef3f4}.feedback-editor-toolbar-end{display:flex;align-items:center;gap:7px;flex:0 0 auto;margin-left:8px;padding-left:10px;border-left:1px solid #dce4e7;background:#fafbfb}.toolbar-divider{width:1px;height:20px;margin:0 4px;background:#dce4e7}.inline-code-icon{font-family:Consolas,"Liberation Mono",monospace;font-size:11px;font-weight:700;letter-spacing:0}.speech-status{margin-left:2px;color:#176b78;font-size:12px}.speech-interim{padding:5px 10px;color:#738496;background:#f8fafc;border-bottom:1px solid #edf1f4;font-size:12px;font-style:italic}.feedback-rich-editor :deep(.tiptap){min-height:104px;padding:10px 12px;outline:none;line-height:1.55}.feedback-rich-editor.compact :deep(.tiptap){min-height:76px}.feedback-rich-editor :deep(.tiptap p){margin:0 0 7px}.feedback-rich-editor :deep(.tiptap p:last-child){margin-bottom:0}.feedback-rich-editor :deep(.tiptap:empty:before){float:left;color:#a7b0ba;content:attr(data-placeholder);pointer-events:none}
.feedback-rich-editor.document :deep(.tiptap){min-height:560px;padding:48px 64px 72px;color:#27353d;font-size:15px;line-height:1.8}.feedback-rich-editor.document :deep(.tiptap h1){margin:0 0 26px;color:#182932;font-size:30px;line-height:1.3}.feedback-rich-editor.document :deep(.tiptap h2){margin:34px 0 14px;color:#22363f;font-size:21px;line-height:1.4}.feedback-rich-editor.document :deep(.tiptap p){margin:0 0 14px}.feedback-rich-editor.document :deep(.tiptap blockquote){margin:18px 0;padding:10px 16px;border-left:3px solid #25866f;background:#f3f8f6;color:#53666e}.feedback-rich-editor.document :deep(.tiptap pre){overflow:auto;padding:14px;background:#f4f6f8;border-radius:4px}@media(max-width:760px){.feedback-rich-editor.document :deep(.tiptap){min-height:440px;padding:28px 20px}.feedback-editor-toolbar{padding-right:6px}.feedback-editor-toolbar-end{margin-left:5px;padding-left:6px}}
.feedback-rich-editor.document :deep(.tableWrapper){margin:18px 0;overflow-x:auto}.feedback-rich-editor.document :deep(table){width:100%;min-width:520px;border-collapse:collapse;table-layout:fixed}.feedback-rich-editor.document :deep(th),.feedback-rich-editor.document :deep(td){min-width:90px;padding:8px 10px;border:1px solid #cfd8e1;vertical-align:top}.feedback-rich-editor.document :deep(th){background:#f5f7f8;color:#263943;font-weight:600;text-align:center}.feedback-rich-editor.document :deep(th p),.feedback-rich-editor.document :deep(td p){margin:0}
.feedback-rich-editor.document :deep(.tiptap img){display:block;max-width:100%;height:auto;margin:22px auto;border:1px solid #e1e6e9;border-radius:4px}
.feedback-rich-editor.document :deep(.mermaid-document-block){display:grid;place-items:center;min-height:180px;margin:22px 0;padding:22px;overflow:auto;border:1px solid #d8e2e5;border-radius:6px;background:#fbfcfc;cursor:pointer;transition:border-color .15s,box-shadow .15s}.feedback-rich-editor.document :deep(.mermaid-document-block:hover),.feedback-rich-editor.document :deep(.mermaid-document-block:focus){border-color:#75aa9d;box-shadow:0 0 0 2px rgba(37,134,111,.1);outline:none}.feedback-rich-editor.document :deep(.mermaid-document-block svg){display:block;max-width:100%;height:auto}.feedback-rich-editor.document :deep(.mermaid-document-loading){color:#75858d;font-size:13px}.feedback-rich-editor.document :deep(.mermaid-document-error){color:#b34f49;font-size:13px}
.mermaid-builder{display:grid;grid-template-columns:minmax(0,.9fr) minmax(0,1.1fr);gap:18px}.mermaid-builder label{display:block;margin-bottom:7px;color:#40535f;font-size:12px;font-weight:600}.mermaid-preview{display:grid;place-items:center;min-height:286px;overflow:auto;border:1px solid #dce3e7;border-radius:6px;background:#f8fafb;padding:14px}.mermaid-preview :deep(svg){display:block;max-width:100%;height:auto}@media(max-width:760px){.mermaid-builder{grid-template-columns:1fr}.mermaid-preview{min-height:220px}}
.feedback-rich-editor.document{overflow:visible}.feedback-rich-editor.document>.feedback-editor-toolbar{position:sticky;z-index:14;top:120px;border:1px solid #dce3e7;border-radius:6px;box-shadow:0 3px 12px rgba(31,47,56,.12)}
.feedback-rich-editor.document :deep(.mermaid-document-block){position:relative;display:block}.feedback-rich-editor.document :deep(.mermaid-document-preview){display:grid;min-height:136px;place-items:center}.feedback-rich-editor.document :deep(.mermaid-delete-button){position:absolute;z-index:2;top:8px;right:8px;display:grid;width:30px;height:30px;padding:0;place-items:center;border:1px solid #d8e0e4;border-radius:4px;color:#687983;background:#fff;box-shadow:0 1px 4px rgba(31,47,56,.1);font-size:21px;line-height:1;cursor:pointer}.feedback-rich-editor.document :deep(.mermaid-delete-button:hover),.feedback-rich-editor.document :deep(.mermaid-delete-button:focus){border-color:#d76b65;color:#b83e38;background:#fff6f5;outline:none}
.document-image-input{display:none}
.feedback-rich-editor.document :deep(.document-image-block){position:relative;width:max-content;max-width:100%;margin:22px auto}.feedback-rich-editor.document :deep(.document-image-block img){margin:0}.feedback-rich-editor.document :deep(.document-image-delete){position:absolute;z-index:2;top:8px;right:8px;display:grid;width:30px;height:30px;padding:0;place-items:center;border:1px solid #d8e0e4;border-radius:4px;color:#687983;background:#fff;box-shadow:0 1px 4px rgba(31,47,56,.14);font-size:21px;line-height:1;cursor:pointer}.feedback-rich-editor.document :deep(.document-image-delete:hover),.feedback-rich-editor.document :deep(.document-image-delete:focus){border-color:#d76b65;color:#b83e38;background:#fff6f5;outline:none}
.feedback-rich-editor.document :deep(.document-image-block img){width:100%;height:auto}.feedback-rich-editor.document :deep(.document-image-resize){position:absolute;right:5px;bottom:5px;width:20px;height:20px;padding:0;border:0;border-right:3px solid #26816d;border-bottom:3px solid #26816d;background:transparent;cursor:nwse-resize}.feedback-rich-editor.document :deep(.document-image-resize:focus){outline:2px solid rgba(38,129,109,.25);outline-offset:2px}
@media(max-width:760px){.feedback-rich-editor.document>.feedback-editor-toolbar{top:120px}}
.feedback-rich-editor.document :deep(.mermaid-document-block),.feedback-rich-editor.document :deep(.mermaid-document-block:hover),.feedback-rich-editor.document :deep(.mermaid-document-block:focus){padding:0;border-color:transparent;background:transparent;box-shadow:none}.feedback-rich-editor.document :deep(.mermaid-delete-button){top:6px;right:6px;width:auto;height:28px;padding:0 9px;border:0;border-radius:4px;opacity:0;color:#fff;background:rgba(34,48,57,.78);box-shadow:none;font-size:12px;transition:opacity .15s}.feedback-rich-editor.document :deep(.mermaid-document-block:hover .mermaid-delete-button),.feedback-rich-editor.document :deep(.mermaid-document-block:focus-within .mermaid-delete-button){opacity:1}.feedback-rich-editor.document :deep(.mermaid-delete-button:hover),.feedback-rich-editor.document :deep(.mermaid-delete-button:focus){color:#fff;background:#b84b45}
.feedback-rich-editor.document :deep(.document-image-block){min-width:60px;min-height:60px}.feedback-rich-editor.document :deep(.document-image-block img){width:100%;height:100%;margin:0;border:0;border-radius:0;object-fit:fill}.feedback-rich-editor.document :deep(.document-image-delete){top:6px;right:6px;width:auto;height:28px;padding:0 9px;border:0;border-radius:4px;opacity:0;color:#fff;background:rgba(34,48,57,.78);box-shadow:none;font-size:12px;transition:opacity .15s}.feedback-rich-editor.document :deep(.document-image-block:hover .document-image-delete),.feedback-rich-editor.document :deep(.document-image-block:focus-within .document-image-delete){opacity:1}.feedback-rich-editor.document :deep(.document-image-delete:hover),.feedback-rich-editor.document :deep(.document-image-delete:focus){color:#fff;background:#b84b45}
.feedback-rich-editor.document :deep(.document-image-resize-frame){position:absolute;z-index:1;inset:-2px;border:1px solid #1677ff;opacity:0;pointer-events:none;transition:opacity .15s}.feedback-rich-editor.document :deep(.document-image-corner){position:absolute;width:9px;height:9px;border:1px solid #1677ff;background:#fff;box-shadow:0 1px 2px rgba(18,54,86,.18)}.feedback-rich-editor.document :deep(.document-image-corner.top-left){top:-5px;left:-5px}.feedback-rich-editor.document :deep(.document-image-corner.top-right){top:-5px;right:-5px}.feedback-rich-editor.document :deep(.document-image-corner.bottom-left){bottom:-5px;left:-5px}.feedback-rich-editor.document :deep(.document-image-corner.bottom-right){right:-5px;bottom:-5px}.feedback-rich-editor.document :deep(.document-image-block:hover .document-image-resize-frame),.feedback-rich-editor.document :deep(.document-image-block:focus-within .document-image-resize-frame),.feedback-rich-editor.document :deep(.document-image-block.is-resizing .document-image-resize-frame){opacity:1}.feedback-rich-editor.document :deep(.document-image-resize){position:absolute;z-index:3;padding:0;border:0;opacity:0;background:transparent}.feedback-rich-editor.document :deep(.resize-width){top:15%;right:-5px;width:10px;height:70%;cursor:ew-resize}.feedback-rich-editor.document :deep(.resize-height){bottom:-5px;left:15%;width:70%;height:10px;cursor:ns-resize}.feedback-rich-editor.document :deep(.resize-both){right:-7px;bottom:-7px;width:16px;height:16px;cursor:nwse-resize}.feedback-rich-editor.document :deep(.document-image-block:hover .document-image-resize),.feedback-rich-editor.document :deep(.document-image-block:focus-within .document-image-resize),.feedback-rich-editor.document :deep(.document-image-block.is-resizing .document-image-resize){opacity:1}.feedback-rich-editor.document :deep(.document-image-block:after){position:absolute;z-index:2;bottom:8px;left:50%;padding:3px 7px;border-radius:3px;opacity:0;color:#fff;background:rgba(34,48,57,.72);content:'右侧调宽 · 底部调高 · 右下自由缩放';font-size:11px;line-height:1.4;white-space:nowrap;pointer-events:none;transform:translateX(-50%);transition:opacity .15s}.feedback-rich-editor.document :deep(.document-image-block:hover:after),.feedback-rich-editor.document :deep(.document-image-block.is-resizing:after){opacity:1}
</style>
