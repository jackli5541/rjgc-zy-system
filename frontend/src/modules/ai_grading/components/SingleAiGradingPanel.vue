<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { createGradingReveal } from '../gradingReveal'
const props = defineProps({ draft: { type: Object, default: null }, loading: Boolean, phase: { type: String, default: 'QUEUED' }, error: { type: String, default: '' }, disabled: Boolean, adopted: Boolean, animate: Boolean })
const emit = defineEmits(['adopt', 'retry'])
const showPrevious = ref(false)
const displayed = ref({ reason: '', points: [], comment: '', typing: false })
const reveal = createGradingReveal(value => { displayed.value = value })
const reducedMotion = typeof window !== 'undefined' ? window.matchMedia?.('(prefers-reduced-motion: reduce)') : null
function handleMotionChange(event) { if (event.matches && displayed.value.typing) reveal.finish() }
reducedMotion?.addEventListener('change', handleMotionChange)
watch([() => props.draft, () => props.loading, () => props.error, () => props.animate], () => {
  const ready = !props.loading && !props.error && props.draft?.status === 'READY'
  reveal.show(ready ? props.draft : null, Boolean(ready && props.animate && !reducedMotion?.matches))
}, { immediate: true })
function adopt() {
  if (props.disabled || props.adopted) return
  if (displayed.value.typing) reveal.finish()
  emit('adopt', props.draft)
}
function retry() {
  reveal.cancel()
  emit('retry')
}
onBeforeUnmount(() => {
  reveal.cancel()
  reducedMotion?.removeEventListener('change', handleMotionChange)
})
watch(() => props.draft, () => { showPrevious.value = false })
</script>

<template>
  <a-card title="AI 批改建议" size="small" class="single-ai-grading-panel" aria-live="polite">
    <p v-if="loading">{{ phase === 'QUEUED' ? '等待后台处理当前作业…' : '正在按教师评分标准生成建议…' }}</p>
    <a-alert v-else-if="error" type="error" :message="error" show-icon />
    <template v-else-if="draft?.status === 'READY'">
      <div class="ai-grade-actions"><strong>建议等级：{{ draft.suggested_grade }}</strong><a-button type="primary" :disabled="disabled || adopted" @click="adopt">{{ adopted ? '已采用' : '采用建议' }}</a-button></div>
      <a-button v-if="displayed.typing" size="small" @click="reveal.finish()">显示全部</a-button>
      <a-alert v-if="draft.materials_changed" type="info" message="批改材料已更新" show-icon />
      <a-alert v-else-if="draft.grade_changed" type="warning" :message="`上次 ${draft.previous_result.suggested_grade} → 本次 ${draft.suggested_grade}`" show-icon>
        <template #description><p>上次理由：{{ draft.previous_result.analysis?.grade_reason }}</p><p>本次理由：{{ draft.analysis?.grade_reason }}</p></template>
      </a-alert>
      <p class="ai-suggested-comment"><strong>定级理由：</strong>{{ displayed.reason }}</p>
      <details><summary>查看判定明细</summary>
      <a-list size="small" :data-source="draft.analysis?.criteria_results || []">
        <template #renderItem="{ item }"><a-list-item><span><strong>{{ item.criterion }}</strong>：{{ item.judgment }}<template v-if="item.evidence">（{{ item.evidence }}）</template></span></a-list-item></template>
      </a-list>
      </details>
      <div v-if="displayed.points.length"><strong>改进建议</strong><ul><li v-for="(point, index) in displayed.points" :key="index">{{ point }}</li></ul></div>
      <p v-if="displayed.comment" class="ai-suggested-comment"><strong>建议总评：</strong>{{ displayed.comment }}</p>
      <p class="ai-grading-hint">采用后可修改，请通过保存草稿或发布完成批阅。</p>
    </template>
    <template v-if="error && draft?.previous_result">
      <a-button @click="showPrevious = !showPrevious">{{ showPrevious ? '收起上次成功建议' : '查看上次成功建议' }}</a-button>
      <div v-if="showPrevious"><p>上次建议等级：{{ draft.previous_result.suggested_grade }}</p><p>{{ draft.previous_result.analysis?.grade_reason }}</p><p>{{ draft.previous_result.suggested_comment }}</p><details><summary>查看判定明细</summary><p v-for="(item, index) in draft.previous_result.analysis?.criteria_results || []" :key="index">{{ item.criterion }}：{{ item.judgment }}（{{ item.evidence }}）</p></details><p>历史建议仅供核对，请核对当前材料后再评分。</p></div>
    </template>
    <a-button v-if="!loading" :disabled="disabled" @click="retry">{{ error ? '重试' : '重新生成' }}</a-button>
  </a-card>
</template>

<style scoped>
.single-ai-grading-panel { flex-shrink: 0; overflow-wrap: anywhere; }
.ai-grade-actions { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
details { margin: 12px 0; }
summary { cursor: pointer; color: #176f9b; }
.ai-suggested-comment { white-space: pre-wrap; }
.ai-grading-hint { margin-top: 8px; color: #7b8998; font-size: 12px; }
</style>
