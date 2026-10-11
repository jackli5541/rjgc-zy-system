<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({ svg: { type: String, default: '' }, src: { type: String, default: '' }, alt: { type: String, default: '' } })
const emit = defineEmits(['close'])
const viewport = ref(null)
const diagram = ref(null)
const scale = ref(1)
const offset = ref({ x: 0, y: 0 })
let width = 1
let height = 1
let dragging = null
let previousOverflow = ''

function fit() {
  const rect = viewport.value?.getBoundingClientRect()
  if (!rect) return
  scale.value = Math.min(1, (rect.width - 48) / width, (rect.height - 48) / height)
  offset.value = { x: 0, y: 0 }
}

function measureDiagram() {
  const svg = diagram.value?.querySelector('svg')
  const viewBox = svg?.viewBox?.baseVal
  width = viewBox?.width || parseFloat(svg?.getAttribute('width')) || 800
  height = viewBox?.height || parseFloat(svg?.getAttribute('height')) || 600
  fit()
}

function measureImage(event) {
  width = event.target.naturalWidth || 1
  height = event.target.naturalHeight || 1
  fit()
}

function zoom(factor) {
  scale.value = Math.min(5, Math.max(.1, scale.value * factor))
}

function pointerDown(event) {
  if (event.button !== 0) return
  dragging = { x: event.clientX - offset.value.x, y: event.clientY - offset.value.y, id: event.pointerId }
  viewport.value?.setPointerCapture(event.pointerId)
}

function pointerMove(event) {
  if (!dragging || dragging.id !== event.pointerId) return
  offset.value = { x: event.clientX - dragging.x, y: event.clientY - dragging.y }
}

function pointerUp(event) {
  if (dragging?.id !== event.pointerId) return
  dragging = null
  if (viewport.value?.hasPointerCapture(event.pointerId)) viewport.value.releasePointerCapture(event.pointerId)
}

function wheel(event) {
  event.preventDefault()
  zoom(event.deltaY < 0 ? 1.15 : 1 / 1.15)
}

function keydown(event) {
  if (event.key === 'Escape') emit('close')
}

onMounted(async () => {
  previousOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  window.addEventListener('keydown', keydown)
  window.addEventListener('resize', fit)
  await nextTick()
  if (props.svg) measureDiagram()
})
onBeforeUnmount(() => {
  document.body.style.overflow = previousOverflow
  window.removeEventListener('keydown', keydown)
  window.removeEventListener('resize', fit)
})
</script>

<template>
  <Teleport to="body">
    <div class="media-lightbox-backdrop" @click.self="emit('close')">
      <div class="media-lightbox" role="dialog" aria-modal="true" :aria-label="src ? '图片预览' : 'Mermaid 图表预览'">
        <div class="media-lightbox-toolbar">
          <strong>{{ src ? '图片预览' : 'Mermaid 图表预览' }}</strong>
          <div class="media-lightbox-actions">
            <button type="button" aria-label="缩小" @click="zoom(1 / 1.2)">−</button>
            <span>{{ Math.round(scale * 100) }}%</span>
            <button type="button" aria-label="放大" @click="zoom(1.2)">＋</button>
            <button type="button" @click="fit">适应窗口</button>
            <button type="button" @click="scale=1; offset={ x: 0, y: 0 }">原始大小</button>
            <button type="button" aria-label="关闭" @click="emit('close')">×</button>
          </div>
        </div>
        <div ref="viewport" class="media-lightbox-viewport" :class="{ dragging: Boolean(dragging) }" @pointerdown="pointerDown" @pointermove="pointerMove" @pointerup="pointerUp" @pointercancel="pointerUp" @wheel="wheel" @dblclick="fit">
          <div class="media-lightbox-content" :style="{ width: width + 'px', height: height + 'px', transform: 'translate(-50%, -50%) translate(' + offset.x + 'px, ' + offset.y + 'px) scale(' + scale + ')' }">
            <img v-if="src" :src="src" :alt="alt" draggable="false" @load="measureImage">
            <div v-else ref="diagram" class="media-lightbox-diagram" v-html="svg"></div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.media-lightbox-backdrop{position:fixed;z-index:2100;inset:0;display:grid;place-items:center;padding:24px;background:rgba(20,31,39,.55)}
.media-lightbox{display:flex;width:min(1120px,100%);height:min(780px,100%);flex-direction:column;overflow:hidden;border-radius:10px;background:#fff;box-shadow:0 18px 60px rgba(25,45,60,.25)}
.media-lightbox-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:56px;padding:8px 18px;border-bottom:1px solid #dce5e9;color:#263b49;background:#f8fafb}
.media-lightbox-actions{display:flex;align-items:center;gap:8px}
.media-lightbox-actions button{min-height:32px;padding:4px 10px;border:1px solid #d4dfe4;border-radius:4px;color:#176b78;background:#fff;cursor:pointer}.media-lightbox-actions button:hover,.media-lightbox-actions button:focus-visible{border-color:#176b78;background:#edf7f7}
.media-lightbox-actions span{min-width:48px;text-align:center}
.media-lightbox-viewport{position:relative;flex:1;min-height:0;overflow:hidden;background:#fff;cursor:grab;touch-action:none}
.media-lightbox-viewport.dragging{cursor:grabbing}
.media-lightbox-content{position:absolute;top:50%;left:50%;transform-origin:center center;user-select:none}
.media-lightbox-content img,.media-lightbox-diagram,.media-lightbox-diagram :deep(svg){display:block;width:100%;height:100%;max-width:none!important;margin:0;user-select:none}
@media(max-width:760px){.media-lightbox-backdrop{padding:12px}.media-lightbox-toolbar{flex-wrap:wrap}.media-lightbox-actions{flex-wrap:wrap}}
</style>
