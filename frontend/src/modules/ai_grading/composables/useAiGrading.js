import { computed, onBeforeUnmount, ref } from 'vue'
import { api } from '../../../api'

export function useAiGrading(assignmentId) {
  const selectedIds = ref([])
  const job = ref(null)
  const drafts = ref({})
  const loading = ref(false)
  let timer
  const progress = computed(() => job.value ? `${job.value.completed_count + job.value.failed_count}/${job.value.total_count}` : '')

  async function start() {
    if (!selectedIds.value.length) return
    loading.value = true
    job.value = await api(`/assignments/${assignmentId}/ai-grading/jobs`, { method: 'POST', body: JSON.stringify({ submission_version_ids: selectedIds.value }) })
    await poll()
  }
  async function poll() {
    if (!job.value) return
    job.value = await api(`/assignments/${assignmentId}/ai-grading/jobs/${job.value.id}`)
    ;(job.value.drafts || []).forEach(item => { drafts.value[item.submission_version_id] = item })
    if (['PENDING', 'RUNNING'].includes(job.value.status)) timer = setTimeout(poll, 1500)
    else loading.value = false
  }
  async function loadDraft(versionId) {
    const result = await api(`/assignments/${assignmentId}/submissions/${versionId}/ai-grading-draft`)
    drafts.value[versionId] = result.draft
    return result.draft
  }
  async function accept(versionId, grade, comment) {
    return api(`/assignments/${assignmentId}/submissions/${versionId}/ai-grading-draft/accept`, { method: 'POST', body: JSON.stringify({ grade, comment }) })
  }
  async function retry(versionId) {
    const result = await api(`/assignments/${assignmentId}/submissions/${versionId}/ai-grading-draft/retry`, { method: 'POST' })
    drafts.value[versionId] = result
    return result
  }
  onBeforeUnmount(() => clearTimeout(timer))
  return { selectedIds, job, drafts, loading, progress, start, poll, loadDraft, accept, retry }
}
