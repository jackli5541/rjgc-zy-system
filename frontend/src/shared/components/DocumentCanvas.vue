<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({ scale: { type: Number, default: 100 }, fillViewport: Boolean })
const root = ref(null)
const canvasWidth = ref(1)
const ratio = computed(() => props.scale / 100)
let observer

onMounted(() => {
  // Source editing uses a fixed CSS viewport, so scrollbar changes must not
  // feed back into measured canvas dimensions.
  if (props.fillViewport) return
  const viewport = root.value?.parentElement
  if (!viewport) return
  const measure = () => {
    const style = getComputedStyle(viewport)
    canvasWidth.value = Math.max(1, viewport.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight))
  }
  observer = new ResizeObserver(measure)
  observer.observe(viewport)
  measure()
})
onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
  <div ref="root" class="document-canvas-stage" :class="{ 'fills-viewport': fillViewport }" :style="{ width: fillViewport ? '100%' : `${Math.max(canvasWidth, canvasWidth * ratio)}px` }">
    <div class="document-canvas-surface" :style="{ width: fillViewport ? `${scale}%` : `${canvasWidth}px`, height: fillViewport ? '100%' : undefined, zoom: ratio }"><slot /></div>
  </div>
</template>

<style scoped>
.document-canvas-stage{display:flex;justify-content:center;align-items:flex-start;min-height:100%}
.document-canvas-surface{flex:none;min-width:0;background:#fff;box-shadow:0 1px 4px rgba(27,45,63,.12)}
.document-canvas-stage.fills-viewport{display:block;height:100%;min-height:0;overflow-x:auto;overflow-y:hidden}
.fills-viewport>.document-canvas-surface{margin-inline:auto}
</style>
