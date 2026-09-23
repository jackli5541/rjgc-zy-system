<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { BorderOutlined, ColumnWidthOutlined, ZoomInOutlined, ZoomOutOutlined } from '@ant-design/icons-vue'
import { getDocument, GlobalWorkerOptions, TextLayer } from 'pdfjs-dist'
import 'pdfjs-dist/web/pdf_viewer.css'

GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString()

const props = defineProps({ url: { type: String, default: '' }, annotations: { type: Array, default: () => [] }, editable: Boolean, selectedAnnotationId: { type: String, default: '' } })
const emit = defineEmits(['selection', 'select', 'layout', 'error'])
const stage = ref(null)
const pages = ref([])
const scale = ref(1.2)
const currentPage = ref(1)
const regionMode = ref(false)
const draftRect = ref(null)
let pdfDocument = null
let loadingTask = null
let observer = null
let drag = null
const renderedAtScale = new Map()

const pageAnnotations = computed(() => {
  const grouped = new Map()
  props.annotations.forEach((annotation, annotationIndex) => {
    const page = annotation.anchor?.page
    if (!grouped.has(page)) grouped.set(page, [])
    grouped.get(page).push({ ...annotation, ordinal: annotationIndex + 1 })
  })
  return grouped
})

async function load() {
  if (!props.url) return
  try {
    if (loadingTask) await loadingTask.destroy()
    renderedAtScale.clear(); pages.value = []
    const response = await fetch(props.url, { credentials: 'include' })
    if (!response.ok) throw new Error('PDF 文件加载失败')
    loadingTask = getDocument({ data: await response.arrayBuffer() })
    pdfDocument = await loadingTask.promise
    const metadata = []
    for (let number = 1; number <= pdfDocument.numPages; number += 1) {
      const page = await pdfDocument.getPage(number)
      const viewport = page.getViewport({ scale: 1 })
      metadata.push({ number, width: viewport.width, height: viewport.height })
    }
    pages.value = metadata
    await nextTick()
    fitWidth()
    observePages()
  } catch (error) { emit('error', error.message || 'PDF 文件加载失败') }
}

function observePages() {
  observer?.disconnect()
  observer = new IntersectionObserver(entries => entries.forEach(entry => {
    if (entry.isIntersecting) {
      const number = Number(entry.target.dataset.page)
      currentPage.value = number
      renderPage(number)
    }
  }), { root: stage.value, rootMargin: '500px 0px', threshold: .05 })
  stage.value?.querySelectorAll('.pdf-page').forEach(element => observer.observe(element))
}

async function renderPage(number) {
  if (!pdfDocument || renderedAtScale.get(number) === scale.value) return
  const container = stage.value?.querySelector(`[data-page="${number}"]`)
  const canvas = container?.querySelector('canvas')
  const textContainer = container?.querySelector('.textLayer')
  if (!canvas || !textContainer) return
  const page = await pdfDocument.getPage(number)
  const viewport = page.getViewport({ scale: scale.value })
  const outputScale = window.devicePixelRatio || 1
  canvas.width = Math.floor(viewport.width * outputScale)
  canvas.height = Math.floor(viewport.height * outputScale)
  canvas.style.width = `${viewport.width}px`; canvas.style.height = `${viewport.height}px`
  const context = canvas.getContext('2d')
  await page.render({ canvasContext: context, viewport, transform: outputScale === 1 ? null : [outputScale, 0, 0, outputScale, 0, 0] }).promise
  textContainer.replaceChildren()
  const textLayer = new TextLayer({ textContentSource: page.streamTextContent(), container: textContainer, viewport })
  await textLayer.render()
  renderedAtScale.set(number, scale.value)
}

async function setScale(value) {
  scale.value = Math.min(3, Math.max(.5, value))
  renderedAtScale.clear()
  await nextTick()
  observePages()
  emit('layout')
}

function fitWidth() {
  const first = pages.value[0]
  if (!first || !stage.value) return
  setScale((stage.value.clientWidth - 48) / first.width)
}

function jumpToPage(value) {
  const page = Math.min(pages.value.length, Math.max(1, Number(value) || 1))
  stage.value?.querySelector(`[data-page="${page}"]`)?.scrollIntoView({ block: 'start' })
}

function createTextAnnotation() {
  if (!props.editable || regionMode.value || !stage.value) return
  const selection = window.getSelection()
  if (!selection || selection.isCollapsed || !selection.rangeCount) return
  const range = selection.getRangeAt(0)
  const element = range.commonAncestorContainer.nodeType === Node.TEXT_NODE ? range.commonAncestorContainer.parentElement : range.commonAncestorContainer
  const pageElement = element?.closest?.('.pdf-page')
  if (!pageElement || !stage.value.contains(pageElement)) return
  const pageRect = pageElement.getBoundingClientRect()
  const rects = Array.from(range.getClientRects()).flatMap(rect => {
    const left = Math.max(pageRect.left, rect.left)
    const top = Math.max(pageRect.top, rect.top)
    const right = Math.min(pageRect.right, rect.right)
    const bottom = Math.min(pageRect.bottom, rect.bottom)
    if (right <= left || bottom <= top) return []
    return [{
      x: (left - pageRect.left) / pageRect.width,
      y: (top - pageRect.top) / pageRect.height,
      width: (right - left) / pageRect.width,
      height: (bottom - top) / pageRect.height
    }]
  })
  const selectionRect = range.getBoundingClientRect()
  if (rects.length) emit('selection', { kind: 'PDF_TEXT_OR_REGION', selectionType: 'TEXT', viewportRect: { left: selectionRect.left, top: selectionRect.top, right: selectionRect.right, bottom: selectionRect.bottom, width: selectionRect.width, height: selectionRect.height }, anchor: { page: Number(pageElement.dataset.page), rects, quote: selection.toString().trim() } })
}

function regionStart(event, page) {
  if (!regionMode.value || !props.editable) return
  const rect = event.currentTarget.getBoundingClientRect()
  drag = { page, x: (event.clientX - rect.left) / rect.width, y: (event.clientY - rect.top) / rect.height, element: event.currentTarget }
  event.currentTarget.setPointerCapture(event.pointerId)
}
function regionMove(event) {
  if (!drag) return
  const rect = drag.element.getBoundingClientRect()
  const x = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width))
  const y = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height))
  draftRect.value = { page: drag.page, x: Math.min(drag.x, x), y: Math.min(drag.y, y), width: Math.abs(x - drag.x), height: Math.abs(y - drag.y) }
}
function regionEnd() {
  if (draftRect.value?.width > .005 && draftRect.value?.height > .005) {
    const rect = drag.element.getBoundingClientRect()
    const left = rect.left + draftRect.value.x * rect.width
    const top = rect.top + draftRect.value.y * rect.height
    const width = draftRect.value.width * rect.width
    const height = draftRect.value.height * rect.height
    emit('selection', { kind: 'PDF_TEXT_OR_REGION', selectionType: 'REGION', viewportRect: { left, top, right: left + width, bottom: top + height, width, height }, anchor: { page: draftRect.value.page, rects: [{ x: draftRect.value.x, y: draftRect.value.y, width: draftRect.value.width, height: draftRect.value.height }], quote: '' } })
  }
  drag = null; draftRect.value = null; regionMode.value = false
}

function focusAnnotation(id) {
  if (!id) return
  const target = stage.value?.querySelector(`[data-annotation-id="${id}"]`)
  if (!target) return
  target.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'center' })
  if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) target.animate([{ filter: 'brightness(1)' }, { filter: 'brightness(1.28)' }, { filter: 'brightness(1)' }], { duration: 650, easing: 'ease' })
}

function annotationRect(id) {
  return stage.value?.querySelector(`[data-comment-annotation-id="${id}"]`)?.getBoundingClientRect() || stage.value?.querySelector(`[data-annotation-id="${id}"]`)?.getBoundingClientRect() || null
}

function viewportRect() { return stage.value?.getBoundingClientRect() || null }

defineExpose({ focusAnnotation, annotationRect, viewportRect })

function selectExisting(id, event, openBubble = false) {
  const rect = event.currentTarget.getBoundingClientRect()
  emit('select', { id, openBubble, viewportRect: { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height } })
}

watch(() => props.url, load)
watch(() => props.selectedAnnotationId, focusAnnotation)
onMounted(() => { load(); window.addEventListener('resize', fitWidth) })
onBeforeUnmount(async () => { observer?.disconnect(); window.removeEventListener('resize', fitWidth); if (loadingTask) await loadingTask.destroy() })
</script>

<template>
  <div class="pdf-viewer-shell">
    <div class="pdf-viewer-toolbar">
      <a-tooltip title="缩小"><a-button shape="circle" @click="setScale(scale-.15)"><ZoomOutOutlined/></a-button></a-tooltip>
      <span>{{Math.round(scale*100)}}%</span>
      <a-tooltip title="放大"><a-button shape="circle" @click="setScale(scale+.15)"><ZoomInOutlined/></a-button></a-tooltip>
      <a-tooltip title="适应宽度"><a-button shape="circle" @click="fitWidth"><ColumnWidthOutlined/></a-button></a-tooltip>
      <a-input-number :value="currentPage" :min="1" :max="pages.length||1" size="small" @change="jumpToPage"/><span>/ {{pages.length||1}}</span>
      <a-tooltip v-if="editable" title="拖动框选图表或区域"><a-button :type="regionMode?'primary':'default'" @click="regionMode=!regionMode"><BorderOutlined/> 区域批注</a-button></a-tooltip>
    </div>
    <div ref="stage" class="pdf-pages" :class="{'region-mode':regionMode}" @mouseup="createTextAnnotation">
      <div v-for="page in pages" :key="page.number" class="pdf-page" :data-page="page.number" :style="{width:`${page.width*scale}px`,height:`${page.height*scale}px`}">
        <canvas/>
        <div class="textLayer"></div>
        <template v-for="annotation in pageAnnotations.get(page.number)||[]" :key="annotation.id">
          <button type="button" class="pdf-annotation-group" :class="[`mark-${(annotation.mark_type||(annotation.comment?'COMMENT':'HIGHLIGHT')).toLowerCase()}`,`color-${(annotation.color||'YELLOW').toLowerCase()}`,{selected:selectedAnnotationId===annotation.id}]" :title="annotation.mark_type==='COMMENT'?'查看批注':'查看标记'" @click.stop="selectExisting(annotation.id,$event)">
            <span v-for="(rect,index) in annotation.anchor.rects" :key="index" :data-annotation-id="index===0?annotation.id:null" :style="{left:`${rect.x*100}%`,top:`${rect.y*100}%`,width:`${rect.width*100}%`,height:`${rect.height*100}%`}"/>
          </button>
          <button v-if="(annotation.mark_type||(annotation.comment?'COMMENT':'HIGHLIGHT'))==='COMMENT'" type="button" class="pdf-comment-bubble" :class="[`color-${(annotation.color||'YELLOW').toLowerCase()}`,{selected:selectedAnnotationId===annotation.id}]" :data-comment-annotation-id="annotation.id" :style="{left:`${(annotation.anchor.rects.at(-1).x+annotation.anchor.rects.at(-1).width)*100}%`,top:`${(annotation.anchor.rects.at(-1).y+annotation.anchor.rects.at(-1).height/2)*100}%`}" :aria-label="`查看第 ${annotation.ordinal} 条批注`" @click.stop="selectExisting(annotation.id,$event,true)">{{annotation.ordinal}}</button>
        </template>
        <div v-if="regionMode" class="pdf-region-capture" @pointerdown="regionStart($event,page.number)" @pointermove="regionMove" @pointerup="regionEnd"/>
        <span v-if="draftRect?.page===page.number" class="pdf-region-draft" :style="{left:`${draftRect.x*100}%`,top:`${draftRect.y*100}%`,width:`${draftRect.width*100}%`,height:`${draftRect.height*100}%`}"/>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pdf-viewer-shell{display:flex;min-height:0;height:100%;flex-direction:column}.pdf-viewer-toolbar{position:sticky;top:0;z-index:5;display:flex;align-items:center;justify-content:center;gap:8px;min-height:52px;padding:8px;border-bottom:1px solid #d9e1e8;background:#fff}.pdf-viewer-toolbar>span{min-width:44px;color:#526579;text-align:center}.pdf-pages{flex:1;overflow:auto;padding:24px;background:#e9edf1}.pdf-page{position:relative;margin:0 auto 22px;background:#fff;box-shadow:0 2px 8px rgba(25,43,62,.18)}.pdf-page canvas{position:absolute;inset:0;width:100%;height:100%}.pdf-page :deep(.textLayer){position:absolute;inset:0;overflow:hidden;line-height:1;opacity:1}.pdf-annotation-group{position:absolute;inset:0;z-index:3;padding:0;border:0;background:transparent;pointer-events:none}.pdf-annotation-group span{position:absolute;border-radius:2px;background:transparent;pointer-events:auto;cursor:pointer;mix-blend-mode:multiply}.pdf-annotation-group.color-yellow{--mark:#f6bd16;--mark-bg:rgba(246,189,22,.34)}.pdf-annotation-group.color-green{--mark:#52a339;--mark-bg:rgba(82,163,57,.27)}.pdf-annotation-group.color-red{--mark:#e24a4a;--mark-bg:rgba(226,74,74,.24)}.pdf-annotation-group.color-blue{--mark:#3182ce;--mark-bg:rgba(49,130,206,.24)}.pdf-annotation-group.mark-highlight span,.pdf-annotation-group.mark-comment span{background:var(--mark-bg)}.pdf-annotation-group.mark-underline span{box-shadow:inset 0 -3px 0 var(--mark)}.pdf-annotation-group.mark-strikethrough span:after{position:absolute;top:50%;right:0;left:0;height:2px;background:var(--mark);content:''}.pdf-annotation-group.selected span{outline:2px solid var(--mark);outline-offset:2px;animation:pdf-annotation-pulse .8s ease}.pdf-comment-bubble{position:absolute;z-index:4;display:grid;width:22px;height:22px;place-items:center;transform:translate(5px,-50%);border:2px solid #fff;border-radius:50%;color:#fff;background:#1677ff;box-shadow:0 1px 5px rgba(22,59,96,.3);font-size:11px;cursor:pointer}.pdf-comment-bubble.selected{background:#0958d9;outline:3px solid rgba(22,119,255,.2)}.pdf-region-capture{position:absolute;inset:0;z-index:5;cursor:crosshair}.pdf-region-draft{position:absolute;z-index:6;border:2px solid #1677ff;background:rgba(22,119,255,.12);pointer-events:none}.region-mode :deep(.textLayer){user-select:none}@keyframes pdf-annotation-pulse{50%{filter:brightness(1.22)}}@media(max-width:760px){.pdf-pages{padding:12px}.pdf-viewer-toolbar{flex-wrap:wrap}.pdf-viewer-toolbar .ant-input-number{width:64px}}
.pdf-annotation-group.selected{z-index:4}.pdf-annotation-group.selected span{outline:0}.pdf-comment-bubble{z-index:5}.pdf-comment-bubble.selected{z-index:6}.pdf-region-capture{z-index:7}.pdf-region-draft{z-index:8}
.pdf-annotation-group.color-purple{--mark:#8b5cf6;--mark-bg:rgba(139,92,246,.27)}.pdf-comment-bubble.color-purple{background:#7c3aed}.pdf-comment-bubble.color-purple.selected{background:#6d28d9;outline-color:rgba(139,92,246,.22)}
.pdf-annotation-group.mark-comment span{pointer-events:none}
</style>
