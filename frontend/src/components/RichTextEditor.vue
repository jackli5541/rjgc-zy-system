<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import { AudioOutlined, BoldOutlined, CodeOutlined, LinkOutlined, OrderedListOutlined, StopOutlined, UndoOutlined, UnorderedListOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'

let activeSpeechStop = null

const props = defineProps({ modelValue: { type: String, default: '' }, placeholder: { type: String, default: '' }, compact: Boolean, autofocus: Boolean, speechEnabled: Boolean })
const emit = defineEmits(['update:modelValue'])
const speechSupported = ref(false)
const listening = ref(false)
const speechState = ref('idle')
const interimText = ref('')
const lastSpeechRange = ref(null)
let recognition = null
let speechStopRequested = false
let speechRestartTimer = 0
const editor = useEditor({
  content: props.modelValue,
  extensions: [StarterKit.configure({ link: { openOnClick: false } })],
  editorProps: { attributes: { 'data-placeholder': props.placeholder } },
  onCreate: ({ editor: instance }) => { if (props.autofocus) instance.commands.focus('end') },
  onUpdate: ({ editor: instance }) => emit('update:modelValue', instance.getHTML())
})

watch(() => props.modelValue, value => {
  if (editor.value && editor.value.getHTML() !== value) editor.value.commands.setContent(value || '', { emitUpdate: false })
})

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
</script>

<template>
  <div class="feedback-rich-editor" :class="{compact}">
    <div v-if="editor" class="feedback-editor-toolbar">
      <a-tooltip title="粗体"><a-button size="small" :type="editor.isActive('bold')?'primary':'default'" @click="editor.chain().focus().toggleBold().run()"><BoldOutlined/></a-button></a-tooltip>
      <a-tooltip title="无序列表"><a-button size="small" @click="editor.chain().focus().toggleBulletList().run()"><UnorderedListOutlined/></a-button></a-tooltip>
      <a-tooltip title="有序列表"><a-button size="small" @click="editor.chain().focus().toggleOrderedList().run()"><OrderedListOutlined/></a-button></a-tooltip>
      <a-tooltip title="链接"><a-button size="small" @click="setLink"><LinkOutlined/></a-button></a-tooltip>
      <a-tooltip title="代码块"><a-button size="small" @click="editor.chain().focus().toggleCodeBlock().run()"><CodeOutlined/></a-button></a-tooltip>
      <a-tooltip v-if="speechEnabled&&speechSupported" :title="listening?'停止语音输入':'语音输入'">
        <a-button size="small" :type="listening?'primary':'default'" :aria-pressed="listening" @click="toggleSpeechRecognition"><StopOutlined v-if="listening"/><AudioOutlined v-else/></a-button>
      </a-tooltip>
      <a-tooltip v-if="speechEnabled&&speechSupported&&lastSpeechRange" title="撤销最近一次语音输入"><a-button size="small" aria-label="撤销最近一次语音输入" @click="undoSpeechInput"><UndoOutlined/></a-button></a-tooltip>
      <span v-if="speechEnabled&&speechSupported&&speechLabel" class="speech-status">{{speechLabel}}</span>
    </div>
    <div v-if="speechEnabled&&speechSupported&&listening&&interimText" class="speech-interim">正在识别：{{interimText}}</div>
    <EditorContent :editor="editor"/>
  </div>
</template>

<style scoped>
.feedback-rich-editor{overflow:hidden;border:1px solid #d5dde5;border-radius:6px;background:#fff}.feedback-editor-toolbar{display:flex;align-items:center;gap:4px;padding:6px;border-bottom:1px solid #e7ecf1;background:#f7f9fb}.speech-status{margin-left:2px;color:#176b78;font-size:12px}.speech-interim{padding:5px 10px;color:#738496;background:#f8fafc;border-bottom:1px solid #edf1f4;font-size:12px;font-style:italic}.feedback-rich-editor :deep(.tiptap){min-height:104px;padding:10px 12px;outline:none;line-height:1.55}.feedback-rich-editor.compact :deep(.tiptap){min-height:76px}.feedback-rich-editor :deep(.tiptap p){margin:0 0 7px}.feedback-rich-editor :deep(.tiptap p:last-child){margin-bottom:0}.feedback-rich-editor :deep(.tiptap:empty:before){float:left;color:#a7b0ba;content:attr(data-placeholder);pointer-events:none}
</style>
