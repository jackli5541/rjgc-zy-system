<script setup>
defineProps({ textScale: { type: Number, default: 100 }, defaultTextScale: { type: Number, default: 100 }, pageScale: { type: Number, default: 100 }, defaultPageScale: { type: Number, default: 100 }, showText: { type: Boolean, default: true } })
const emit = defineEmits(['update:textScale', 'update:pageScale'])
</script>

<template>
  <div class="document-scale-controls">
    <div v-if="showText" class="material-text-controls" role="group" aria-label="字号调节"><span class="material-scale-label">字号</span><button type="button" aria-label="缩小字号" :disabled="textScale <= 70" @click="emit('update:textScale', Math.max(70, textScale - 10))">A−</button><button class="document-scale-value" type="button" title="恢复默认字号" aria-label="恢复字号" @click="emit('update:textScale', defaultTextScale)">{{textScale}}%</button><button type="button" aria-label="放大字号" :disabled="textScale >= 180" @click="emit('update:textScale', Math.min(180, textScale + 10))">A＋</button></div>
    <div class="material-text-controls" role="group" aria-label="页面缩放"><span class="material-scale-label">页面</span><button type="button" aria-label="缩小页面" :disabled="pageScale <= 50" @click="emit('update:pageScale', Math.max(50, pageScale - 10))">−</button><button class="document-scale-value" type="button" title="恢复页面缩放" aria-label="恢复页面缩放" @click="emit('update:pageScale', defaultPageScale)">{{pageScale}}%</button><button type="button" aria-label="放大页面" :disabled="pageScale >= 200" @click="emit('update:pageScale', Math.min(200, pageScale + 10))">＋</button></div>
  </div>
</template>

<style scoped>
.document-scale-controls{display:flex;align-items:center;flex-wrap:wrap;gap:8px}
.material-text-controls{flex:0 0 auto}
.material-text-controls button{box-sizing:border-box;flex:0 0 36px;width:36px;padding-inline:0}
.material-text-controls .document-scale-value{flex-basis:56px;width:56px;font-variant-numeric:tabular-nums}
</style>
