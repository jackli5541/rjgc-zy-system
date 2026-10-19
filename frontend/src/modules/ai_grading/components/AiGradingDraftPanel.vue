<script setup>
import { ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { useAiGrading } from '../composables/useAiGrading'

const props = defineProps({ assignmentId: { type: String, required: true }, submissionVersionId: { type: String, required: true } })
const { drafts, loadDraft, accept, retry } = useAiGrading(props.assignmentId)
const draft = ref(null)
const grade = ref('')
const comment = ref('')
async function load() {
  draft.value = await loadDraft(props.submissionVersionId)
  grade.value = draft.value?.suggested_grade || ''
  comment.value = draft.value?.suggested_comment || ''
}
async function save() {
  await accept(props.submissionVersionId, grade.value, comment.value)
  message.success('已提交教师评分')
}
async function retryDraft() { draft.value = await retry(props.submissionVersionId); await load() }
watch(() => props.submissionVersionId, load, { immediate: true })
</script>

<template>
  <a-card title="AI 批改建议" size="small">
    <a-spin :spinning="draft?.status === 'PROCESSING'">
      <a-alert v-if="draft?.error_message" type="error" :message="draft.error_message" show-icon />
      <template v-if="draft?.analysis">
        <p>{{ draft.analysis.summary }}</p>
        <a-list size="small" :data-source="draft.analysis.criteria_results || []">
          <template #renderItem="{ item }"><a-list-item><strong>{{ item.criterion }}</strong>：{{ item.judgment }}<span v-if="item.evidence">（{{ item.evidence }}）</span></a-list-item></template>
        </a-list>
        <a-form layout="vertical">
          <a-form-item label="建议等级"><a-select v-model:value="grade" :options="['A','B','C','D','E'].map(value => ({ label: value, value }))"/></a-form-item>
          <a-form-item label="教师评语"><a-textarea v-model:value="comment" :rows="4"/></a-form-item>
        </a-form>
        <a-space><a-button type="primary" @click="save">确认并提交评分</a-button><a-button @click="retryDraft">重新生成</a-button></a-space>
      </template>
    </a-spin>
  </a-card>
</template>
