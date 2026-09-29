<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { CloseOutlined, CopyOutlined, PlusOutlined, SendOutlined, StopOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { api, apiStream, randomUUID } from '../../../api'
import { aiTeacherActionLabel, aiTeacherName } from '../aiTeacherConfig'
import { hasCompletedTurn, reconcileTurn } from '../aiTeacherChat'
import { createTypewriter } from '../aiTeacherTypewriter'
import { renderMarkdown } from '../../../markdownPreview'

const props = defineProps({
  open: Boolean,
  assignment: { type: Object, default: null },
  quote: { type: String, default: '' },
  quoteSource: { type: String, default: '' },
  quoteVersion: { type: Number, default: 0 }
})
const emit = defineEmits(['close'])

const loading = ref(false)
const sending = ref(false)
const verifying = ref(false)
const verificationPending = ref(false)
const input = ref('')
const messages = ref([])
const enabled = ref(true)
const selectedQuote = ref('')
const selectedQuoteSource = ref('')
const conversationId = ref('')
const windowSize = reactive({ width: 420, height: 500 })
let resizeObserver
let sendController
let answerTypewriter
const copiedMessageId = ref('')
let historyRequestId = 0
const windowRef = ref(null)
const messageListRef = ref(null)
const followLatest = ref(true)
const windowPosition = reactive({ left: 12, top: 12 })
const windowDrag = reactive({ active: false, pointerId: null, startX: 0, startY: 0, originLeft: 0, originTop: 0 })
const visibleMessages = computed(() => messages.value.filter(item => item.role !== 'assistant' || item.content?.trim()))

function handleMessageScroll() {
  const list = messageListRef.value
  if (!list) return
  followLatest.value = list.scrollHeight - list.scrollTop - list.clientHeight <= 72
}

async function scrollToLatest(force = false) {
  if (!force && !followLatest.value) return
  await nextTick()
  const list = messageListRef.value
  if (list && (force || followLatest.value)) {
    if (force) followLatest.value = true
    list.scrollTop = list.scrollHeight
  }
}

const assignmentId = computed(() => props.assignment?.id || '')
const storageKey = computed(() => `ai-teacher-window-${assignmentId.value}`)
const conversationKey = computed(() => `ai-teacher-conversation-${assignmentId.value}`)
const defaultWindowPosition = () => {
  return {
    left: Math.max(12, window.innerWidth - 444),
    top: Math.max(12, window.innerHeight - 524)
  }
}

const windowStyle = computed(() => ({ left: `${windowPosition.left}px`, top: `${windowPosition.top}px`, width: `${windowSize.width}px`, height: `${windowSize.height}px` }))

function resetWindowPosition() {
  let saved = null
  try { saved = JSON.parse(localStorage.getItem(storageKey.value) || 'null') } catch (_) { /* ignore invalid saved layout */ }
  Object.assign(windowSize, {
    width: Number.isFinite(saved?.width) && saved.width > 0 ? saved.width : 420,
    height: Number.isFinite(saved?.height) && saved.height > 0 ? saved.height : 500
  })
  Object.assign(windowPosition, Number.isFinite(saved?.left) && Number.isFinite(saved?.top)
    ? { left: saved.left, top: saved.top }
    : defaultWindowPosition())
}

function saveWindowLayout() {
  localStorage.setItem(storageKey.value, JSON.stringify({ ...windowPosition, ...windowSize }))
}

function rememberWindowSize() {
  const rect = windowRef.value?.getBoundingClientRect()
  if (!rect || rect.width <= 0 || rect.height <= 0) return
  windowSize.width = Math.round(rect.width)
  windowSize.height = Math.round(rect.height)
  saveWindowLayout()
}

function clampWindowPosition(left, top) {
  const rect = windowRef.value?.getBoundingClientRect()
  const width = rect?.width || windowSize.width
  const height = rect?.height || windowSize.height
  windowPosition.left = Math.min(Math.max(12, left), Math.max(12, window.innerWidth - width - 12))
  windowPosition.top = Math.min(Math.max(12, top), Math.max(12, window.innerHeight - height - 12))
  saveWindowLayout()
}

function startWindowDrag(event) {
  const target = event.target
  if (event.button !== 0 || target instanceof Element && target.closest('button')) return
  event.preventDefault()
  windowDrag.active = true
  windowDrag.pointerId = event.pointerId
  windowDrag.startX = event.clientX
  windowDrag.startY = event.clientY
  windowDrag.originLeft = windowPosition.left
  windowDrag.originTop = windowPosition.top
  event.currentTarget.setPointerCapture?.(event.pointerId)
  window.addEventListener('pointermove', moveWindowDrag)
  window.addEventListener('pointerup', stopWindowDrag)
  window.addEventListener('pointercancel', stopWindowDrag)
}

function moveWindowDrag(event) {
  if (!windowDrag.active || event.pointerId !== windowDrag.pointerId) return
  clampWindowPosition(
    windowDrag.originLeft + event.clientX - windowDrag.startX,
    windowDrag.originTop + event.clientY - windowDrag.startY
  )
}

function stopWindowDrag(event) {
  if (!windowDrag.active || (event?.pointerId != null && event.pointerId !== windowDrag.pointerId)) return
  windowDrag.active = false
  windowDrag.pointerId = null
  window.removeEventListener('pointermove', moveWindowDrag)
  window.removeEventListener('pointerup', stopWindowDrag)
  window.removeEventListener('pointercancel', stopWindowDrag)
}

function clampWindowSize() {
  windowSize.width = Math.min(Math.max(300, windowSize.width), Math.max(1, window.innerWidth - 24))
  windowSize.height = Math.min(Math.max(320, windowSize.height), Math.max(1, window.innerHeight - 24))
  clampWindowPosition(windowPosition.left, windowPosition.top)
}

function handleViewportResize() { if (props.open) clampWindowSize() }

function newConversation() {
  answerTypewriter?.cancel()
  sendController?.abort()
  conversationId.value = randomUUID()
  localStorage.setItem(conversationKey.value, conversationId.value)
  messages.value = []
  input.value = ''
  selectedQuote.value = ''
  selectedQuoteSource.value = ''
  verificationPending.value = false
  historyRequestId += 1
  scrollToLatest(true)
}

function renderAssistantContent(content) {
  const source = String(content || '')
    .replace(/\\([*_#`~>])/g, '$1')
    .replace(/^(#{1,6})([^\s#])/gm, '$1 $2')
  return renderMarkdown(source)
}

function normalizeMessage(item) {
  return item.role === 'assistant'
    ? { ...item, renderedContent: renderAssistantContent(item.content) }
    : item
}

async function copyAnswer(item) {
  try {
    await navigator.clipboard.writeText(String(item.content || ''))
    copiedMessageId.value = item.id
    window.setTimeout(() => { if (copiedMessageId.value === item.id) copiedMessageId.value = '' }, 1600)
  } catch (_) {
    message.warning('复制失败，请手动选择回答内容')
  }
}

async function loadHistory() {
  if (!assignmentId.value || !props.open) return
  const requestId = ++historyRequestId
  loading.value = true
  try {
    const data = await api('/assignments/' + assignmentId.value + '/ai-teacher/history?conversation_id=' + conversationId.value)
    if (requestId !== historyRequestId) return
    messages.value = (data.messages || []).map(normalizeMessage)
    enabled.value = data.enabled !== false
    verificationPending.value = false
  } catch (error) {
    message.error(error.message)
  } finally {
    loading.value = false
    if (requestId === historyRequestId && props.open) await scrollToLatest(true)
  }
}

async function sendQuestion() {
  const question = input.value.trim()
  if (!question || loading.value || sending.value || verifying.value || verificationPending.value || !assignmentId.value) return
  historyRequestId += 1
  const quote = selectedQuote.value
  const quoteSource = quote ? selectedQuoteSource.value : ''
  const requestAssignmentId = assignmentId.value
  const requestConversationId = conversationId.value
  const localUserMessage = { id: randomUUID(), role: 'user', content: question, contexts: quote ? [{ quote }] : [] }
  const localAnswer = reactive({ id: 'stream-' + Date.now(), role: 'assistant', content: '', renderedContent: '' })
  messages.value.push(localUserMessage)
  messages.value.push(localAnswer)
  scrollToLatest(true)
  input.value = ''
  selectedQuote.value = ''
  selectedQuoteSource.value = ''
  sending.value = true
  sendController = new AbortController()
  const typewriter = createTypewriter(text => {
    if (!props.open || conversationId.value !== requestConversationId || assignmentId.value !== requestAssignmentId) return
    localAnswer.content = text
    localAnswer.renderedContent = renderAssistantContent(text)
    scrollToLatest()
  })
  answerTypewriter = typewriter
  let completed = false
  const applyCompletedTurn = saved => {
    const userMessage = saved.find(item => item.id === localUserMessage.id && item.role === 'user')
    const assistantMessage = saved[saved.indexOf(userMessage) + 1]
    if (!userMessage || assistantMessage?.role !== 'assistant') return false
    typewriter.finish()
    messages.value = messages.value.map(item => item.id === localUserMessage.id
      ? normalizeMessage(userMessage)
      : item.id === localAnswer.id ? normalizeMessage(assistantMessage) : item)
    input.value = ''
    selectedQuote.value = ''
    selectedQuoteSource.value = ''
    verificationPending.value = false
    completed = true
    scrollToLatest()
    return true
  }
  try {
    const reader = await apiStream('/assignments/' + requestAssignmentId + '/ai-teacher/chat', { question, quote, quote_source: quoteSource || undefined, conversation_id: requestConversationId, message_id: localUserMessage.id }, sendController.signal)
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let boundary
      while ((boundary = buffer.replace(/\r\n/g, '\n').indexOf('\n\n')) >= 0) {
        buffer = buffer.replace(/\r\n/g, '\n')
        const frame = buffer.slice(0, boundary).replace(/\r/g, '')
        buffer = buffer.slice(boundary + 2)
        const event = frame.match(/^event: (.+)$/m)?.[1]
        const payload = frame.match(/^data: (.+)$/m)?.[1]
        if (!payload) continue
        const data = JSON.parse(payload)
        if (event === 'delta') {
          if (conversationId.value !== requestConversationId || assignmentId.value !== requestAssignmentId) continue
          typewriter.append(data.text)
        } else if (event === 'done') {
          if (conversationId.value !== requestConversationId || assignmentId.value !== requestAssignmentId) continue
          if (!applyCompletedTurn(data.messages || [])) throw new Error('回答记录不完整，请稍后重试')
        } else if (event === 'error') throw new Error(data.message || '叶老师暂时无法回答')
      }
    }
    if (!completed) throw new Error('回答中断，请重试')
  } catch (error) {
    typewriter.cancel()
    if (conversationId.value === requestConversationId && assignmentId.value === requestAssignmentId) {
      verifying.value = true
      try {
        const history = await api('/assignments/' + requestAssignmentId + '/ai-teacher/history?conversation_id=' + requestConversationId)
        if (conversationId.value !== requestConversationId || assignmentId.value !== requestAssignmentId) return
        const stored = history.messages || []
        const reconciled = reconcileTurn(stored, localUserMessage.id, question, quote)
        if (reconciled.completed) {
          messages.value = stored.map(normalizeMessage)
          input.value = ''
          selectedQuote.value = ''
          selectedQuoteSource.value = ''
          verificationPending.value = false
          scrollToLatest()
        } else {
          input.value = question
          selectedQuote.value = quote
          selectedQuoteSource.value = quote ? quoteSource : ''
          messages.value = messages.value.filter(item => item.id !== localUserMessage.id && item.id !== localAnswer.id)
          verificationPending.value = false
          if (error.name !== 'AbortError') message.error(error.message)
        }
      } catch (_) {
        if (conversationId.value === requestConversationId && assignmentId.value === requestAssignmentId) {
          verificationPending.value = true
          message.warning('无法确认回答是否已保存，请重新打开聊天窗口查看记录')
        }
      } finally {
        verifying.value = false
      }
    }
  } finally {
    typewriter.cancel()
    if (answerTypewriter === typewriter) answerTypewriter = null
    sending.value = false
    sendController = null
  }
}

function stopAnswer() { answerTypewriter?.cancel(); sendController?.abort() }

watch(() => props.quoteVersion, () => {
  selectedQuote.value = props.quote || ''
  selectedQuoteSource.value = selectedQuote.value ? props.quoteSource || '' : ''
})

watch(() => props.open, async value => {
  if (!value) {
    historyRequestId += 1
    stopAnswer()
    stopWindowDrag()
    resizeObserver?.disconnect()
    resizeObserver = null
    rememberWindowSize()
    return
  }
  conversationId.value = localStorage.getItem(conversationKey.value) || randomUUID()
  localStorage.setItem(conversationKey.value, conversationId.value)
  resetWindowPosition()
  await nextTick()
  if (!props.open || !windowRef.value) return
  clampWindowSize()
  resizeObserver?.disconnect()
  resizeObserver = new ResizeObserver(entries => {
    if (props.open && entries[0]?.target.isConnected) {
      rememberWindowSize()
      clampWindowPosition(windowPosition.left, windowPosition.top)
    }
  })
  resizeObserver.observe(windowRef.value)
  loadHistory()
}, { immediate: true, flush: 'sync' })

window.addEventListener('resize', handleViewportResize)
onBeforeUnmount(() => {
  stopAnswer()
  stopWindowDrag()
  resizeObserver?.disconnect()
  rememberWindowSize()
  window.removeEventListener('resize', handleViewportResize)
})
</script>

<template>
  <Teleport to="body">
    <section v-if="open" ref="windowRef" class="ai-teacher-window" :style="windowStyle" role="dialog" :aria-label="aiTeacherActionLabel">
      <header class="ai-teacher-window-header" @pointerdown="startWindowDrag">
        <strong>{{ aiTeacherActionLabel }}</strong>
        <div @pointerdown.stop>
          <a-button type="text" class="ai-new-conversation" aria-label="新建对话" title="新建对话" @click="newConversation"><PlusOutlined /> 新建对话</a-button>
          <a-button type="text" shape="circle" aria-label="隐藏聊天窗口" title="隐藏聊天窗口" @click="emit('close')"><CloseOutlined /></a-button>
        </div>
      </header>
      <div class="ai-teacher-panel">
      <div ref="messageListRef" class="ai-message-list" @scroll.passive="handleMessageScroll">
        <a-skeleton v-if="loading" active :paragraph="{ rows: 5 }" />
        <a-empty v-else-if="!messages.length" :description="`还没有向${aiTeacherName}提问`" />
        <article v-for="item in visibleMessages" v-else :key="item.id" class="ai-message" :class="item.role">
          <div v-if="item.role === 'assistant'" class="ai-answer">
            <div class="ai-answer-content" v-html="item.renderedContent || renderAssistantContent(item.content)"></div>
            <div class="ai-answer-actions" aria-label="回答操作">
              <button type="button" :title="copiedMessageId === item.id ? '已复制' : '复制回答'" :aria-label="copiedMessageId === item.id ? '已复制' : '复制回答'" @click="copyAnswer(item)"><CopyOutlined /></button>
            </div>
          </div>
          <div v-else class="ai-user-content"><blockquote v-if="item.contexts?.[0]?.quote">{{ item.contexts[0].quote }}</blockquote>{{ item.content }}</div>
        </article>
      </div>
      <div class="ai-teacher-composer">
        <div v-if="selectedQuote" class="ai-teacher-quote"><span>{{ selectedQuote }}</span><button type="button" aria-label="移除引用" title="移除引用" @click="selectedQuote=''; selectedQuoteSource=''">×</button></div>
        <div v-if="verificationPending" class="ai-verification-warning">回答状态未确认，请关闭后重新打开查看记录。</div>
        <a-textarea
          v-model:value="input"
          :rows="3"
          :maxlength="2000"
          :disabled="loading || sending || verifying || verificationPending || !enabled"
          placeholder="描述你卡住的地方，例如：我不知道怎么写需求分析的参与者部分"
          @keydown.enter.exact.prevent="sendQuestion"
        />
        <div class="ai-composer-actions">
          <span></span>
          <a-button v-if="sending" @click="stopAnswer"><StopOutlined /> 停止</a-button>
          <a-button v-else type="primary" :disabled="!input.trim() || verifying || verificationPending || !enabled" @click="sendQuestion"><SendOutlined /> 发送</a-button>
        </div>
      </div>
      </div>
    </section>
  </Teleport>
</template>

<style scoped>
.ai-teacher-window{position:fixed;z-index:970;display:flex;min-width:min(300px,calc(100vw - 24px));min-height:min(320px,calc(100vh - 24px));max-width:calc(100vw - 24px);max-height:calc(100vh - 24px);box-sizing:border-box;resize:both;flex-direction:column;overflow:hidden;border:1px solid #d8e2e7;border-radius:8px;background:#fff;box-shadow:0 18px 54px rgba(27,45,58,.22)}
.ai-teacher-window-header{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:48px;padding:0 12px 0 16px;border-bottom:1px solid #e7edf1;background:#fff;cursor:move;user-select:none;touch-action:none}
.ai-teacher-window-header strong{overflow:hidden;color:#1f3440;text-overflow:ellipsis;white-space:nowrap;font-size:15px}
.ai-teacher-window-header>div{display:flex;align-items:center;gap:3px;cursor:auto}
.ai-new-conversation{display:inline-flex;align-items:center;gap:4px;white-space:nowrap}
.ai-teacher-panel{display:flex;min-height:0;flex:1;flex-direction:column;gap:10px;overflow:hidden;padding:10px 12px 12px}
.ai-message-list{display:flex;min-height:0;flex:1 1 0;flex-direction:column;gap:18px;overflow:auto;padding:4px 2px 8px}
.ai-message{max-width:94%;color:#24343d}
.ai-message.user{align-self:flex-end;max-width:82%}
.ai-message.assistant{align-self:flex-start;width:100%}
.ai-user-content{margin:0;padding:10px 14px;border-radius:16px 16px 4px 16px;background:#f1f3f5;color:#1f2d35;white-space:pre-wrap;line-height:1.65}
.ai-user-content blockquote{max-height:90px;margin:0 0 8px;padding:4px 8px;overflow:auto;border-left:3px solid #168269;color:#667984;background:#fff;font-size:12px}
.ai-teacher-quote{display:flex;max-height:90px;gap:8px;padding:7px 9px;overflow:auto;border-left:3px solid #168269;background:#f3f8f6;color:#40545b;font-size:12px}.ai-teacher-quote span{flex:1;white-space:pre-wrap}.ai-teacher-quote button{align-self:flex-start;border:0;background:transparent;cursor:pointer}
.ai-verification-warning{color:#ad6919;font-size:12px;line-height:1.5}
.ai-answer{min-width:0}
.ai-answer-content{font-size:14px;line-height:1.72;overflow-wrap:anywhere}
.ai-answer-content :deep(h1){margin:0 0 12px;font-size:20px;line-height:1.35}
.ai-answer-content :deep(h2){margin:14px 0 7px;font-size:17px;line-height:1.4}
.ai-answer-content :deep(h3){margin:12px 0 6px;font-size:15px;line-height:1.4}
.ai-answer-content :deep(p){margin:0 0 9px}
.ai-answer-content :deep(p:last-child),.ai-answer-content :deep(ul:last-child),.ai-answer-content :deep(ol:last-child),.ai-answer-content :deep(pre:last-child),.ai-answer-content :deep(blockquote:last-child){margin-bottom:0}
.ai-answer-content :deep(ul),.ai-answer-content :deep(ol){margin:0 0 9px;padding-left:22px}
.ai-answer-content :deep(blockquote){margin:9px 0;padding:8px 10px;border-left:3px solid #25866f;background:#f3f8f6;color:#53666e}
.ai-answer-content :deep(pre){max-width:100%;margin:9px 0;padding:10px;overflow:auto;border-radius:5px;background:#f4f6f8}
.ai-answer-content :deep(code){font-size:12px}
.ai-answer-content :deep(table){display:block;max-width:100%;overflow:auto;border-collapse:collapse}
.ai-answer-content :deep(th),.ai-answer-content :deep(td){padding:6px 8px;border:1px solid #cfd8e1}
.ai-answer-actions{display:flex;align-items:center;gap:4px;margin-top:8px;color:#8a949a}
.ai-answer-actions button{display:grid;width:28px;height:28px;place-items:center;padding:0;border:0;border-radius:6px;color:inherit;background:transparent;cursor:pointer}
.ai-answer-actions button:hover{color:#40515a;background:#f0f3f4}
.ai-teacher-composer{display:grid;flex:0 0 auto;gap:9px;min-height:0;padding-top:12px;border-top:1px solid #e2e8ed}
.ai-teacher-composer :deep(.ant-input){resize:vertical}
.ai-composer-actions{display:flex;align-items:center;justify-content:space-between;gap:10px;min-height:40px}
.ai-composer-actions span{display:flex;min-width:0;align-items:center;gap:5px;color:#7b8993;font-size:12px;line-height:1.4}
.ai-composer-actions :deep(.ant-btn){display:inline-flex;align-items:center;justify-content:center;min-width:84px;height:40px;white-space:nowrap}
@media(max-width:600px){.ai-teacher-window{resize:vertical}.ai-teacher-panel{padding:8px}.ai-teacher-window-header{min-height:44px}}
</style>
