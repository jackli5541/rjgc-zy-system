<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({ html: { type: String, default: '' }, annotations: { type: Array, default: () => [] }, editable: Boolean, selectedAnnotationId: { type: String, default: '' } })
const emit = defineEmits(['selection', 'select'])
const root = ref(null)
const highlights = ref([])
const blockSelector = 'p,h1,h2,h3,h4,li,blockquote,pre,td,th'

function assignBlocks() {
  root.value?.querySelectorAll(blockSelector).forEach((element, index) => { element.dataset.annotationBlock = `b${index}` })
}

function pointOffset(block, node, offset) {
  const range = document.createRange()
  range.selectNodeContents(block)
  range.setEnd(node, offset)
  return range.toString().length
}

function pointAt(block, targetOffset) {
  const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT)
  let consumed = 0
  let node
  while ((node = walker.nextNode())) {
    const next = consumed + node.textContent.length
    if (targetOffset <= next) return { node, offset: Math.max(0, targetOffset - consumed) }
    consumed = next
  }
  return { node: block, offset: block.childNodes.length }
}

function rebuildHighlights() {
  const container = root.value
  if (!container) return
  const containerRect = container.getBoundingClientRect()
  const items = []
  props.annotations.forEach((annotation, annotationIndex) => {
    const anchor = annotation.anchor || {}
    const startBlock = container.querySelector(`[data-annotation-block="${anchor.start?.block_id}"]`)
    const endBlock = container.querySelector(`[data-annotation-block="${anchor.end?.block_id}"]`)
    if (!startBlock || !endBlock) return
    try {
      const start = pointAt(startBlock, anchor.start.offset)
      const end = pointAt(endBlock, anchor.end.offset)
      const range = document.createRange()
      range.setStart(start.node, start.offset)
      range.setEnd(end.node, end.offset)
      const rects = Array.from(range.getClientRects()).filter(rect => rect.width && rect.height).map(rect => ({ left: rect.left - containerRect.left + container.scrollLeft, top: rect.top - containerRect.top + container.scrollTop, width: rect.width, height: rect.height }))
      if (!rects.length) return
      const last = rects[rects.length - 1]
      items.push({ id: annotation.id, ordinal: annotationIndex + 1, markType: annotation.mark_type || (annotation.comment ? 'COMMENT' : 'HIGHLIGHT'), color: annotation.color || 'YELLOW', rects, bubble: { left: last.left + last.width + 5, top: last.top + last.height / 2 } })
    } catch (_) { /* Invalid stale anchors are shown in the sidebar only. */ }
  })
  highlights.value = items
}

async function refresh() {
  await nextTick()
  assignBlocks()
  rebuildHighlights()
}

function createFromSelection() {
  if (!props.editable || !root.value) return
  const selection = window.getSelection()
  if (!selection || selection.isCollapsed || !selection.rangeCount) return
  const range = selection.getRangeAt(0)
  if (!root.value.contains(range.commonAncestorContainer)) return
  const startElement = range.startContainer.nodeType === Node.TEXT_NODE ? range.startContainer.parentElement : range.startContainer
  const endElement = range.endContainer.nodeType === Node.TEXT_NODE ? range.endContainer.parentElement : range.endContainer
  const startBlock = startElement?.closest?.('[data-annotation-block]')
  const endBlock = endElement?.closest?.('[data-annotation-block]')
  if (!startBlock || !endBlock) return
  const exact = selection.toString().trim()
  if (!exact) return
  const fullText = root.value.textContent || ''
  const globalRange = document.createRange()
  globalRange.selectNodeContents(root.value)
  globalRange.setEnd(range.startContainer, range.startOffset)
  const globalOffset = globalRange.toString().length
  const selectionRect = range.getBoundingClientRect()
  emit('selection', {
    kind: 'RICH_TEXT_RANGE',
    selectionType: 'TEXT',
    viewportRect: { left: selectionRect.left, top: selectionRect.top, right: selectionRect.right, bottom: selectionRect.bottom, width: selectionRect.width, height: selectionRect.height },
    anchor: {
      start: { block_id: startBlock.dataset.annotationBlock, offset: pointOffset(startBlock, range.startContainer, range.startOffset) },
      end: { block_id: endBlock.dataset.annotationBlock, offset: pointOffset(endBlock, range.endContainer, range.endOffset) },
      exact,
      prefix: fullText.slice(Math.max(0, globalOffset - 32), globalOffset),
      suffix: fullText.slice(globalOffset + exact.length, globalOffset + exact.length + 32)
    }
  })
}

function focusAnnotation(id) {
  if (!id) return
  root.value?.querySelector(`[data-annotation-id="${id}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

function selectExisting(id, event, openBubble = false) {
  const rect = event.currentTarget.getBoundingClientRect()
  emit('select', { id, openBubble, viewportRect: { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height } })
}

watch(() => props.html, refresh)
watch(() => props.annotations, refresh, { deep: true })
watch(() => props.selectedAnnotationId, focusAnnotation)
onMounted(() => { refresh(); window.addEventListener('resize', rebuildHighlights) })
onBeforeUnmount(() => window.removeEventListener('resize', rebuildHighlights))
</script>

<template>
  <div ref="root" class="rich-document" @mouseup="createFromSelection">
    <div class="rich-document-content" v-html="html"></div>
    <template v-for="highlight in highlights" :key="highlight.id">
      <button v-for="(rect,index) in highlight.rects" :key="`${highlight.id}-${index}`" type="button" class="rich-annotation-highlight" :class="[`mark-${highlight.markType.toLowerCase()}`,`color-${highlight.color.toLowerCase()}`,{selected:selectedAnnotationId===highlight.id}]" :data-annotation-id="index===0?highlight.id:null" :style="{left:`${rect.left}px`,top:`${rect.top}px`,width:`${rect.width}px`,height:`${rect.height}px`}" :title="highlight.markType==='COMMENT'?'查看批注':'查看标记'" @click.stop="selectExisting(highlight.id,$event)"/>
      <button v-if="highlight.markType==='COMMENT'" type="button" class="rich-comment-bubble" :class="{selected:selectedAnnotationId===highlight.id}" :data-comment-annotation-id="highlight.id" :style="{left:`${highlight.bubble.left}px`,top:`${highlight.bubble.top}px`}" :aria-label="`查看第 ${highlight.ordinal} 条批注`" @click.stop="selectExisting(highlight.id,$event,true)">{{highlight.ordinal}}</button>
    </template>
  </div>
</template>

<style scoped>
.rich-document{position:relative;width:min(860px,100%);min-height:100%;margin:0 auto;padding:42px 56px;background:#fff;box-shadow:0 1px 4px rgba(27,45,63,.12);color:#233446;line-height:1.75}.rich-document-content{position:relative;z-index:1}.rich-document :deep(h1),.rich-document :deep(h2),.rich-document :deep(h3){margin:1.3em 0 .55em;color:#17283a}.rich-document :deep(p){margin:.8em 0}.rich-document :deep(table){width:100%;border-collapse:collapse}.rich-document :deep(th),.rich-document :deep(td){padding:8px 10px;border:1px solid #cfd8e1}.rich-document :deep(pre){overflow:auto;padding:14px;border-radius:6px;background:#f3f6f8}.rich-document :deep(img){max-width:100%;height:auto}.rich-document :deep(input[type=checkbox]){margin-right:7px}.rich-annotation-highlight{position:absolute;z-index:2;padding:0;border:0;border-radius:2px;background:transparent;cursor:pointer;mix-blend-mode:multiply}.rich-annotation-highlight.color-yellow{--mark:#f6bd16;--mark-bg:rgba(246,189,22,.34)}.rich-annotation-highlight.color-green{--mark:#52a339;--mark-bg:rgba(82,163,57,.27)}.rich-annotation-highlight.color-red{--mark:#e24a4a;--mark-bg:rgba(226,74,74,.24)}.rich-annotation-highlight.color-blue{--mark:#3182ce;--mark-bg:rgba(49,130,206,.24)}.rich-annotation-highlight.mark-highlight,.rich-annotation-highlight.mark-comment{background:var(--mark-bg)}.rich-annotation-highlight.mark-underline{box-shadow:inset 0 -3px 0 var(--mark)}.rich-annotation-highlight.mark-strikethrough:after{position:absolute;top:50%;right:0;left:0;height:2px;background:var(--mark);content:''}.rich-annotation-highlight.selected{outline:2px solid var(--mark);outline-offset:2px;animation:annotation-pulse .8s ease}.rich-comment-bubble{position:absolute;z-index:4;display:grid;width:22px;height:22px;place-items:center;transform:translateY(-50%);border:2px solid #fff;border-radius:50%;color:#fff;background:#1677ff;box-shadow:0 1px 5px rgba(22,59,96,.3);font-size:11px;cursor:pointer}.rich-comment-bubble.selected{background:#0958d9;outline:3px solid rgba(22,119,255,.2)}@keyframes annotation-pulse{50%{filter:brightness(1.22)}}@media(max-width:760px){.rich-document{padding:26px 22px}}
.rich-annotation-highlight.selected{z-index:3;outline:0}.rich-comment-bubble.selected{z-index:5}
</style>
