<script setup>
import { ref } from 'vue'
const props = defineProps({ modelValue: Number, min: { type: Number, default: 160 }, max: { type: Number, default: 440 }, reverse: Boolean, label: String })
const emit = defineEmits(['update:modelValue'])
const dragging = ref(false)
let startX = 0
let startWidth = 0
function change(value) { emit('update:modelValue', Math.round(Math.max(props.min, Math.min(props.max, value)))) }
function start(event) {
  if (event.button !== 0) return
  startX = event.clientX
  startWidth = props.modelValue
  dragging.value = true
  event.currentTarget.setPointerCapture(event.pointerId)
}
function move(event) {
  if (dragging.value) change(startWidth + (event.clientX - startX) * (props.reverse ? -1 : 1))
}
</script>

<template>
  <div class="material-resize-handle" :class="{ dragging }" role="separator" aria-orientation="vertical" :aria-label="label" :aria-valuenow="modelValue" :aria-valuemin="min" :aria-valuemax="max" tabindex="0" @pointerdown.prevent="start" @pointermove="move" @pointerup="dragging = false" @lostpointercapture="dragging = false" @pointercancel="dragging = false" @keydown.left.prevent="change(modelValue + (reverse ? 16 : -16))" @keydown.right.prevent="change(modelValue + (reverse ? -16 : 16))" />
</template>
