<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { MessageOutlined } from '@ant-design/icons-vue'
import { selectionActionPosition } from '../aiSelectionPosition'

const props = defineProps({ position: { type: Object, required: true }, selectionId: { type: String, required: true } })
const emit = defineEmits(['ask'])
const button = ref(null)
const style = ref({ visibility: 'hidden' })
let anchorOffset = null

function visibleTop(range) {
  const node = range.startContainer
  const parent = node?.nodeType === 1 ? node : node?.parentElement
  const toolbar = parent?.closest('.feedback-rich-editor')?.querySelector('.feedback-editor-toolbar')
  const header = document.querySelector('.app-header')
  return [header, toolbar].reduce((top, element) => {
    if (!element) return top
    const css = window.getComputedStyle(element)
    const rect = element.getBoundingClientRect()
    if (!['fixed', 'sticky'].includes(css.position) || css.display === 'none' || css.visibility === 'hidden' || rect.top >= window.innerHeight) return top
    return Math.max(top, rect.bottom)
  }, 0)
}

function updatePosition(reset = false) {
  const bounds = button.value?.getBoundingClientRect()
  const range = props.position.range
  if (!bounds || !range) return
  if (reset) anchorOffset = null
  const contentTop = visibleTop(range)
  const rectangles = range.getClientRects ? Array.from(range.getClientRects()) : [range.getBoundingClientRect()]
  const rect = rectangles.find(item => item.width > 0 && item.bottom > contentTop && item.top < window.innerHeight && item.right > 0 && item.left < window.innerWidth)
  if (range.startContainer?.isConnected === false || !rect) {
    style.value = { ...style.value, visibility: 'hidden' }
    return
  }
  if (!anchorOffset) {
    const chat = document.querySelector('.ai-teacher-window')?.getBoundingClientRect()
    const anchor = { left: rect.left, top: rect.top - bounds.height - 8 }
    const point = selectionActionPosition(anchor, bounds, { width: window.innerWidth, height: window.innerHeight }, chat)
    anchorOffset = { left: point.left - rect.left, top: point.top - rect.top }
  }
  const left = Math.max(8, Math.min(rect.left + anchorOffset.left, window.innerWidth - bounds.width - 8))
  const top = Math.min(rect.top + anchorOffset.top, window.innerHeight - bounds.height - 8)
  if (top < contentTop + 8) {
    style.value = { ...style.value, visibility: 'hidden' }
    return
  }
  style.value = { left: `${left}px`, top: `${top}px` }
}

function handleViewportChange() { updatePosition() }

watch(() => props.selectionId, () => updatePosition(true), { flush: 'post' })
onMounted(() => {
  updatePosition(true)
  window.addEventListener('resize', handleViewportChange)
  window.addEventListener('scroll', handleViewportChange, true)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', handleViewportChange)
  window.removeEventListener('scroll', handleViewportChange, true)
})
</script>

<template>
  <Teleport to="body"><button ref="button" type="button" class="ai-selection-action" :style="style" @pointerdown.prevent @click="emit('ask')"><MessageOutlined /> 问叶老师</button></Teleport>
</template>

<style scoped>
.ai-selection-action{position:fixed;z-index:969;padding:6px 10px;border:1px solid #bad5ce;border-radius:5px;background:#fff;color:#176f5b;box-shadow:0 3px 12px rgba(31,47,56,.18);cursor:pointer;white-space:nowrap}
</style>
