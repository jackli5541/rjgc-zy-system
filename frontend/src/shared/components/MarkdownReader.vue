<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import MaterialResizeHandle from './MaterialResizeHandle.vue'
import RichTextViewer from './RichTextViewer.vue'
import DocumentCanvas from './DocumentCanvas.vue'

const props = defineProps({ html: { type: String, default: '' }, outlineOpen: Boolean, textScale: { type: Number, default: 100 }, pageScale: { type: Number, default: 100 }, annotations: { type: Array, default: () => [] }, editable: Boolean, selectedAnnotationId: { type: String, default: '' }, regionLabel: { type: String, default: '教学资料正文' }, resetKey: { type: String, default: '' } })
const emit = defineEmits(['close-outline', 'selection', 'select'])
const outlineWidth = ref(240)
const root = ref(null)
const viewer = ref(null)
defineExpose({
  viewportRect: () => root.value?.getBoundingClientRect(),
  annotationRect: id => viewer.value?.annotationRect?.(id),
  focusAnnotation: id => viewer.value?.focusAnnotation?.(id)
})
const headings = ref([])
const collapsed = ref(new Set())
const active = ref(-1)
let elements = []
let frame = 0
let headingFrame = 0
const visibleHeadings = computed(() => headings.value.filter(item => !item.parents.some(id => collapsed.value.has(id))))

function toggle(id) {
  const next = new Set(collapsed.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  collapsed.value = next
}

function navigationInset() {
  const viewport = root.value
  const toolbar = viewport?.querySelector?.('.feedback-editor-toolbar')
  return toolbar ? Math.max(20, toolbar.getBoundingClientRect().bottom - viewport.getBoundingClientRect().top + 12) : 20
}

function locate(id) {
  // Editors can replace heading DOM before the deferred outline scan runs.
  rebuildHeadings()
  const element = elements[id]
  const viewport = root.value
  if (!element || !viewport) return
  // Focusing a contenteditable heading can restore the editor's old caret and
  // scroll back. Reading headings can still receive keyboard focus safely.
  if (!element.isContentEditable) element.focus({ preventScroll: true })
  viewport.scrollTo({ top: viewport.scrollTop + element.getBoundingClientRect().top - viewport.getBoundingClientRect().top - navigationInset(), behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
  active.value = id
}

function updateActive() {
  cancelAnimationFrame(frame)
  frame = requestAnimationFrame(() => {
    let current = elements.length ? 0 : -1
    const threshold = (root.value?.getBoundingClientRect().top || 0) + navigationInset() + 20
    elements.forEach((element, index) => {
      if (element.getBoundingClientRect().top <= threshold) current = index
    })
    active.value = current
  })
}

function rebuildHeadings() {
  elements = [...(root.value?.querySelectorAll('.rich-document-content h1, .rich-document-content h2, .rich-document-content h3, .rich-document-content h4, .rich-document-content h5, .rich-document-content h6, .tiptap h1, .tiptap h2, .tiptap h3, .tiptap h4, .tiptap h5, .tiptap h6') || [])]
  const stack = []
  headings.value = elements.map((element, id) => {
    const level = Number(element.tagName.slice(1))
    while (stack.length && stack[stack.length - 1].level >= level) stack.pop()
    const item = { id, level, text: element.textContent.trim() || '未命名标题', parents: stack.map(parent => parent.id), depth: stack.length, children: false }
    if (stack.length) stack[stack.length - 1].children = true
    stack.push(item)
    // Keep the editor-owned DOM untouched; tabindex mutations can cause its
    // document observer to replace these headings and invalidate navigation.
    if (!element.isContentEditable) element.tabIndex = -1
    return item
  })
  updateActive()
}

function scheduleHeadings() {
  if (headingFrame) return
  headingFrame = requestAnimationFrame(() => {
    headingFrame = 0
    rebuildHeadings()
  })
}

// Slotted editors can mount after the HTML prop has already arrived. Observe
// their actual heading nodes as well as prop changes and outline reopening.
watch(root, (element, previous, onCleanup) => {
  if (!element) return
  const observer = new MutationObserver(scheduleHeadings)
  observer.observe(element, { childList: true, characterData: true, subtree: true })
  rebuildHeadings()
  onCleanup(() => observer.disconnect())
}, { flush: 'post' })

watch([() => props.html, () => props.resetKey, () => props.outlineOpen], async () => {
  await nextTick()
  rebuildHeadings()
}, { immediate: true, flush: 'post' })

watch(() => props.resetKey, () => {
  collapsed.value = new Set()
  if (root.value) root.value.scrollTop = 0
})

onBeforeUnmount(() => {
  cancelAnimationFrame(frame)
  cancelAnimationFrame(headingFrame)
})
</script>

<template>
  <div class="material-markdown-layout" :class="{ 'outline-open': outlineOpen }" :style="{ '--material-outline-width': `${outlineWidth}px`, '--material-text-scale': textScale / 100 }">
    <div ref="root" class="teaching-material-rich" role="region" :aria-label="regionLabel" tabindex="0" @scroll="updateActive"><slot><DocumentCanvas :scale="pageScale"><RichTextViewer ref="viewer" :html="html" :annotations="annotations" :editable="editable" :selected-annotation-id="selectedAnnotationId" @selection="emit('selection', $event)" @select="(...args) => emit('select', ...args)" /></DocumentCanvas></slot></div>
    <nav v-if="outlineOpen" class="material-outline" aria-label="文档大纲">
      <MaterialResizeHandle v-model="outlineWidth" :min="160" :max="480" reverse label="大纲宽度" />
      <div class="material-outline-title">大纲<button type="button" aria-label="关闭大纲" @click="emit('close-outline')">收起</button></div>
      <div class="material-outline-items">
      <p v-if="!headings.length" class="material-outline-empty">本文暂无标题</p>
      <div v-for="item in visibleHeadings" :key="item.id" class="material-outline-row" :style="{ paddingLeft: `${item.depth * 14}px` }">
        <button v-if="item.children" type="button" class="material-outline-toggle" :aria-label="`${collapsed.has(item.id) ? '展开' : '折叠'}${item.text}`" :aria-expanded="!collapsed.has(item.id)" @click="toggle(item.id)">{{ collapsed.has(item.id) ? '▸' : '▾' }}</button>
        <span v-else class="material-outline-spacer" />
        <button type="button" class="material-outline-link" :class="{ active: active === item.id }" :aria-current="active === item.id ? 'location' : undefined" :title="item.text" @click="locate(item.id)">{{ item.text }}</button>
      </div>
      </div>
    </nav>
  </div>
</template>

<style scoped>
/* Override the viewer's fixed typography only in the materials reader. */
.teaching-material-rich :deep(.rich-document){width:100%;max-width:none;box-sizing:border-box;padding:clamp(18px,2vw,36px);font-size:calc(15px * var(--material-text-scale,1))}
.teaching-material-rich :deep(.rich-document h1){font-size:2em}
.teaching-material-rich :deep(.rich-document h2){font-size:1.4em}
.teaching-material-rich :deep(.rich-document h3){font-size:1.17em}
</style>
