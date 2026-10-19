<script setup>
import { ref } from 'vue'
import { message } from 'ant-design-vue'
import { useAiGrading } from '../composables/useAiGrading'

const props = defineProps({ assignmentId: { type: String, required: true }, submissionVersionIds: { type: Array, default: () => [] } })
const emit = defineEmits(['completed'])
const { job, loading, progress, start } = useAiGrading(props.assignmentId)
const running = ref(false)
async function run() {
  if (!props.submissionVersionIds.length) return message.info('请先选择未批改的提交')
  running.value = true
  try {
    const ids = props.submissionVersionIds
    const apiState = useAiGrading(props.assignmentId)
    apiState.selectedIds.value = ids
    await apiState.start()
    emit('completed', apiState.job.value)
  } catch (error) { message.error(error.message) }
  finally { running.value = false }
}
</script>

<template>
  <a-space wrap>
    <a-button type="primary" :loading="running || loading" :disabled="!submissionVersionIds.length" @click="run">AI 批量批改（{{ submissionVersionIds.length }}）</a-button>
    <a-tag v-if="job">任务进度 {{ progress }} · {{ job.status }}</a-tag>
  </a-space>
</template>
